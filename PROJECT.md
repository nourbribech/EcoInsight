# EcoInsight — Project Documentation

> Software-based power, energy and carbon estimation for Windows workstations,
> with a live dashboard and a personalised recommendation engine.
>
> **This is the maintainer's document** — architecture, methodology, decisions
> and open work. See [README.md](README.md) to install and run it,
> [DEMO-setup.md](DEMO-setup.md) for the IT demo, and
> [RAPPORT-source.md](RAPPORT-source.md) for the measured figures gathered for
> the internship report.

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
│   └── GreenIT/
│       ├── agent.py               # THE entry point: loop on a thread + API on one port
│       ├── collectors/            # layer 1 — raw OS readings
│       │   ├── hardware/              # psutil: cpu, cpu_info, memory, disk,
│       │   │                          #   network, processes
│       │   └── windows/               # WMI/ctypes: display, power, power_settings,
│       │                              #   session, system_identity, battery_health,
│       │                              #   scheduled_tasks, wsl
│       ├── models/                # layer 2 — typed contracts (frozen dataclasses)
│       │   ├── runtime/               # cpu/memory/disk/network runtime metrics
│       │   ├── snapshot.py, calibration.py, recommendation.py
│       │   └── power_estimate.py / energy_estimate.py / carbon_estimate.py
│       ├── services/              # layer 3 — orchestration + stateful sampling
│       │   ├── metrics_polling_service.py, hardware_service.py
│       │   └── estimation_loop.py     # the main runtime loop
│       ├── estimators/            # layer 4 — pure calculation
│       │   ├── power.py / energy.py / carbon.py
│       │   ├── recommendations.py, recommendation_messages.py, process_catalog.py
│       │   ├── process_attribution.py, generic_calibration.py
│       │   ├── goals.py, rating.py, equivalences.py
│       │   ├── lifecycle.py           # embodied vs operating carbon
│       │   ├── config_audit.py        # sleep settings, wake timers
│       │   ├── workloads.py           # WSL / Docker left running
│       │   └── actions.py             # every standing finding, ranked
│       ├── database/              # layer 5 — SQLite persistence
│       │   ├── database.py            # ecoinsight.db (history)
│       │   ├── settings_store.py      # user preferences, JSON key/value
│       │   ├── hardware_repository.py # hardware.db — READ ONLY, by design
│       │   ├── calibration_writer.py  # hardware.db — the only writer
│       │   └── data/hardware.db
│       ├── data/ecoinsight.db     # measurement + telemetry + recommendation history
│       ├── api/api.py             # FastAPI: REST layer + serves the built dashboard
│       └── scripts/
│           ├── install_autostart.py   # per-user log-on task
│           ├── setup_hardware_db.py, migrate_*.py
│           └── calibration/           # the measurement campaign toolkit
│               ├── auto_calibration.py    # THE runnable sweep — generates its own load
│               ├── _load.py               # CPU load worker (spawn-safe, no heavy imports)
│               ├── battery_power.py       # discharge-rate ground truth + fit_line
│               ├── validate_model.py      # cross-validated R² against a null model
│               ├── ram_sweep.py, recalibrate_cpu.py, set_baseline.py
│               └── run_calibration.py     # SUPERSEDED — supervised, unqualified imports
└── frontend/                      # React 19 + TypeScript + Vite dashboard
    └── src/
        ├── App.tsx                # views, topbar, session mode, IT setup routing
        ├── components/
        │   ├── StatsBar, PowerChart, UtilizationChart, IoChart      # live
        │   ├── SummaryPanel, GoalPanel, ActionsPanel, PatternsPanel # digest
        │   ├── RecommendationsFeed, ProcessTable, WorkloadsPanel
        │   ├── LifecyclePanel                                        # years
        │   ├── CalibrationPanel, ITSetupWizard                       # IT setup
        │   └── Disclosure.tsx                                        # shared
        ├── hooks/usePolling.tsx, hooks/useLiveSeries.ts
        ├── lib/series.ts          # bucketing — what the CHARTS need
        └── types/api.ts           # faithful mirror of the API contract
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

