# api.py
import asyncio
import json
import os
import sys
import time

import pythoncom
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from GreenIT.database import database
from GreenIT.database import settings_store
from GreenIT.estimators import goals
from GreenIT.estimators.process_catalog import label_for
from GreenIT.estimators import config_audit
from GreenIT.estimators import equivalences
from GreenIT.estimators import rating
from GreenIT.estimators import lifecycle
from GreenIT.estimators import workloads
# Aliased because the endpoint function below is also called `actions`.
from GreenIT.estimators import actions as actions_estimator
from GreenIT.collectors.windows import power_settings
from GreenIT.collectors.windows import scheduled_tasks
from GreenIT.collectors.windows import battery_health
from GreenIT.collectors.windows import wsl
from GreenIT.database.hardware_repository import HardwareRepository
from GreenIT.database import calibration_writer
from GreenIT.database.calibration_writer import (
    CalibrationWriter, CalibrationWriteError, CalibrationPermissionError)
from GreenIT.services.hardware_service import HardwareService
from GreenIT.services.estimation_loop import HARDWARE_DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI()


def _get_it_mode_source() -> str | None:
    """
    How this session came to be in IT mode, or None if it is not.

    Reported so the UI knows whether leaving is even possible. A session
    started with `--mode it` cannot be returned to a user view by clearing a
    stored preference — the flag would win again on the next request — so
    offering a button that appears to do nothing would be worse than
    explaining why there isn't one.
    """
    if getattr(app.state, "session_mode", None) == "it":
        return "flag"
    if settings_store.get(IT_MODE_UNLOCKED_KEY) == "true":
        return "unlocked"
    return None


def _get_session_mode() -> str:
    """
    Session mode from the CLI flag or the in-app unlock preference.

    Priority:
    1. --mode it command-line flag (for automated/headless scenarios)
    2. In-app IT mode unlock (for interactive use)
    3. Default: user mode
    """
    return "it" if _get_it_mode_source() else "user"


@app.get("/api/session")
def session_info():
    """Describe the local session and profile status without exposing coefficients."""
    profile_status = _profile_status()
    return {
        "mode": _get_session_mode(),
        # 'flag' cannot be undone from the UI, 'unlocked' can — see
        # _get_it_mode_source.
        "it_mode_source": _get_it_mode_source(),
        "database": getattr(app.state, "database_path", None),
        "calibration_database": str(HARDWARE_DB_PATH),
        # Whether THIS ACCOUNT could write a profile. Reported so the setup
        # screen can explain the situation up front instead of presenting a
        # form that fails on submit — and so the honest reason ("that file is
        # administrator-only") is visible rather than looking like a fault.
        "calibration_writable": CalibrationWriter(HARDWARE_DB_PATH).is_writable(),
        # False on a fresh machine, and false again whenever the basis of the
        # numbers changes - see _acknowledgement_token.
        "calibration_acknowledged": (
            settings_store.get(ACKNOWLEDGED_KEY)
            == _acknowledgement_token(profile_status)
        ),
        # IT setup wizard shown only once, on first IT login.
        "it_wizard_completed": settings_store.get(IT_WIZARD_COMPLETED_KEY) == "true",
        **profile_status,
    }

# Two of the things the insights endpoint needs are expensive subprocess
# calls, and they go stale at very different rates:
#
#   power policy   ~310 ms, changes the moment somebody edits Windows settings
#   wake timers    ~3 s,    changes only when software is installed
#
# One shared TTL would either re-run the 3-second query every minute or leave
# a setting the user just changed looking wrong for half an hour. Separate
# TTLs let each be as fresh as it needs to be and no fresher.
POWER_SETTINGS_TTL_SECONDS = 60
WAKE_TASKS_TTL_SECONDS = 1800
# ~340 ms of wsl.exe subprocess. A minute is short enough that shutting a
# distro down is reflected while the user still remembers doing it.
WSL_TTL_SECONDS = 60
# The digest aggregates over 145k+ measurement rows and takes ~2.2s. Its
# answer changes only as fast as measurements accumulate, and two views now
# ask for it, so caching it for one poll interval removes the duplication
# and most of the cost at once.
SUMMARY_TTL_SECONDS = 60

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl_seconds: float, produce):
    """Memoises `produce()` for `ttl_seconds`. Single-process, single-threaded
    reads — the API runs in one uvicorn worker, so no locking is needed."""
    entry = _cache.get(key)
    now = time.monotonic()
    if entry is not None and now - entry[0] < ttl_seconds:
        return entry[1]

    value = produce()
    _cache[key] = (now, value)
    return value

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/current")
def current():
    row = database.get_latest_measurement()
    return dict(row) if row else {}


