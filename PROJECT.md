# EcoInsight — Project Documentation

> Software-based power, energy and carbon estimation for Windows workstations,
> with a live dashboard and a personalised recommendation engine.

---

## 1. What the project does

EcoInsight measures how much **electricity a Windows PC is consuming right now**,
without any external hardware (no wall meter, no smart plug), converts that into
**energy over time** and **CO₂ emissions**, stores the history locally, and warns
the user when their machine is behaving unusually badly.

The chain is always the same four steps:

```
raw OS metrics  →  power (W)  →  energy (Wh)  →  carbon (gCO₂eq)
   psutil/WMI       linear         P × Δt        Wh × grid intensity
                    model
```

The distinguishing idea of the project is that the power model is **not guessed
from datasheet TDP values** — it is *calibrated per machine model* by measuring
the laptop's own battery discharge rate under controlled loads, then fitting a
linear regression. Those regression coefficients are what the runtime uses.

**Target context:** a fleet of standardised company PCs in **Tunisia** (grid
carbon intensity ≈ 483 gCO₂eq/kWh, a >98 % gas-fired grid).

---

## 2. Repository layout

```
projets/
├── backend/                       # Python — collection, estimation, storage, API
│   ├── main.py                    # leftover FastAPI hello-world (NOT the real API)
│   ├── config.py                  # legacy global constants (mostly superseded)
│   ├── requirements.txt
│   └── GreenIT/                   # the actual application package
│       ├── collectors/            # layer 1 — raw OS readings
│       │   ├── collector.py           # aggregates everything
│       │   ├── hardware/              # psutil: cpu, memory, disk, network
│       │   └── windows/               # WMI/ctypes: display, power, session, identity
│       ├── models/                # layer 2 — typed data contracts (frozen dataclasses)
│       │   ├── runtime/               # cpu/memory/disk/network runtime metrics
│       │   ├── snapshot.py            # SystemMetricsSnapshot
│       │   ├── calibration.py         # CalibrationProfile
│       │   ├── power_estimate.py / energy_estimate.py / carbon_estimate.py
│       │   └── recommendation.py
│       ├── services/              # layer 3 — orchestration + stateful sampling
│       │   ├── metrics_polling_service.py
│       │   ├── hardware_service.py
│       │   └── estimation_loop.py     # the main runtime loop
│       ├── estimators/            # layer 4 — pure calculation
│       │   ├── power.py / energy.py / carbon.py
│       │   └── recommendations.py
│       ├── database/              # layer 5 — SQLite persistence
│       │   ├── database.py            # ecoinsight.db (history)
│       │   ├── hardware_repository.py # hardware.db (calibration, read-only)
│       │   └── data/hardware.db
│       ├── data/ecoinsight.db     # measurement + telemetry + recommendation history
│       ├── api/api.py             # FastAPI REST layer consumed by the frontend
│       └── scripts/               # developer tools, not runtime
│           ├── setup_hardware_db.py, migrate_drop_disk_column.py
│           ├── smoke_test_power_estimator.py, check telemetry.py
│           ├── recommendations_test.py
│           └── calibration/           # the measurement campaign toolkit
└── frontend/                      # React 19 + TypeScript + Vite dashboard
    └── src/
        ├── App.tsx                # still the Vite starter template
        ├── components/StatsBar.tsx
        ├── hooks/usePolling.tsx
        └── types/api.tsx
```

---

## 3. Architecture — the five layers

The codebase follows a strict one-way dependency rule:

```
collectors  →  models  ←  services  →  estimators  →  database
   (raw)       (contracts)  (glue)      (pure math)    (SQLite)
```

* **Estimators never touch the database, WMI or psutil.** They are pure functions
  of `SystemMetricsSnapshot` + `CalibrationProfile`. That is what makes them
  unit-testable and lets calibration data change without touching logic.
* **Collectors are stateless** "read right now" functions returning raw dicts.
  Anything requiring memory between reads (disk/network throughput) lives in the
  polling service.
* **Models are the contract** between layers — frozen dataclasses, no behaviour
  except computed properties.

### 3.1 Collectors (`GreenIT/collectors/`)

| File | Source | Provides |
|---|---|---|
| `hardware/cpu.py` | psutil | usage %, per-core usage, frequency, times, stats, core counts |
| `hardware/memory.py` | psutil | virtual + swap memory |
| `hardware/disk.py` | psutil | cumulative disk I/O counters |
| `hardware/network.py` | psutil | cumulative net I/O counters, interface stats |
| `hardware/cpu_info.py` | WMI | CPU model, cores, clock, socket (hardware identity) |
| `windows/display.py` | screen-brightness-control | brightness %, monitor count |
| `windows/power.py` | psutil + `powercfg` | battery, AC status, active power plan |
| `windows/session.py` | ctypes/user32 | idle seconds since last keyboard/mouse input |
| `windows/system_identity.py` | WMI | manufacturer + model, and `build_machine_key()` |

