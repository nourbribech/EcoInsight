# api.py
import time

import pythoncom
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
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
from GreenIT.collectors.windows import power_settings
from GreenIT.collectors.windows import scheduled_tasks
from GreenIT.collectors.windows import battery_health
from GreenIT.database.hardware_repository import HardwareRepository
from GreenIT.services.hardware_service import HardwareService
from GreenIT.services.estimation_loop import HARDWARE_DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI()

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


@app.get("/api/insights")
def insights():
    """
    Standing findings about how this machine is configured.

    Recomputed at most once a minute: reading the power policy costs ~310 ms
    of subprocess work, and the answer only changes when somebody opens
    Windows settings. Without the cache, a dashboard left open in a
    background tab would spawn powercfg processes forever — the exact kind of
    waste this project exists to report on.
    """
    settings = _cached("power_settings", POWER_SETTINGS_TTL_SECONDS,
                       power_settings.collect)
    wake = _cached("wake_tasks", WAKE_TASKS_TTL_SECONDS, scheduled_tasks.collect)

    # Machine identity does not change while the process runs, so this is
    # resolved once and kept — it costs a WMI round trip.
    profile = _cached("calibration", 86400, lambda: _with_com(_resolve_profile))

    observed = database.get_observed_behaviour(days=7)
    observed["wake_tasks"] = wake["wake_tasks"]
    observed["wake_tasks_available"] = wake["available"]
    battery = _cached("battery", 3600, lambda: _with_com(battery_health.collect))
    observed["battery_health_percent"] = battery["health_percent"]
    observed["battery"] = battery
    observed["calibration_source"] = profile.source
    observed["calibration_notes"] = profile.notes
    observed["machine_model"] = profile.machine_model

    findings = [f.to_dict() for f in config_audit.audit(settings, observed)]
    return {"settings": settings, "observed": observed, "findings": findings}


@app.get("/api/lifecycle")
def machine_lifecycle(days: int = 7):
    """
    Manufacturing carbon against operating carbon, plus battery wear.

    Separate from /api/summary because it answers a different question on a
    different timescale: the summary is about this week, this is about whether
    the machine should still be here in three years.
    """
    profile = _cached("calibration", 86400, lambda: _with_com(_resolve_profile))
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
def summary(days: int = 7):
    """
    The period digest: what this machine used, how much of it was avoidable,
    and how that compares with the period before.

    This is the one endpoint that answers "how am I doing" rather than "what
    is happening" — the question the whole product is supposed to serve, and
    the one every chart on the dashboard was silently leaving to the user.
    """
    result = database.get_period_summary(days)
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
    result["offhours"] = database.get_offhours_summary(days)

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
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="dashboard")