@app.get("/api/history")
def history(hours: int = 24, buckets: int | None = None):
    """
    Measurement history for the last `hours`.

    Pass `buckets` to have the server downsample to at most that many
    points — required for anything beyond a few hours, since a 7-day
    window is ~54,000 raw rows / ~20 MB of JSON. Omitting it returns raw
    rows, which keeps existing callers working unchanged.
    """
    until = datetime.now()
    since = until - timedelta(hours=hours)

    if buckets is not None and buckets > 0:
        rows = database.get_measurements_bucketed(since, until, buckets)
    else:
        rows = database.get_measurements_since(since)

    return [dict(r) for r in rows]


@app.get("/api/telemetry")
def telemetry(hours: int = 24):
    since = datetime.now() - timedelta(hours=hours)
    rows = database.get_telemetry_since(since)
    return [dict(r) for r in rows]


@app.get("/api/recommendations")
def recommendations(hours: int = 24, limit: int = 20):
    since = datetime.now() - timedelta(hours=hours)
    rows = database.get_recommendations_since(since, limit)
    return [dict(r) for r in rows]


@app.get("/api/processes")
def top_processes(limit: int = 10):
    """
    The applications currently drawing the most CPU power.

    Returns the latest sample only. Updated on the telemetry cadence
    (~2 min), so polling this faster just refetches identical rows.
    """
    rows = database.get_latest_process_samples(limit)

    # `label` is added here rather than stored: it is a rendering concern, and
    # keeping it out of the table means improving the lookup improves every
    # historical row too, instead of only the ones written afterwards.
    return [dict(r, label=label_for(r["name"])) for r in rows]


def _with_com(produce):
    """
    Runs `produce` with COM initialised on this thread.

    COM state is PER THREAD, and FastAPI runs synchronous endpoints on a
    worker from its own pool which has never initialised it — so any WMI call
    raises x_wmi_uninitialised_thread. The same trap agent.py documents for
    the collection thread, one layer up.

    EVERY WMI CALL IN A REQUEST HAS TO GO THROUGH HERE. The first version
    wrapped only the profile lookup, and its CoUninitialize then tore COM down
    for the battery read that followed on the same thread. That failure was
    invisible: battery_health catches broadly on purpose, so a desktop with no
    battery and a torn-down COM apartment both report "no battery available".
    A defensive catch in the collector hid a real bug in the caller.
    """
    pythoncom.CoInitialize()
    try:
        return produce()
    finally:
        # Paired, so the pooled thread is left as it was found before being
        # handed to an unrelated request.
        pythoncom.CoUninitialize()


def _resolve_profile():
    """The calibration profile in force, measured or estimated."""
    service = HardwareService(HardwareRepository(HARDWARE_DB_PATH))
    return service.get_current_machine_profile()


def _cached_profile():
    """
    The resolved profile, re-read whenever hardware.db changes on disk.

    A plain 24-hour memo was wrong across processes. The write that adds a
    profile drops the cache in the process that performed it, and no other -
    so an IT session could store a profile and the employee's session, running
    beside it on another port, would keep serving the old one for a day. The
    demo made that obvious; the fleet case is worse, because IT calibrating a
    machine while its owner has the dashboard open is the normal way this
    happens.

    Keying on the file's modification time makes any change visible to every
    process within one poll, while still costing one stat() rather than a WMI
    round trip on each request.
    """
    try:
        stamp = HARDWARE_DB_PATH.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return _cached(f"calibration:{stamp}", 86400,
                   lambda: _with_com(_resolve_profile))