`build_machine_key()` is deliberately the **single** place that builds the
`"Dell Inc. Latitude 7480"` lookup key — both the runtime and the offline
calibration scripts must use it, otherwise calibration written by one path would
silently never match lookups from the other.

### 3.2 Services

**`MetricsPollingService.poll()`** — the only stateful object in the collection
path. psutil's disk/network counters are *cumulative since boot*, so throughput
requires two readings a known interval apart. It holds the previous counters and
timestamp, and returns a `SystemMetricsSnapshot`.
*The first call returns `None`* (nothing to diff against) — callers skip that
tick. Default interval: **1.5 s** (sub-second sampling makes throughput noisier,
not more accurate).

**`HardwareService.get_current_machine_profile()`** — resolves WMI identity →
machine key → `CalibrationProfile` from `hardware.db`. Called **once at startup**;
machine identity doesn't change mid-session.

**`EstimationLoop`** — the orchestrator, with no maths of its own:

```python
snapshot = polling.poll()                       # None on first tick
power    = power_estimator.estimate(snapshot, profile)
recs     = maybe_save_telemetry(snapshot, power.total_watts)  # every 120 s
energy   = energy_estimator.estimate(power, snapshot.timestamp)  # None on first tick
carbon   = carbon_estimator.estimate(energy)
database.save_measurement(...)
```

There are **two ticks of warm-up**, not one — the polling service and the energy
estimator each need a prior reading. Both `None` returns are expected behaviour.

Telemetry is written on a much slower cadence (**every 120 s**) than power
measurements, because the recommendation baseline only needs a rolling daily
picture — writing every tick would produce 80× more rows than useful.

### 3.3 Estimators — the actual maths

**Power** (`estimators/power.py`), a linear per-component model:

```
cpu_watts  = cpu_watts_per_percent_usage × cpu_usage_percent
ram_watts  = ram_watts_per_gb_used       × ram_used_gb
total      = cpu_watts + ram_watts + baseline_watts
```

`baseline_watts` covers the constant draw — motherboard, chipset, fans.
Disk was originally a fourth term but was **removed** (see
`scripts/migrate_drop_disk_column.py`): the measurable disk power delta sat below
the battery sensor's noise floor.

Current calibrated values for the reference machine (`hardware.db`):

| Coefficient | Value | Source |
|---|---|---|
| `cpu_watts_per_percent_usage` | 0.10532 W/% | battery-discharge regression over multiple sweeps |
| `ram_watts_per_gb_used` | 0.375 W/GB | literature value (delta below sensor noise) |
| `baseline_watts` | 1.9193 W | mean of 5 direct measurements, σ = 0.702 W |

**Energy** (`estimators/energy.py`) — integrates power over real elapsed time:
`interval_Wh = total_watts × Δt_hours`, plus a running cumulative total for the
session. Returns `None` on its first call (no previous timestamp).

**Carbon** (`estimators/carbon.py`) — `kgCO₂eq = kWh × 0.483`, the Tunisia grid
intensity. The factor is constructor-injected so the app can be deployed in
another region without editing the class. Same two-stage formula CodeCarbon uses.

**Recommendations** (`estimators/recommendations.py`) — statistical anomaly
detection against the user's *own* history, not fixed thresholds:

* Watches `cpu_usage_percent` and `ram_usage_percent`.
* Baseline = mean + standard deviation over the last **7 days** of
  `telemetry_history`, computed strictly *before* the current snapshot.
* Elevated when `(current − mean) / stdev ≥ 1.5`.
* Requires at least **3 days** of history before it says anything (cold-start gate).
* State machine per metric:
  * **not elevated → elevated**: notify immediately, with a *projection* —
    "if this continues for 1 h, ~X Wh / Y g CO₂eq".
  * **still elevated**: remind at most every **1.5 h**, this time with the
    *actual accumulated* Wh/gCO₂eq since it went elevated (summed from the real
    `measurements` table).
  * **elevated → normal**: reset silently, no "resolved" message.

### 3.4 Database

Two separate SQLite files with different lifecycles:

**`GreenIT/database/data/hardware.db`** — read-only at runtime, shipped
pre-populated, written only by calibration scripts.

```sql
calibration_profiles(
  machine_model TEXT PRIMARY KEY,
  cpu_watts_per_percent_usage REAL, ram_watts_per_gb_used REAL,
  baseline_watts REAL, calibrated_at TEXT, notes TEXT)
```

A missing machine model raises `UnknownMachineModelError` — a **deliberate hard
failure**, not a fallback to generic coefficients, since a wrong guess would
silently corrupt every downstream number.

**`GreenIT/data/ecoinsight.db`** — the local history, created/migrated on startup
by `initialize_database()`.