**`GreenIT/database/data/hardware.db`** — the fleet's calibration, shipped
pre-populated and **tracked in git**: it is 20 KB, it changes only when somebody
runs a sweep, and losing it means recalibrating from scratch.

```sql
calibration_profiles(
  machine_model TEXT PRIMARY KEY,
  cpu_watts_per_percent_usage REAL, ram_watts_per_gb_used REAL,
  baseline_watts REAL, calibrated_at TEXT, notes TEXT,
  source TEXT)                          -- 'measured' | 'entered'
```

Read through `HardwareRepository`, which stays read-only by design, and written
**only** through `CalibrationWriter` (§4.2). The `source` column was added
alongside the screen that can write anything else; existing rows backfill to
`measured`, because every row predating it came from a sweep.

A missing machine model still raises `UnknownMachineModelError` at the
repository, which is the right answer to "is there a measured profile for this
key". What to DO about the absence is policy, and policy lives in
`HardwareService`: it falls back to a profile scaled from the CPU class, marked
`source="estimated"`, and raises a dashboard finding. Since the fleet is
calibrated model by model, every machine is uncalibrated for a while — a newly
issued laptop has to produce labelled estimates in the meantime, not silence.

**`GreenIT/data/ecoinsight.db`** — the local history, created and migrated on
startup by `initialize_database()`. Gitignored: it is rewritten every 1.5 s and
reached 33 MB in twenty days. A snapshot taken with `VACUUM INTO` is committed
once, deliberately, when a machine is retired.

| Table | Written by | Cadence | Rows (30 Aug) |
|---|---|---|---|
| `measurements` | estimation loop | every tick (~1.5 s) | 279 389 |
| `telemetry_history` | estimation loop | every 120 s | 4 139 |
| `process_samples` | estimation loop | every 120 s | 28 810 |
| `workload_samples` | estimation loop | every 120 s | 1 770 |
| `recommendations` | recommendation engine | on trigger | 99 |
| `profile_changes` | on calibration write | on change | 1 |
| `settings` | API, on user action | on change | 4 |
| `cpu_specs` | online-lookup cache | on demand | 0 (unused so far) |

`profile_changes` exists so the digest can **withhold** a period-over-period
comparison when the coefficients moved inside the window. Comparing energy
across a calibration change would report a change in the model as a change in
behaviour.

### 3.5 API (`GreenIT/api/api.py`)

FastAPI, CORS-allowed for the Vite dev server at `http://localhost:5173`. In
production it also **serves the built dashboard** from `frontend/dist`, so the
agent is one process on one port.

**Reading measurements**

| Endpoint | Params | Returns |
|---|---|---|
| `GET /api/current` | – | latest `measurements` row, or `{}` |
| `GET /api/history` | `hours`, `buckets` | measurements, downsampled in SQL |
| `GET /api/telemetry` | `hours` | telemetry rows since cutoff |
| `GET /api/processes` | – | per-application CPU/watts, newest sample |
| `GET /api/recommendations` | `hours`, `limit` | recommendations, newest first |

**Analysis**

| Endpoint | Returns |
|---|---|
| `GET /api/summary` | the digest: energy, carbon, per-day, idle share, off-hours, waste rating, equivalences |
| `GET /api/insights` | standing configuration findings (sleep, wake timers) |
| `GET /api/workloads` | WSL/Docker left running, with observed hours |
| `GET /api/actions` | every standing finding from all rules, ranked |
| `GET /api/lifecycle` | manufacturing carbon against operating carbon, battery health |
| `GET`/`PUT /api/goal` | the weekly waste target and progress against it |

**Session and IT setup**

| Endpoint | Purpose |
|---|---|
| `GET /api/session` | mode, `it_mode_source`, profile provenance, writability |
| `POST /api/session/acknowledge` | records that the user saw how figures are derived |
| `POST /api/session/unlock-it` | enter IT mode — refuses without write permission |
| `POST /api/session/lock-it` | leave IT mode — 409 if the mode came from `--mode it` |
| `POST /api/it/wizard-complete` | the walkthrough is shown once per database |
| `GET`/`POST /api/calibration` | list / write a profile |
| `DELETE /api/calibration/{model}` | remove a profile, after backing the file up |
| `GET /api/calibration/export`, `POST .../import` | move profiles between machines |
| `POST /api/calibration/run` | run the sweep in a child process (`quick=true`) |