_SETUP_STATE = {"measured": "calibrated", "entered": "entered",
                "estimated": "estimated"}


def _profile_status() -> dict:
    """Return setup information safe for both user and IT sessions."""
    # The override used to short-circuit here and report
    # calibration_source: null / setup_state: "unconfigured". That was a lie
    # of omission: the rest of the app resolved the profile normally and got
    # "estimated", so /api/session and /api/actions disagreed inside one
    # process about what coefficients were in use. The override belongs to
    # HardwareService, which already honours it - so this now resolves like
    # everything else and simply reports what it finds.
    try:
        profile = _cached_profile()
        return {
            "machine_model": profile.machine_model,
            "calibration_source": profile.source,
            "calibration_notes": profile.notes,
            "calibrated_at": profile.calibrated_at,
            # Three states, matching the three provenances. "entered" is its
            # own answer rather than being folded into either neighbour: it is
            # not a measurement, but somebody did deliberately configure this
            # model, which is more than a TDP scaling.
            "setup_state": _SETUP_STATE.get(profile.source, "unconfigured"),
        }
    except Exception as error:  # noqa: BLE001 - setup status must not kill the UI
        return {
            "machine_model": None,
            "calibration_source": None,
            "calibration_notes": str(error),
            "calibrated_at": None,
            "setup_state": "unconfigured",
        }


def _configuration_state() -> tuple[dict, dict]:
    """
    The settings and observed behaviour the configuration audit runs against.

    Factored out because /api/insights and /api/actions both need exactly
    this, and every line of it is a cached subprocess or a WMI round trip.
    Duplicating it would have been correct and slow.
    """
    settings = _cached("power_settings", POWER_SETTINGS_TTL_SECONDS,
                       power_settings.collect)
    wake = _cached("wake_tasks", WAKE_TASKS_TTL_SECONDS, scheduled_tasks.collect)

    # Machine identity does not change while the process runs, so this is
    # resolved once and kept — it costs a WMI round trip.
    profile = _cached_profile()

    observed = database.get_observed_behaviour(days=7)
    observed["wake_tasks"] = wake["wake_tasks"]
    observed["wake_tasks_available"] = wake["available"]
    battery = _cached("battery", 3600, lambda: _with_com(battery_health.collect))
    observed["battery_health_percent"] = battery["health_percent"]
    observed["battery"] = battery
    observed["calibration_source"] = profile.source
    observed["calibration_notes"] = profile.notes
    observed["machine_model"] = profile.machine_model

    return settings, observed


def _workload_state(days: int) -> tuple[dict, dict, object]:
    """The live WSL reading, its recorded history, and the profile to price it."""
    reading = _cached("wsl", WSL_TTL_SECONDS, wsl.collect)
    history = database.get_workload_history("wsl", days)
    profile = _cached_profile()
    return reading, history, profile


@app.get("/api/actions")
def actions(days: int = 7):
    """
    Every standing finding, from every rule, in one ranked list.

    The dashboard had grown three separate places telling the user to act,
    with no ranking between them — and once the page was split into views,
    the workload findings ended up on a different tab from the configuration
    ones. Ranking is domain logic, so it happens here rather than in the
    browser: the rule is then testable, and the panel makes one request
    instead of two.

    Both halves are already memoised by _cached, so the cost after the first
    call is a couple of SQLite aggregates.
    """
    settings, observed = _configuration_state()
    reading, history, profile = _workload_state(days)

    ranked = actions_estimator.rank([
        ("power settings", config_audit.audit(settings, observed)),
        ("developer workloads",
         workloads.assess(reading, history, profile.cpu.watts_per_percent_usage)),
    ])

    return {
        "actions": [a.to_dict() for a in ranked],
        "summary": actions_estimator.summarise(ranked),
        # Carried so the panel can mark anything derived from an estimated
        # profile, exactly as the individual panels already do.
        "calibration_source": profile.source,
    }