| Table | Written by | Cadence | Current rows |
|---|---|---|---|
| `measurements` | estimation loop | every tick (~1.5 s) | 53 805 |
| `telemetry_history` | estimation loop | every 120 s | 1 174 |
| `recommendations` | (see §7) | on trigger | table not yet created in the live file |
| `cpu_specs` | online-lookup cache | on demand | 0 (unused so far) |

### 3.5 API (`GreenIT/api/api.py`)

FastAPI, CORS-allowed for the Vite dev server at `http://localhost:5173`.

| Endpoint | Params | Returns |
|---|---|---|
| `GET /api/current` | – | latest `measurements` row, or `{}` |
| `GET /api/history` | `hours=24` | measurements since cutoff, ascending |
| `GET /api/telemetry` | `hours=24` | telemetry rows since cutoff |
| `GET /api/recommendations` | `hours=24`, `limit=20` | recommendations, newest first |

The API is **read-only**; it never runs the estimation loop. The loop is a
separate process writing to the same SQLite file.

### 3.6 Frontend

React 19 + TypeScript ~6 + Vite 8, with the React Compiler babel preset enabled.

* **`hooks/usePolling.tsx`** — generic hook: fetch a URL on an interval, expose
  `{data, error, loading}`, fire immediately rather than waiting for the first
  tick, and cancel cleanly on unmount so a late response can't set state on an
  unmounted component.
* **`components/StatsBar.tsx`** — polls `/api/current` every 5 s and renders
  three tiles: instantaneous power (with cpu/ram/baseline breakdown), cumulative
  energy, cumulative carbon. Uses a type-guard to distinguish a real reading from
  the empty `{}` the API returns when there is no data yet.
* **`types/api.tsx`** — `CurrentReading` mirroring the `measurements` schema.

---

## 4. The calibration methodology (`scripts/calibration/`)

This is the scientific core of the project and worth understanding separately.

**Ground truth without hardware:** `battery_power.read_discharge_watts()` reads
`Win32_BatteryStatus.DischargeRate` via WMI (`root\wmi` namespace) — the battery
fuel gauge reporting real total system draw in mW. It **requires the laptop to be
unplugged** and raises otherwise.

**Guard rails:**
* `check_battery_in_safe_range(30–100 %)` — below ~20 % Windows battery-saver
  throttles the CPU mid-sweep and silently changes what you're measuring; the
  fuel gauge is also noisier at the extremes of the charge curve.
* `sample_average_watts()` averages several readings to smooth sensor noise.
* `fit_line()` is ordinary least squares returning **`(intercept, slope, R²)`** —
  R² is returned deliberately so a bad fit is visible rather than silently trusted.

**The scripts:**

| Script | What it does |
|---|---|
| `cpu_sweep.py` | Prompts you to drive the CPU to 0/25/50/75/100 % load, samples 25 s per level, returns raw measurements + prints the per-run regression |
| `ram_sweep.py` | Automated: allocates 0/1/2/4 GB itself, samples power, fits, writes `ram_watts_per_gb_used` |
| `recalibrate_cpu.py` | The mature path: loads all past runs from `data/cpu_calibration_runs.csv`, runs 3 more sweeps, appends them, refits over **all** historical + new points, and updates **only** the CPU coefficient |
| `set_baseline.py` | Measures `baseline_watts` directly: sample CPU/power/RAM together, subtract the known CPU and RAM contributions, average over N runs. Doesn't require literal 0 % CPU — it corrects for whatever idle floor the machine really has. Refuses to write a non-positive result and warns if runs disagree |
| `set_coefficient.py` | Manually set one coefficient from literature (with a citation in `notes`) — used for RAM |
| `calibration_db.py` | Shared partial-update helper: writes only the given columns, always stamps `calibrated_at`, so one component can be recalibrated without redoing the others |
| `run_calibration.py` | Full CPU + RAM sweep in one go, averaging the two intercepts into a single `baseline_watts` |
| `test_lhm.py` | Spike: reading LibreHardwareMonitor sensors via pythonnet, an alternative ground-truth source |

`data/cpu_calibration_runs.csv` currently holds **45 raw measurements** across
several runs for the Dell Latitude 7480 — the accumulating dataset behind the
0.10532 W/% coefficient.

---

## 5. Data flow, end to end

```
psutil / WMI / ctypes
        │  raw dicts
        ▼
MetricsPollingService.poll()          ← holds previous counters, computes B/s
        │  SystemMetricsSnapshot
        ▼
PowerEstimator.estimate(snapshot, profile)   ← profile from hardware.db (once, at startup)
        │  PowerEstimate (cpu / ram / baseline / total)
        ├──────────────► every 120 s: save_telemetry_snapshot()
        │                             └► RecommendationEngine.evaluate()
        ▼
EnergyEstimator.estimate(power, ts)   ← integrates over real elapsed time
        │  EnergyEstimate (interval + cumulative Wh)
        ▼
CarbonEstimator.estimate(energy)      ← × 0.483 kgCO₂eq/kWh
        │  CarbonEstimate
        ▼
ecoinsight.db  ──►  FastAPI  ──►  usePolling (5 s)  ──►  StatsBar
```