The measurement endpoints are read-only; the calibration ones are the single
mutating surface, and every one of them is gated on the operating system
allowing the write.

**Caching.** Expensive collectors are memoised with separate TTLs, because they
go stale at very different rates — power policy changes the moment somebody
edits a setting (60 s), wake timers only when software is installed (30 min).
Static assets carry an explicit policy: `no-cache` on `index.html`, which names
which bundle to load, and `immutable` on the content-hashed assets, whose bytes
can never change.

### 3.6 Frontend

React 19 + TypeScript ~6 + Vite 8, with the React Compiler babel preset enabled.

**The page is split by QUESTION, not by data source.** Before that it was twelve
sections in one column, every one wrapped in an identical panel, so nothing
signalled where to look. That flatness — not the amount of data — is what made
it overwhelming. The split also separates two timescales that were interleaved:
"how am I doing this week" changes weekly, "what is happening now" changes every
1.5 seconds.

| View | Question | Timescale |
|---|---|---|
| **Today** | How do I compare this week? | week |
| **Live** | What is happening right now? | seconds |
| **Machine** | Should this machine be replaced? | years |
| **IT setup** | Is this model calibrated? | fleet |
| **Guide** | What do these numbers mean? | — |

* **`hooks/usePolling.tsx`** — fetch a URL on an interval, expose
  `{data, error, loading}`, fire immediately, cancel cleanly on unmount.
* **`hooks/useLiveSeries.ts`** — seed from `/api/history` once, then append from
  `/api/current`, so a live chart costs one row per poll instead of the whole
  window. Used only where that pattern earns its complexity.
* **`lib/series.ts`** — bucketing for the charts. Deliberately separate from
  `types/api.ts`, which stays a faithful description of the server contract and
  nothing else.
* **Gaps are never filled.** A break in a chart means no measurement was
  recorded. It is shaded rather than interpolated, and never drawn as a drop to
  zero — that would claim the machine consumed nothing.

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
| **`auto_calibration.py`** | **The runnable path.** Generates the CPU load itself, samples usage and discharge together, fits, scores the fit by cross-validation, and writes through `CalibrationWriter`. `--quick` (~75 s) or full (3 randomised rounds). This is what the IT screen's button runs |
| `_load.py` | The load worker. Its own module importing nothing but `time`: multiprocessing `spawn` re-imports the target's module in every child, and pointing that at the calibration module would import psutil and the COM stack *while CPU is being measured* |
| `validate_model.py` | Scores the shipped coefficients against held-out data and against a null model |
| `cpu_sweep.py` | Prompts you to drive the CPU by hand to 0/25/50/75/100 %, 25 s per level |
| `ram_sweep.py` | Automated: allocates in half-GB blocks, randomised order across rounds, regresses CPU out. Writes nothing — prints a number and a confidence interval |
| `recalibrate_cpu.py` | Loads all past runs from `data/cpu_calibration_runs.csv`, runs 3 more sweeps, refits over **all** points, updates **only** the CPU coefficient |
| `set_baseline.py` | Measures `baseline_watts` at rest, subtracting the known CPU and RAM contributions. Doesn't require literal 0 % CPU — it corrects for whatever idle floor the machine really has |
| `set_coefficient.py` | Manually set one coefficient from literature, with a citation in `notes` |
| `calibration_db.py` | Partial-update helper: writes only the given columns, always stamps `calibrated_at` |
| `run_calibration.py` | **Superseded.** Its imports are unqualified so it raises on import, and `cpu_sweep` calls `input()` at every level — a supervised procedure no button can start |
| `test_lhm.py` | Spike: LibreHardwareMonitor via pythonnet. Dead end — the exposed sensors do not give total system draw on this model |

`data/cpu_calibration_runs.csv` holds **45 raw measurements** across nine sweeps
and three sessions for the Dell Latitude 7480 — the dataset behind the
0.10532 W/% coefficient.

### 4.1 What the automated sweep guarantees

Four things that are refusals rather than features, and matter more than the
measurement itself:

* **It only adds load, so it checks it has room to work.** On a machine already
  at 85 % with a browser and an IDE open, every level measures near the top and
  a line fitted through a 15-point spread is arithmetic, not calibration. Idle
  CPU is checked before starting (3 s, fails fast) and the measured spread again
  afterwards, because a machine that started quiet can get busy mid-run.
* **Levels are visited in randomised order.** Battery voltage sags, a scan
  finishes, the machine warms up. Anything changing monotonically with time
  would otherwise land on whichever level is sampled late and masquerade as a
  CPU effect.
* **The fit is scored against a null model, not against itself.** Below the
  threshold the profile is not written and the estimated one is kept — a weak
  "measured" profile inherits the authority of a sweep without having earned it.
* **The RAM coefficient is carried through as a reference value and labelled
  one.** This machine's RAM sweep could not separate a memory effect from sensor
  noise, and writing a measured-looking number nobody measured is the single
  thing the design exists to prevent.

### 4.2 Writing a profile (`database/calibration_writer.py`)

Writing is a **different capability with a different caller**, so it is not a
method on `HardwareRepository`. That class documents itself as read-only access
and the guarantee is worth keeping: every estimator, the API and the estimation
loop hold a repository, and none of them should be one typo away from rewriting
the coefficients the whole fleet's numbers depend on.

**Permission is the real gate, and `--mode it` is not.** Gating on the flag
would be security theatre — any employee can pass it. If a flag were enough,
anybody could drop their baseline from 5 W to 1 W and watch a third of their
reported waste disappear, in a tool whose entire output is a waste figure. So
the write is attempted and the operating system decides. On a managed fleet
`hardware.db` is admin-writable only, which makes the boundary enforced by
Windows rather than decorated by a UI.

**Validation is physics, not taste.** A fat-fingered `0.105 → 1.05` produces
numbers that look plausible and are wrong forever, with nothing downstream able
to notice. The bounds come from what a laptop can actually do:
CPU 0.02–0.60 W/%, RAM 0–1 W/GB, baseline 0.5–20 W.

**Provenance is recorded and never upgraded.** `measured` means a sweep ran;
`entered` means somebody typed it; `estimated` describes a runtime fallback and
the writer refuses to store it at all. The typed-entry form always saves as
`entered` — only the sweep itself, and importing a file already classified
elsewhere, produce `measured`. Import preserves it because calibration belongs
to a *model*: a sweep run on one laptop is genuinely measured for every
identical unit, and downgrading it in transit would destroy true information.

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

**Backend dependencies** (`requirements.txt`, UTF-8, six direct entries):
`fastapi`, `uvicorn`, `pydantic`, `psutil`, `wmi`,
`screen-brightness-control`; `pythonnet` is calibration-only.

**One command runs the product.** The agent starts collection on a background
thread and serves the API plus the built dashboard from the same process — the
Netdata model.

```powershell
# from backend/
.\.venv\Scripts\python.exe -m GreenIT.agent
# → http://127.0.0.1:8000
```

Useful flags: `--port`, `--database ./demo.db` (isolated history),
`--machine-key "..."` (look the machine up under another name),
`--mode it` (start in the IT view).

**At log-on**, via a per-user task registered by
`python -m GreenIT.scripts.install_autostart install|status|uninstall`. It runs
`pythonw.exe`, so there is no console and the agent logs to
`GreenIT/data/agent.log`. Control it with
`Start-ScheduledTask -TaskName "EcoInsight Agent"`.

### 6.1 The two-step rebuild

The agent serves `frontend/dist`, **not** the sources. A change is invisible in
the browser until both halves are done, and doing one but not the other produces
a symptom that looks exactly like a bug in the feature itself.

| Changed | Required |
|---|---|
| Frontend | `npm run build` |
| Backend | restart the agent |

For frontend work, skip both: `npm run dev` serves `:5173` with hot reload and
proxies `/api` to the agent on `:8000`. The build only matters for what `:8000`
serves — the demo.