@app.get("/api/insights")
def insights():
    """
    Standing findings about how this machine is configured.

    Kept alongside /api/actions rather than replaced by it: this returns the
    raw settings and observed behaviour as well as the findings, which is
    what makes it useful for debugging a rule that fired when it should not
    have. /api/actions answers "what should I do", this answers "why did it
    say that".

    Recomputed at most once a minute: reading the power policy costs ~310 ms
    of subprocess work, and the answer only changes when somebody opens
    Windows settings. Without the cache, a dashboard left open in a
    background tab would spawn powercfg processes forever — the exact kind of
    waste this project exists to report on.
    """
    settings, observed = _configuration_state()
    findings = [f.to_dict() for f in config_audit.audit(settings, observed)]
    return {"settings": settings, "observed": observed, "findings": findings}


@app.get("/api/workloads")
def workload_findings(days: int = 7):
    """
    Developer workloads left running - today, WSL distributions.

    The live reading is cached for a minute: it costs a `wsl.exe` subprocess
    (~340 ms), and a dashboard left open in a background tab must not spawn
    one of those per poll. That would be the same waste this project reports
    on, committed by the reporting tool.

    Note the CPU figure comes from whichever process object the cache is
    holding, so it is an average over the gap since the last call rather than
    an instantaneous sample - which is the more useful number anyway.
    """
    reading, history, profile = _workload_state(days)
    findings = workloads.assess(
        reading, history, profile.cpu.watts_per_percent_usage)

    return {
        "wsl": reading,
        "history": history,
        "findings": [f.to_dict() for f in findings],
        # Carried so the panel can mark figures derived from an estimated
        # profile, exactly as the config audit does.
        "calibration_source": profile.source,
        "days": days,
    }


@app.get("/api/lifecycle")
def machine_lifecycle(days: int = 7):
    """
    Manufacturing carbon against operating carbon, plus battery wear.

    Separate from /api/summary because it answers a different question on a
    different timescale: the summary is about this week, this is about whether
    the machine should still be here in three years.
    """
    profile = _cached_profile()
    battery = _cached("battery", 3600, lambda: _with_com(battery_health.collect))

    period = database.get_period_summary(days)
    # Scale the measured period to a year. Under-counts whenever the agent was
    # not running for the whole window, which biases the comparison AGAINST
    # the point being made - real operating emissions are higher, so the
    # manufacturing multiple shown here is a floor.
    annual_kg = period["current"]["grams_co2eq"] / 1000 * (365 / days)

    result = lifecycle.assess(profile.machine_model, annual_kg).to_dict()
    result["machine_model"] = profile.machine_model
    result["battery"] = battery
    result["measured_days"] = days
    return result


ACKNOWLEDGED_KEY = "calibration_acknowledged"
IT_WIZARD_COMPLETED_KEY = "it_wizard_completed"
IT_MODE_UNLOCKED_KEY = "it_mode_unlocked"


def _acknowledgement_token(status: dict) -> str:
    """
    What the user actually agreed to.

    Storing a bare "yes" would be wrong: somebody who accepted estimated
    figures on a new laptop has not thereby accepted a different set of
    coefficients somebody typed in three weeks later. Keying the
    acknowledgement to the model AND its provenance means the notice returns
    exactly when the basis of the numbers changes, and stays quiet otherwise.
    """
    return f"{status.get('machine_model')}|{status.get('calibration_source')}"


@app.post("/api/session/acknowledge")
def acknowledge_calibration():
    """Records that the user has seen how this machine's figures are derived."""
    settings_store.set(ACKNOWLEDGED_KEY, _acknowledgement_token(_profile_status()))
    return session_info()


@app.post("/api/it/wizard-complete")
def complete_it_wizard():
    """Records that the IT user has completed the setup wizard."""
    settings_store.set(IT_WIZARD_COMPLETED_KEY, "true")
    return {"completed": True}