---

## 6. Running the project

**Backend dependencies** (`requirements.txt` is UTF-16-encoded and incomplete —
see §7): `fastapi`, `uvicorn`, `pydantic`, `psutil`, `wmi`,
`screen-brightness-control`, and `pythonnet` only for `test_lhm.py`.

```bash
# from backend/
python -m GreenIT.services.estimation_loop      # the collection + estimation loop
uvicorn GreenIT.api.api:app --port 8000         # the read API
```

```bash
# from frontend/
npm install
npm run dev        # http://localhost:5173
```

First-time machine setup:

```bash
python -m GreenIT.scripts.setup_hardware_db          # create hardware.db + placeholder row
python -m GreenIT.scripts.calibration.recalibrate_cpu   # unplugged
python -m GreenIT.scripts.calibration.set_baseline      # unplugged
```

Sanity checks: `smoke_test_power_estimator.py` (prints one real estimate),
`check telemetry.py` (confirms telemetry rows are landing).

---

## 7. Current state and TODO

*Last updated: 2026-08-17.*

### Working end to end

Run `python -m GreenIT.agent` and open **http://127.0.0.1:8000**. That single
process runs collection on a background thread and serves both the API and the
built dashboard on one port — the Netdata model the product is built around.

* Collection, power/energy/carbon estimation and persistence run continuously;
  ~57,000 measurement rows and ~1,200 telemetry rows accumulated.
* Real calibration data for the Dell Latitude 7480, backed by 45 raw sweeps.
* All four API endpoints work, plus SQL-side downsampling on `/api/history`.
* The recommendation engine fires, persists, and surfaces in the UI.
* Dashboard has six panels: recommendations, top consumers, power draw,
  utilisation, disk I/O, network I/O — with a 1h/6h/24h/7d window picker.
* **Idle-waste detection**: flags a machine left awake with nobody at it,
  costed from real measurements. The only rule that needs no history, so it
  works from the first minute the agent runs.
* **Per-process attribution**: CPU power split between applications
  (processes grouped by executable name), sampled on the telemetry cadence.

### TODO

**Recommendation quality — do this before desktop notifications**

The statistical rule fires far too often to be pushed to the desktop. Measured
over 1,258 telemetry rows:

```
cpu p50 = 20.6%   p90 = 73.2%
mean = 32.1%, stdev = 24.8%  ->  1.5σ fires above 69.3%
share of samples that would fire: 11.3%
```

At a 2-minute cadence that is a notification roughly every 18 minutes - as
toasts, unusable. **Now 2.3/day** after the work below (CPU 0.6, RAM 1.6),
measured by replaying the same six days through the shipped rule.

- [x] **The Gaussian assumption is wrong.** ~~"mean + 1.5s" lands around the
      88th percentile.~~ Replaced with p90 of the machine's own recent
      history. p90 and not higher because the metric saturates - measured
      here, p95 = 97% and p98 = 100%, so past p90 the rule degenerates into
      "only fires when pinned".
- [x] **Nothing requires persistence.** ~~A single 2-minute spike fires.~~
      Now requires 5 consecutive samples (10 min), and runs are gap-aware:
      a break longer than 300s resets the count, so a suspend cannot glue two
      unrelated spikes into one "sustained" episode.

      Persistence turned out to be the only lever that matters. Replaying six
      days of real telemetry: swapping sigma for a percentile alone gave 16.2
      CPU notifications/day, barely better than the 16.8 it replaced - a
      rolling percentile fires on ~(100-N)% of samples by construction, on
      any machine. Adding persistence took it to 0.6/day.
- [x] **Added an impact gate.** "Unusual for you" is not "worth interrupting
      you": on a machine that idles at 5%, p90 might be 20%. The gate is in
      the tool's own unit - the excess over the machine's measured typical
      draw must project to >= 5 Wh over the notice window.

      It must veto *speaking*, not membership in the episode. The first
      version folded it into the elevated condition, and replay showed power
      hovering near the gate tore one episode into many, each re-announcing
      itself: RAM went **up**, 2.3/day to 5.7/day. Now it silences only, and
      a silenced first notice stays owed - if the draw later climbs past the
      gate the user gets the opening message, not a reminder about something
      never mentioned.