When something "isn't showing up", check in this order before reading any code:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/session   # is the agent even alive?
```

No answer means the browser tab is displaying a dead server's last render, which
looks identical to a frozen UI.

### 6.2 Calibrating a machine

From the dashboard: **IT setup → Unlock IT Mode →** the walkthrough's sweep
button. From a terminal, unplugged and with applications closed:

```powershell
.\.venv\Scripts\python.exe -m GreenIT.scripts.calibration.auto_calibration --quick --no-write
.\.venv\Scripts\python.exe -m GreenIT.scripts.calibration.auto_calibration
.\.venv\Scripts\python.exe -m GreenIT.scripts.calibration.validate_model
```

Sanity checks: `smoke_test_power_estimator.py` (prints one real estimate),
`check telemetry.py` (confirms telemetry rows are landing).

---

## 7. Current state and TODO

*Last updated: 2026-08-30.*

### Working end to end

Run `python -m GreenIT.agent` and open **http://127.0.0.1:8000**. That single
process runs collection on a background thread and serves both the API and the
built dashboard on one port — the Netdata model the product is built around.

* Collection, power/energy/carbon estimation and persistence run continuously;
  **279,000 measurement rows over 20 days** at the time of writing.
* Real calibration data for the Dell Latitude 7480, backed by 45 raw sweeps and
  validated against held-out data.
* Twenty-three API endpoints, with SQL-side downsampling and per-collector TTLs.
* The recommendation engine fires, persists, survives restarts, and surfaces in
  the UI.
* **Dashboard split by question** — Today / Live / Machine / IT setup / Guide —
  rather than twelve identical panels in one column.
* **Idle-waste detection**: flags a machine left awake with nobody at it,
  costed from real measurements. The only rule that needs no history, so it
  works from the first minute the agent runs.
* **Per-process attribution**: CPU power split between applications
  (processes grouped by executable name), sampled on the telemetry cadence.
* **Weekly waste goal** the user sets themselves, with a verdict on the finished
  week — a target you choose reads as feedback where the same number handed to
  you reads as a verdict.
* **Lifecycle panel**: manufacturing carbon against measured operating carbon,
  plus battery health.
* **Standing findings ranked into one list** across every rule, rather than
  three unranked lists leaving the reader to prioritise.

### Shipped 24–30 Aug — IT setup, and calibration from a button

The claim was always "IT calibrates a model and every identical machine picks it
up". Until this landed, doing so meant editing `hardware.db` by hand — which put
calibrating a fleet out of reach of the people who own the fleet.

- [x] **A profile can be written from the UI.** `CalibrationWriter` with
      physical bounds, a file copy before every destructive change, and
      provenance that is recorded and never upgraded. See §4.2.
- [x] **IT mode is an in-app switch, and a reversible one.** `--mode it` still
      works for headless runs, but the mode is now a preference this session can
      set and clear. The session reports *how* it got there: a flag-started
      session refuses to leave rather than appearing to succeed, since the flag
      is re-read on every request and would win again.

      The exit exists in three places, which is deliberate. It started in the
      setup panel only — and the panel renders *instead* of the walkthrough, so
      on a machine that had never completed setup the exit was unreachable and
      IT mode was a one-way door. The topbar badge is now the primary route: the
      element that NAMES the mode is the one that leaves it, and it is the only
      exit visible from the views where somebody would notice they are in the
      wrong mode.
- [x] **The sweep runs from a button.** `auto_calibration.py` generates its own
      load, so no operator is needed at the keyboard. It runs in a child process:
      it saturates every core for minutes, and running it inline would starve
      the event loop and the collection thread — the dashboard would stop
      answering during the exact window somebody is watching it.
- [x] **Static assets carry a cache policy.** Starlette sends an ETag but no
      `Cache-Control`, so a browser could serve `index.html` from cache without
      revalidating. That file names which bundle to load; a cached copy points
      at a bundle the next build deleted, and the page keeps rendering the old
      application while every file on disk is correct. Cost most of a day to
      diagnose.
- [x] **`DEMO-setup.md`** — the demo runbook, with the prerequisites, what the
      system refuses to do and why, and a troubleshooting table.

### Resolved from the correctness list

- [x] `run_calibration.py` is superseded rather than repaired. Fixing its
      unpacking bug would not have made it runnable: the imports are unqualified
      so it raises on import, and `cpu_sweep` blocks on `input()`. Its docstring
      now says so and points at `auto_calibration.py`.
- [x] The split import paths no longer block the runtime path — the module the
      product actually calls uses qualified imports throughout. The older
      supervised scripts still carry bare `from collectors...` and still only
      work from one working directory.

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

**Lifecycle carbon** (shipped 19 Aug)

- [x] **Manufacturing carbon and battery health.** Every other panel measures
      electricity, and for a laptop electricity is the small number. Measured
      here: 12.9 kg CO2eq/year operating against roughly 300 kg to
      manufacture - **about 23 years of operation, 82% of lifetime carbon**.
      Keeping the machine one year longer avoids ~50 kg, more than 3.9 years
      of its own electricity.

      Battery health comes from `root\wmi` BatteryStaticData rather than
      Win32_Battery, which reports DesignCapacity and FullChargeCapacity as
      None on modern machines (verified - both null here). **This machine is
      at 46%**, and battery wear is the usual trigger for replacing a laptop
      that still works, which makes it the highest-leverage row on the
      dashboard despite having nothing to do with electricity.

      The embodied figure is the softest number in the project: a
      manufacturer's estimate, not a measurement, and published PCFs carry
      wide uncertainty of their own. The panel states its provenance, shows a
      200-400 kg class range when no datasheet is on file, and notes that
      operating emissions are scaled from a partial window so the multiple is
      a floor.

- [ ] **Get the real PCF for the Latitude 7480.** Dell publishes per-model
      Product Carbon Footprint datasheets; `_EMBODIED_KG_CO2E` in
      lifecycle.py is deliberately empty so no guess sits under a real model
      name pretending to be a citation.

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

- [x] ~~`run_calibration.py` unpacks a two-tuple from a function returning a
      list.~~ Superseded rather than repaired — see "Resolved from the
      correctness list" above.
- [ ] `recommendations_test.py` calls `engine.evaluate(snapshot)` with one
      argument; the signature now needs `power_watts` too.
- [ ] The supervised calibration scripts still use bare `from collectors...`
      imports (`ram_sweep.py` excepted) and only work from one working
      directory. Not on the runtime path, so this is tidiness rather than a
      bug — but it is the reason `run_calibration.py` was dead for weeks
      without anybody noticing.

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
| Labelled fallback instead of hard failure on an unknown model | The repository still raises, but the service falls back to a CPU-class estimate marked `estimated`. Every machine is uncalibrated for a while, and silence is worse than a labelled approximation |
| Statistical baseline instead of fixed thresholds for recommendations | "80 % CPU" is normal for a developer and alarming for an office user; the baseline is the user's own history |
| Two separate SQLite files | `hardware.db` is versioned and shipped; `ecoinsight.db` is per-installation, mutable and growing |
| Two-tier cadence (1.5 s power, 120 s telemetry) | The dashboard needs to feel live; the anomaly baseline needs days of data, not high resolution |
| Country-specific carbon intensity | A world-average factor would misstate Tunisia's >98 % gas-fired grid in either direction |
| Estimators take injected component models / intensity factors | Each can be swapped or unit-tested independently, with no database or collector involvement |
| Filesystem permission as the access control, not the `--mode` flag | Any employee can pass a flag. If a flag were enough to rewrite coefficients, anybody could halve their own reported waste — in a tool whose entire output is a waste figure |
| Provenance recorded per profile and never upgraded | Typing three numbers is not running a sweep. A typed profile that claimed to be measured would inherit a sweep's authority and switch off the warning that exists to flag it |
| The sweep refuses rather than storing a weak fit | Scored by cross-validation against a model that ignores the CPU. A bad "measured" profile is worse than an estimate, because nothing downstream can tell it is wrong |
| A view split by question, not by data source | Twelve identical panels in a column signalled nothing about where to look, and interleaved a weekly digest with a chart that redraws every 1.5 s |
| Absence rendered as absence | Gaps unfilled, comparisons withheld when history is too thin or calibration moved, no cause named unless one process genuinely dominates. On a tool whose whole output is a waste figure, the standing temptation is to produce a number the data does not support |