@app.post("/api/session/unlock-it")
def unlock_it_mode():
    """Unlock IT mode for this account if they have write permission to hardware.db."""
    writable = CalibrationWriter(HARDWARE_DB_PATH).is_writable()
    if not writable:
        raise HTTPException(
            status_code=403,
            detail="This account cannot write the calibration database. "
            "On a managed machine that file is administrator-only, "
            "which is what stops calibration being changed from a normal session.",
        )

    settings_store.set(IT_MODE_UNLOCKED_KEY, "true")
    return session_info()


@app.post("/api/session/lock-it")
def lock_it_mode():
    """
    Return this session to the employee view.

    Only undoes the in-app unlock. A session started with `--mode it` stays in
    IT mode, and says so rather than pretending to have changed something: the
    flag is re-read on every request and would win immediately.

    Nothing is verified before allowing this. Leaving a privileged view is not
    a privileged act, and a check that could fail would mean somebody could be
    stuck in a screen they did not want to be in.
    """
    if getattr(app.state, "session_mode", None) == "it":
        raise HTTPException(
            status_code=409,
            detail=(
                "This session was started with --mode it. Restart the agent "
                "without that flag to use the employee view."
            ),
        )

    settings_store.set(IT_MODE_UNLOCKED_KEY, "false")
    return session_info()


async def _run_sweep(quick: bool) -> dict:
    """
    Run the automated calibration in a child process and return its result.

    A CHILD PROCESS, NOT A THREAD, AND NOT INLINE
    The sweep saturates every core for minutes at a time. Running it inside the
    API process would starve the uvicorn event loop and the estimation thread —
    the dashboard would stop answering during the exact window the user is
    watching it. It also spawns its own worker processes, which needs a real
    process to parent them.

    stdin is closed deliberately. Anything that tried to prompt an operator
    would hang the request until the timeout instead of failing immediately,
    and there is nobody at that end to answer.
    """
    command = [sys.executable, "-m",
               "GreenIT.scripts.calibration.auto_calibration", "--json"]
    if quick:
        command.append("--quick")

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Generous margin over the plan itself: a quick sweep is ~75s and a full
    # one ~6 min, but a machine under load samples slower than it plans to.
    timeout = 300 if quick else 1800

    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(
            status_code=504,
            detail=f"Calibration exceeded {timeout // 60} minutes and was stopped.",
        )

    output = stdout_data.decode(errors="replace").strip()

    # The script reports an expected refusal as JSON on stdout AND a non-zero
    # exit code, so the exit code alone cannot distinguish "the machine is
    # plugged in" from "the module failed to import". Parse first, and only
    # treat it as a crash when there is nothing to parse.
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break

    raise HTTPException(
        status_code=500,
        detail=(stderr_data.decode(errors="replace").strip()
                or "Calibration produced no result."),
    )


@app.post("/api/calibration/run")
async def run_calibration_sweep(quick: bool = True):
    """
    Measure this machine and store the profile.

    Returns 200 with `ok: false` for a refusal the operator needs to read —
    a plugged-in machine, or a fit too weak to store. Those are answers the
    procedure is supposed to produce, not faults, and an HTTP error code would
    push them into a failure path that hides the explanation.
    """
    if _get_session_mode() != "it":
        raise HTTPException(status_code=403, detail="IT mode required")

    if not CalibrationWriter(HARDWARE_DB_PATH).is_writable():
        raise HTTPException(
            status_code=403,
            detail="This account cannot write the calibration database.",
        )

    # No cache to drop: _cached_profile keys on hardware.db's mtime, so a
    # profile written by the sweep is visible to this process and to every
    # other session within one poll.
    return await _run_sweep(quick)


class CalibrationInput(BaseModel):
    """One profile as the IT setup form submits it."""
    machine_model: str
    cpu_watts_per_percent: float
    ram_watts_per_gb: float
    baseline_watts: float
    notes: str = ""
    # Honoured only on import, never on the form — see _save_profiles.
    source: str = "entered"


class CalibrationImport(BaseModel):
    profiles: list[CalibrationInput]