- [x] **The messages aren't actionable.** ~~"CPU usage is unusually high"
      says nothing to act on.~~ Done. `process_catalog.py` maps executable
      names to labels, plain-language descriptions and advice (87 entries,
      seeded from the names actually observed in `process_samples`), and
      `recommendation_messages.py` composes the sentence from them.

      A cause is named only when one process holds ≥40% of the resource AND
      is ≥1.5× the runner-up; otherwise the message describes the aggregate
      and blames nobody. Advice is gated on a `closeable` flag, so a system
      service or an unrecognised process is never something the tool tells
      you to close. Reminders drop the advice deliberately — repeating it
      every 90 minutes is nagging, and the point of a reminder is that the
      situation is continuing.

      The measured-cost clause is omitted entirely when the measurements
      table has no rows for the period (agent restarted mid-episode, or the
      machine was suspended and the energy estimator correctly dropped the
      interval). Printing "0.00 Wh" there would assert a measurement that was
      never taken.
- [x] **State is in memory only,** ~~so restarting the agent re-fires
      everything it had already reported.~~ The engine now reloads the latest
      recommendation per metric at startup and resumes from it. No new table:
      the row it already writes *is* the record of "I told the user at time
      T". Only rows newer than one reminder interval are restored - anything
      older is not evidence of an ongoing episode. Restore failures are
      swallowed, because losing it costs one duplicate notification while
      crashing costs all collection.
- [ ] Once the above land, desktop notifications (feature 2) become worth
      shipping. Not before — pushing the current signal to the OS would
      train the user to dismiss it. Note when it lands: the longest composed
      message is 334 characters, and a Windows toast body truncates around
      200. The advice sentence is the droppable part, so a toast should carry
      the situation and the cost, with the advice left for the dashboard.

**On generating the messages with an LLM** — evaluated and deliberately not
done at alert time. Two of the requirements are guarantees rather than
preferences: the energy figure must be the measured one, and no cause may be
named unless one genuinely dominates. A template enforces both by
construction; a generative model can only be asked. Add to that a 2–5 GB
resident model inside a tool whose whole purpose is reporting unnecessary
resource use, plus an Ollama install on every deployment target. The place it
would earn its cost is a daily or weekly digest — one inference, latency
irrelevant, real synthesis to do, and no live alert can be corrupted by a bad
generation.

**Waste over anomalies** (done)

Measured on this machine's own data: 27% of the energy since idle tracking
began went to a machine nobody was using (14.3 Wh, 96 min). Chrome's entire
day cost 1.27 Wh. That ratio is the argument - "CPU is unusually high" is a
computer doing its job, and no phrasing rescues an event with no action
attached.

- [x] **The elevated rule stays silent when nothing dominates.** The aggregate
      variant ("spread across several applications with no single one
      responsible") was a statistic wearing a recommendation's clothes. Only
      ~20% of samples have a dominant process, so CPU notices are now rare by
      design - if the tool cannot say what is responsible, it has nothing
      worth saying.
- [x] **Unattended activity.** Idle AND busy is a different situation from
      either alone: a job running with nobody there. Same detection, forked
      wording, opposite advice - a sleep timer would kill the job, so the
      message asks whether it is meant to be running instead.
- [x] **Scale framing.** "14 Wh" is unreadable; "27% of everything your
      machine has used today" needs no units and no prior knowledge. Attached
      to measured figures only - pairing a projection with the day's actual
      total would put two different kinds of number in one sentence.
- [x] **Removed the sigma badge from the feed.** The trigger is a p90
      percentile plus a persistence run plus an energy gate; sigma is part of
      none of them. A number that looks precise and means nothing is worse
      than no number.

Still open, and where this gets genuinely smart: the history produces exactly
one number today (p90). It could produce "third time today", "every weekday
around 14:00", "Chrome cost you 3.75 Wh, second to VS Code". That is the core
of the weekly digest.

**Employee-facing features** (shipped 19 Aug)

- [x] **Wake-timer audit.** `Get-ScheduledTask` names the tasks allowed to
      wake the machine, without elevation - `powercfg /waketimers` needs admin
      and returns nothing for a normal user. This completes the best finding
      the agent makes: the sleep contradiction went from "something is
      blocking sleep, ask IT" to naming `WakeUpAndScanForUpdates` and
      `WakeUpAndContinueUpdates`. Ranked so informative names survive the
      three-item cut; Windows returns them alphabetically, which led with
      ".NET Framework NGEN" and cut the one name a human could act on.
      ~3s to run, so it has its own 30-minute cache, separate from the
      60-second one on power settings.

- [x] **Carbon and energy equivalences.** 482 Wh becomes "4 kettles of water
      boiled, 28 phone charges, 2 kilometres driven". Energy comparisons and
      the carbon one are marked separately - the second carries a second
      emission factor and should not borrow the first's authority. Dropped
      entirely when the count would fall outside roughly 0.5-500, since
      "0.02 kettles" informs nobody.

- [x] **Off-hours and weekend waste.** Measured on this machine: **136 Wh of
      482 (28%) drawn outside 08:00-19:00, 67 Wh of it at weekends**, with
      16-18 Wh in each of the 00:00-02:00 hours. Needed no new collection -
      the timestamps were always there. Rendered as a 24-bar hour-of-day
      profile with off-hours bars in the alert colour, because the number
      alone is a statistic and the shape is an argument.

**Uncalibrated machines** (shipped 19 Aug)

- [x] **The agent no longer dies on an unmeasured model.** `hardware.db`
      holds one profile, so on any other machine `UnknownMachineModelError`
      escaped `EstimationLoop.__init__`, killed the collection thread, and
      left a normal-looking dashboard that would never fill in. Since the
      fleet is calibrated model by model, every machine is uncalibrated for a
      while - a newly issued laptop has to produce labelled estimates in the
      meantime, not silence.

      The fallback lives in `HardwareService`, not the repository. The
      repository answers "is there a measured profile for this key", and
      raising is the right answer to that question; what to DO about the
      absence is policy, and policy belongs to the layer that resolves
      profiles for the running application.

      The CPU coefficient is **not** a literature value, because
      watts-per-CPU-percent is not a property of the processor - it depends
      on the platform's power management, its cooling, and what Windows calls
      "100%". Any published figure is somebody else's regression on somebody
      else's laptop. What transfers is a ratio: the anchor machine
      (i5-6300U, 15 W) fits 0.1053 W/%, so 10.5 W at full load, **70% of
      TDP**. TDP is published for every part, so the fallback is
      `0.70 x TDP / 100`, inferred from the processor suffix (U 15 W, P 28 W,
      H 45 W, HX 55 W), defaulting to 15 W since most corporate fleets are
      U-series. Baseline (5 W) and the RAM term genuinely are literature
      figures - there is no better source for either.

      The ratio rests on ONE anchor point and could be 0.6 or 0.85 elsewhere,
      so profiles built this way carry `source="estimated"` and raise a
      dashboard finding. It also self-improves: a second calibrated model
      lets the ratio be checked instead of assumed, and a third lets it be
      fitted - at which point the fallback stops being a stopgap and becomes
      the first data point of the fleet model.

- [ ] **Validate the 70% ratio on a second machine model.** The single
      largest open question in the fallback, and it needs only one more
      calibration sweep to answer.

**Deployment**

- [x] **Run the agent at boot.** Done -
      `python -m GreenIT.scripts.install_autostart install|status|uninstall`.
      Registers a per-user log-on task via XML rather than
      `schtasks /SC ONLOGON`, because the command-line form cannot set a
      working directory (needed for `-m GreenIT.agent`) or touch the power
      settings - and **Task Scheduler's defaults would have broken this
      tool**: new tasks get `DisallowStartIfOnBatteries` and
      `StopIfGoingOnBatteries` set true, so on a laptop the agent would
      refuse to start on battery and be killed when the charger came out,
      switching itself off exactly when a power monitor is most interesting.
      Also `ExecutionTimeLimit=PT0S` (the default kills it after 3 days),
      `MultipleInstancesPolicy=IgnoreNew` (two collectors would double every
      energy figure while still looking plausible), 30s log-on delay, and
      below-normal priority.

      Two bugs found by actually running it rather than trusting the exit
      code, which reported success both times:

      * **The agent died silently under `pythonw`.** No console means
        `sys.stdout` is None, so the first `print()` raised inside the daemon
        collection thread - whose handler reports crashes by printing, and
        raised again. `agent.py` now redirects to `GreenIT/data/agent.log`
        when there is no console, with a last-resort handler for failures
        before the redirect is installed.
      * **`status` printed an empty, reassuring report.** `schtasks /Query /V
        /FO LIST` returns LOCALISED field names, and this is a French Windows
        install - matching "Task To Run" found nothing. It now parses the
        task XML, which is not translated.
- [x] **`requirements.txt` rewritten.** It was UTF-16 **without a BOM**
      (which is why a first repair attempt silently failed: the BOM check
      missed it, the UTF-8 decode "succeeded" on interleaved null bytes, and
      the same garbage was written back). Now UTF-8, six direct dependencies
      derived from what the code actually imports, with pythonnet marked
      calibration-only. Verified with `pip install --dry-run -r`.

**Correctness**

- [ ] `run_calibration.py` unpacks `cpu_intercept, cpu_slope = run_cpu_sweep()`,
      but that function returns a list of measurement dicts. The script
      crashes; `recalibrate_cpu.py` is the working path.
- [ ] `recommendations_test.py` calls `engine.evaluate(snapshot)` with one
      argument; the signature now needs `power_watts` too.
- [ ] Import paths are split: `recalibrate_cpu.py` uses `from GreenIT...`
      while `run_calibration.py`, `ram_sweep.py`, `cpu_sweep.py`,
      `set_baseline.py` and `set_coefficient.py` use bare `from collectors...`.
      Only one of the two works from a given working directory.

**Science**

- [x] **Validate the model on held-out data.** Done -
      `python -m GreenIT.scripts.calibration.validate_model`.

      ```
      IN-SAMPLE   linear 4.69 + 0.1053*cpu%      MAE 0.89 W  MAPE  8.0%  R2  0.869
      HELD OUT    leave-one-sweep-out            MAE 0.95 W  MAPE  8.5%  R2  0.852
                  leave-one-session-out          MAE 0.95 W  MAPE  8.7%  R2  0.861
                  null model (predict the mean)  MAE 2.92 W  MAPE 28.8%  R2 -0.014
      SHIPPED     1.92 + 0.375*11GB + 0.1053*cpu MAE 1.40 W  MAPE 15.3%  bias +1.35 W
      ```

      **The model generalises.** Held-out error is barely worse than
      in-sample (0.95 vs 0.89 W), so it is not overfitted, and it beats the
      null model threefold - which is the comparison R-squared makes silently
      and nobody had checked. Leave-one-session-out matches
      leave-one-sweep-out, so the relationship is stable across days.

      Splits are grouped, not random: rows inside a sweep share a battery
      charge state and a thermal state, so a random split scores
      interpolation between near-duplicates and reports an optimistic number.
      Also note `run_id` restarts at 1 each session (runs 1-3 exist on both
      7 and 8 August), so the grouping key has to be (date, run_id) - keying
      on run_id alone leaks across the split.

- [x] **Settle the RAM coefficient by measurement.** Done, unplugged, 19 Aug
      - `python -m GreenIT.scripts.calibration.ram_sweep`. 360 samples, six
      allocation levels visited in randomised order across six rounds.

      ```
      watts = 5.67 + 0.1345 x cpu%  - 0.0899 x ram_gb        (n=360)
        ram coefficient   -0.090 +/- 0.215 W per GB
        95% interval      [-0.305, +0.126] W/GB
      adding ram to a cpu-only model: R2 0.563 -> 0.564, F = 0.67 (needs 3.9)
      ram alone explains R2 = 0.001
      ```

      **`0.375 W/GB of memory USED` is rejected for this machine.** It sits
      outside the interval; zero sits inside it. Over the 2.59 GB actually
      spanned, the shipped term predicts +0.97 W and the measurement says
      -0.23 W [-0.79, +0.33].

      The manipulation is verified, so this is a real null and not a failed
      experiment: allocating moved `ram_used` 10.88 -> 13.48 GB monotonically
      across levels, sd 0.16-0.28.

      This does not make CodeCarbon wrong. Their 3 W / 8 GB models DIMM
      refresh power, which exists whether or not the OS has handed the pages
      out - so it is a property of *installed* capacity and behaves as a
      constant. A constant is exactly what this experiment sees, absorbed
      into the intercept. The error was applying an installed-capacity figure
      per *byte resident*. Whether 0.375 W/GB is right for 16 GB *installed*
      was not tested here.

- [ ] **Reconcile the two CPU estimates before changing any coefficient.**
      This sweep puts the CPU term at **0.1345 +/- 0.0123 W/%**, CI
      [0.122, 0.147], which EXCLUDES the calibrated 0.1053. Two experiments
      on the same laptop, twelve days apart, disagree by about 28%.
      Collinearity with RAM was only +0.09, so the estimates are cleanly
      separated and this is not an artefact of the fit. Candidate causes:
      synthetic stress load versus real mixed workload, different CPU-percent
      sampling windows, or thermal/turbo state. Worth one deliberate
      experiment - a CPU sweep under both load types in one session - because
      until it is resolved there is no defensible value to ship.

- [ ] **Then fold the RAM term into the constant.** Justified now by
      measurement rather than by the earlier circular argument. Blocked on
      the CPU reconciliation above, since both coefficients want changing in
      one deliberate step, with a decision about whether to migrate the
      stored history or accept a discontinuity.

- [ ] **The component breakdown isn't physical.** DRAM power scales with
      *installed* capacity, not bytes used, so `ram_watts_per_gb_used` is
      probably the wrong shape regardless of its value - see the RAM
      coefficient item above. The total is defensible; the split the UI
      advertises is not, and the calibration data cannot arbitrate it because
      memory never varied during those runs.
- [x] **Display state is now recorded and shown.** `brightness_percent` and
      `monitor_count` flow through the snapshot into `telemetry_history`, and
      appear on the dashboard as a stat tile plus a dashed line on the
      utilisation chart - dashed because it is a *setting the user chose*,
      not load the machine is under, even though it shares the 0-100% axis.

      Sampled every 120s, not every poll: the read costs ~170 ms because it
      talks to each monitor over DDC/CI, which is 11% of a 1.5s cycle. A
      green-IT tool burning that much CPU to watch a value that only moves
      when someone drags a slider would be indefensible. Failed reads retry
      after 15s rather than being cached for the full two minutes - the first
      restart after shipping this showed a single DDC hiccup punching a
      2-minute hole in the line.

- [ ] **Brightness still does not feed the POWER MODEL.** It is recorded and
      charted, but the panel - one of the largest consumers on a laptop - is
      still absorbed into the constant term rather than estimated from
      brightness. That is the next real modelling improvement, and unlike the
      RAM question there is a clear mechanism and a way to measure it
      (sweep brightness at fixed CPU on battery, the same design as
      ram_sweep.py).
- [ ] Calibrate a second machine model — the premise is a fleet of
      standardised PCs, and n=1 doesn't test that.

**Cleanup**

- [ ] `config.py` is legacy and unimported: `DEFAULT_CARBON_INTENSITY = 600`
      contradicts the 483 actually used in `carbon.py`, `CPU_TDP_WATTS` names
      a CPU that isn't the calibrated machine, and its thresholds were
      superseded by the statistical baseline.
- [ ] `main.py` and `test_main.http` are still the FastAPI hello-world.
- [ ] `services/machine_lookup.py` is empty; `backend/temp.py` is a scratch
      file; `scripts/check telemetry.py` has a space in its filename, which
      blocks `python -m`.
- [ ] No real test suite — `recommendations_test.py` and
      `smoke_test_power_estimator.py` are explicitly throwaway scripts.

### Recently fixed

* **Sleep-gap energy inflation.** The estimator integrated power across
  suspend, so resuming from a 38 h sleep logged 641 Wh in one tick.
  `EnergyEstimator.MAX_INTERVAL_SECONDS` (60 s, chosen from the observed
  bimodal tick distribution — p99.9 is 5.5 s, the next tier is 4.6 h) now
  drops such intervals. `migrate_recompute_cumulative.py` repaired history:
  **1,273.8 Wh of phantom energy removed, 77.2 % of the recorded total**;
  the real figure is 376 Wh.
* **`/api/history` aggregates in SQL** via `buckets`, each column by what it
  means — AVG for rates, SUM for per-interval amounts, MAX for cumulative
  totals. 7 days went from 18.7 MB to 63 KB.
* **Recommendations are persisted.** `save_recommendation()` had no caller.
* **`import before`** removed from `recommendations.py` — it made the module
  unimportable, so the loop couldn't start.
* **`run_forever`** no longer raises `NameError` on its warm-up tick, and
  honours `interval` as a floor rather than ignoring it.
* **WMI on a background thread** needs `pythoncom.CoInitialize()` — surfaced
  the moment the agent moved collection off the main thread.
* Frontend: StatsBar labelled kilograms as grams; `usePolling` had two type
  errors; `App.tsx` was still the Vite starter template.
* **Chart gaps are shaded** rather than left as bare breaks, so a stretch
  where the agent wasn't collecting reads as missing data instead of a
  rendering fault. Not drawn as a drop to zero — that would claim the machine
  consumed nothing, which is as false as interpolating across it.
* **Schema upgrades run automatically** at startup (`_apply_schema_upgrades`),
  since `CREATE TABLE IF NOT EXISTS` never adds columns to a table that
  already exists — a real problem for an agent meant to run unattended on
  many machines.
* **"System Idle Process" is excluded** from process attribution. It is
  Windows' accounting fiction for CPU doing *nothing*, and it topped the list
  at 100.8%; left in the denominator it also deflated every real process's
  share.

## 8. Design decisions worth remembering

| Decision | Rationale |
|---|---|
| Per-machine calibration instead of TDP-based estimation | Datasheet TDP is a thermal ceiling, not real draw; regression against battery discharge captures the actual machine |
| Battery fuel gauge as ground truth | No admin rights, no external hardware, works on any laptop — at the cost of requiring the machine unplugged |
| Hard failure on unknown machine model | Silent fallback coefficients would produce plausible-looking but wrong numbers, which is worse than an error |
| Statistical baseline instead of fixed thresholds for recommendations | "80 % CPU" is normal for a developer and alarming for an office user; the baseline is the user's own history |
| Two separate SQLite files | `hardware.db` is versioned, shipped and read-only; `ecoinsight.db` is per-installation, mutable and growing |
| Two-tier cadence (1.5 s power, 120 s telemetry) | The dashboard needs to feel live; the anomaly baseline needs days of data, not high resolution |
| Country-specific carbon intensity | A world-average factor would misstate Tunisia's >98 % gas-fired grid in either direction |
| Estimators take injected component models / intensity factors | Each can be swapped or unit-tested independently, with no database or collector involvement |