def _profile_dict(profile) -> dict:
    return {
        "machine_model": profile.machine_model,
        "cpu_watts_per_percent": profile.cpu.watts_per_percent_usage,
        "ram_watts_per_gb": profile.ram.watts_per_gb_used,
        "baseline_watts": profile.baseline_watts,
        "source": profile.source,
        "notes": profile.notes,
        "calibrated_at": profile.calibrated_at,
    }


def _current_machine_key() -> str | None:
    """The key this machine will look itself up by, so the form can prefill
    it. Getting it wrong by a character means the profile is never found."""
    try:
        return _with_com(_resolve_profile).machine_model
    except Exception:  # noqa: BLE001 - a prefill is not worth an error page
        return None


@app.get("/api/calibration")
def calibration_profiles():
    """
    Every stored profile, plus whether this account may add one.

    Listing them is not decoration: somebody about to type coefficients in
    should first see whether an identical model has already been swept, which
    is the difference between copying a measurement and inventing one.
    """
    writer = CalibrationWriter(HARDWARE_DB_PATH)
    try:
        profiles = [_profile_dict(p)
                    for p in HardwareRepository(HARDWARE_DB_PATH).list_profiles()]
        error = None
    except Exception as failure:  # noqa: BLE001
        profiles, error = [], str(failure)

    return {
        "profiles": profiles,
        "writable": writer.is_writable(),
        "database": str(HARDWARE_DB_PATH),
        "current_machine_key": _current_machine_key(),
        "limits": {
            "cpu_watts_per_percent": calibration_writer.CPU_WATTS_PER_PERCENT_RANGE,
            "ram_watts_per_gb": calibration_writer.RAM_WATTS_PER_GB_RANGE,
            "baseline_watts": calibration_writer.BASELINE_WATTS_RANGE,
        },
        "error": error,
    }


def _save_profiles(entries: list[CalibrationInput],
                   allow_measured: bool = False) -> dict:
    """
    Shared by the single-profile save and the bulk import.

    `allow_measured` is the difference between them, and the first version
    got it wrong: it honoured whatever `source` the caller sent, so posting
    {"source": "measured"} to the form stored a typed-in guess with the
    authority of a discharge sweep - the precise hole this provenance chain
    exists to close.

    FORM (False): always "entered". Somebody is typing numbers; no field they
    can set should be able to say otherwise.

    IMPORT (True): preserve what the file says. Calibration is per MODEL, not
    per machine, so a profile swept on one laptop is genuinely measured for
    every identical unit - downgrading it on transport would destroy true
    information rather than protect anything.

    Neither is a security control. Anyone who can write hardware.db can write
    any row with sqlite3 directly, which is why the real gate is filesystem
    permission. This is an honesty control for the normal path, so that IT
    reading the label later can trust what it says.
    """
    writer = CalibrationWriter(HARDWARE_DB_PATH)
    saved = []
    try:
        # Backup before the first change, never after. hardware.db is the only
        # record of every sweep anybody has run, and re-measuring a model
        # costs hours of controlled battery discharge; the copy costs 20 KB.
        backup = str(writer.backup())
        for entry in entries:
            profile = writer.save(
                machine_model=entry.machine_model,
                cpu_watts_per_percent=entry.cpu_watts_per_percent,
                ram_watts_per_gb=entry.ram_watts_per_gb,
                baseline_watts=entry.baseline_watts,
                source=(entry.source if allow_measured
                        and entry.source in ("measured", "entered")
                        else "entered"),
                notes=entry.notes,
            )
            saved.append(_profile_dict(profile))
    except CalibrationPermissionError as denied:
        raise HTTPException(status_code=403, detail=str(denied)) from denied
    except CalibrationWriteError as invalid:
        raise HTTPException(status_code=400, detail=str(invalid)) from invalid

    # Other processes pick the change up on their own, because the profile
    # cache is keyed on hardware.db's mtime - see _cached_profile. The
    # estimation loop is the exception: it resolves coefficients once in its
    # constructor, so new MEASUREMENTS need a restart even though the
    # dashboard updates immediately. Hence restart_required below.

    return {
        "saved": saved,
        "backup": backup,
        "restart_required": True,
        "restart_note": (
            "The dashboard now uses the new profile. The collector resolves "
            "its coefficients once at startup, so restart the agent before "
            "new measurements use them."
        ),
    }


@app.post("/api/calibration")
def save_calibration(entry: CalibrationInput):
    """Create or replace one profile. Refuses on permission or validation.

    Always stored as "entered" regardless of what was submitted — see
    _save_profiles."""
    return _save_profiles([entry], allow_measured=False)


@app.post("/api/calibration/import")
def import_calibration(payload: CalibrationImport):
    """
    Load profiles produced by /api/calibration/export on another machine.

    This is how a sweep run on one laptop reaches the rest of the fleet
    without anybody touching source code. Without it, a profile entered on
    machine A never reaches machine B of the same model, and "calibrated by
    model" quietly becomes "calibrated per machine".
    """
    if not payload.profiles:
        raise HTTPException(status_code=400, detail="No profiles in the file.")
    return _save_profiles(payload.profiles, allow_measured=True)


@app.get("/api/calibration/export")
def export_calibration():
    """Every profile as a file IT can review, keep, or load elsewhere."""
    profiles = HardwareRepository(HARDWARE_DB_PATH).list_profiles()
    return {
        "exported_at": datetime.now().isoformat(),
        "source_machine": _current_machine_key(),
        "profiles": [_profile_dict(p) for p in profiles],
    }


@app.delete("/api/calibration/{machine_model:path}")
def delete_calibration(machine_model: str):
    """
    Remove a profile. The machine falls back to an estimated one at the next
    restart, which is the point: a fallback is never permanent, and neither
    is a mistake.
    """
    writer = CalibrationWriter(HARDWARE_DB_PATH)
    try:
        backup = str(writer.backup())
        removed = writer.delete(machine_model)
    except CalibrationPermissionError as denied:
        raise HTTPException(status_code=403, detail=str(denied)) from denied
    except CalibrationWriteError as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure

    if not removed:
        raise HTTPException(status_code=404, detail="No such profile.")

    # No cache to drop: the profile cache is keyed on hardware.db's mtime, so
    # deleting a row invalidates it in every process at once.
    return {"deleted": machine_model, "backup": backup, "restart_required": True}


class GoalUpdate(BaseModel):
    """`target_share` as a fraction (0.15) or a percentage (15) - see
    goals.normalise_target, which accepts both."""
    target_share: float


def _goal_payload() -> dict:
    """
    The weekly goal, this calendar week's progress, and last week's verdict.

    Both weeks are computed here rather than by the caller because the answer
    is meaningless without the pair: progress alone is a gauge, and it is the
    finished week that lets the user have actually met something.
    """
    target = goals.normalise_target(
        settings_store.get(goals.SETTING_KEY, goals.DEFAULT_TARGET_SHARE))

    now = datetime.now()
    start, end = goals.week_bounds(now)
    this_week = database.get_waste_between(start, now)
    # The full preceding week, both bounds fixed - a finished period, so its
    # verdict does not move once written.
    last_week = database.get_waste_between(start - timedelta(days=goals.WEEK_DAYS),
                                           start)

    status = goals.evaluate(target, this_week, now, this_week.get("typical_watts"))

    return {
        "target_share": target,
        "default_target_share": goals.DEFAULT_TARGET_SHARE,
        "minimum_target_share": goals.MINIMUM_TARGET_SHARE,
        "maximum_target_share": goals.MAXIMUM_TARGET_SHARE,
        # None until the user has set one, which lets the panel distinguish
        # "you chose 15%" from "nobody has chosen, so we assumed 15%".
        "chosen_at": settings_store.updated_at(goals.SETTING_KEY),
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "status": status.to_dict(),
        # Judged against the target held NOW, not the one in force last week.
        # That means changing the goal re-judges history, which is a real
        # choice and the right one here: the target is not stored per week, so
        # the alternative is a verdict against a number the user can no longer
        # see. For a soft goal, "if I had been aiming at 10% I would have
        # missed" is useful rather than dishonest.
        "previous_week": goals.verdict(target, last_week),
    }


@app.get("/api/goal")
def goal():
    return _goal_payload()


@app.put("/api/goal")
def set_goal(update: GoalUpdate):
    """
    Stores the target and returns the recomputed status in one round trip, so
    the panel re-renders against the new goal without a second fetch.

    Normalised before storing rather than on read: the stored value is then
    the one the user will be judged against, instead of a raw number that
    every reader has to remember to clamp.
    """
    settings_store.set(goals.SETTING_KEY,
                       goals.normalise_target(update.target_share))
    return _goal_payload()


@app.get("/api/summary")
def summary(days: int = 7, end: str | None = None):
    """Cached wrapper; `end` is an optional exclusive local-time boundary."""
    end_date = datetime.fromisoformat(end) if end else None
    cache_key = f"summary:{days}:{end or 'now'}"
    return _cached(cache_key, SUMMARY_TTL_SECONDS, lambda: _summary(days, end_date))


def _summary(days: int, end: datetime | None = None) -> dict:
    """
    The period digest: what this machine used, how much of it was avoidable,
    and how that compares with the period before.

    This is the one endpoint that answers "how am I doing" rather than "what
    is happening" — the question the whole product is supposed to serve, and
    the one every chart on the dashboard was silently leaving to the user.
    """
    result = database.get_period_summary(days, end)
    # Labelled here for the same reason /api/processes is: the mapping is a
    # rendering concern, so improving it improves history too.
    result["top_applications"] = [
        {**application, "label": label_for(application["name"])}
        for application in result["top_applications"]
    ]
    result["equivalences"] = [
        e.to_dict() for e in equivalences.for_energy(
            result["current"]["watt_hours"], result["current"]["grams_co2eq"])
    ]
    result["offhours"] = database.get_offhours_summary(days, end)

    # None when idle tracking has not run long enough to judge. The dashboard
    # renders that as "not enough data to rate yet" rather than hiding the
    # element, so an absent grade never reads as a good one.
    verdict = rating.rate_waste(result["idle_awake_share"], result["days_tracked"])
    result["rating"] = verdict.to_dict() if verdict else None
    result["rating_minimum_days"] = rating.MINIMUM_DAYS_TRACKED
    return result


# Serve the built dashboard from the same origin as the API, so the agent is
# a single process on a single port — open http://127.0.0.1:8000 and you get
# the UI, exactly the Netdata model.
#
# Mounted LAST on purpose: FastAPI matches routes in registration order, so
# every /api/* route above is resolved before this catch-all sees the request.
#
# html=True makes it serve index.html for unknown paths, which is what a
# single-page app needs for client-side routing.
#
# Guarded on existence because `npm run build` may not have been run yet —
# in dev the Vite server serves the UI on :5173 and proxies /api here, so
# this mount is simply unused.
class _Dashboard(StaticFiles):
    """
    StaticFiles with the cache policy a hashed-asset build needs.

    Starlette sends an ETag and a Last-Modified but no Cache-Control. With no
    Cache-Control at all a browser falls back to heuristic freshness and may
    serve index.html from cache without revalidating — and index.html is the
    one file that must never be stale, because it names which bundle to load.
    A cached copy points at a bundle that was deleted by the next build, and
    the page silently keeps rendering the old application. That is not
    theoretical: it cost an afternoon of debugging what looked like a frozen
    UI while every file on disk was correct.

    The inverse holds for everything else. Vite fingerprints asset filenames
    with a content hash, so a given URL's bytes can never change — those are
    safe to cache indefinitely, and saying so avoids a revalidation round trip
    on every load.
    """

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            # Revalidate every time; the ETag still saves the transfer when
            # nothing has changed.
            response.headers["cache-control"] = "no-cache"
        else:
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response


if FRONTEND_DIST.is_dir():
    app.mount("/", _Dashboard(directory=FRONTEND_DIST, html=True), name="dashboard")