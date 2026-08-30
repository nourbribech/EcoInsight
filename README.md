# EcoInsight

**Measures what a Windows laptop actually consumes, in watts, with no external
hardware — then tells you which part of it was avoidable.**

A local agent samples the machine every 1.5 seconds, converts that into energy
and CO₂, and surfaces the waste: a machine left awake with nobody at it, a
build running overnight, a sleep setting that was never going to fire.

The power model is **not guessed from datasheet TDP**. It is calibrated per
machine model by measuring the laptop's own battery discharge rate under
controlled CPU load, then fitting a regression — and the fit is scored against
held-out data before it is trusted.

```
raw OS metrics  →  power (W)  →  energy (Wh)  →  carbon (gCO₂eq)
   psutil/WMI       calibrated     P × Δt        Wh × grid intensity
                    linear model
```

---

## Requirements

**Windows only.** The project depends on WMI for battery discharge and machine
identity, DDC/CI for screen brightness, `powercfg` for power policy, and Task
Scheduler for autostart. There is no Linux or macOS path.

| | |
|---|---|
| OS | Windows 10 / 11 |
| Python | 3.12+ (developed on 3.14) |
| Node | 20+ (developed on 24) |
| Hardware | A **laptop with a battery** — required for calibration, not for running |

No administrator rights are needed to run the agent. Writing a calibration
profile requires write access to `hardware.db`, which is the point (see below).

---

## Install

```powershell
git clone https://github.com/nourbribech/EcoInsight.git
cd EcoInsight

# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Frontend
cd ..\frontend
npm install
npm run build          # the agent serves this build, not the sources
```

## Run

```powershell
cd backend
.\.venv\Scripts\python.exe -m GreenIT.agent
```

Open **http://127.0.0.1:8000**.

That single process runs collection on a background thread and serves both the
API and the dashboard on one port — the same shape as Netdata. If the agent is
up, collection is up.

To start it at log-on:

```powershell
.\.venv\Scripts\python.exe -m GreenIT.scripts.install_autostart install
```

### Developing the frontend

`npm run dev` serves `:5173` with hot reload and proxies `/api` to the agent on
`:8000`. No rebuild needed while you work.

> **The agent serves `frontend/dist`, not the sources.** A frontend change needs
> `npm run build`; a backend change needs the agent restarted. Doing one but not
> the other produces a symptom that looks exactly like a bug in the feature
> itself.

---

## Calibrate

Until a model is calibrated, coefficients are **scaled from the CPU class** and
the dashboard says so. Trends and the share of energy wasted are reliable; the
absolute watts carry an unknown error.

Calibration measures the machine against its own battery, so it needs the
charger out and the machine quiet:

```powershell
cd backend
.\.venv\Scripts\python.exe -m GreenIT.scripts.calibration.auto_calibration --quick --no-write
```

`--no-write` analyses without storing anything. Drop it once the result looks
sound. There is also a button for this in the app, under **IT setup**.

Calibration belongs to a **machine model**, not a machine: a sweep run on one
laptop applies to every identical unit in the fleet. Profiles can be exported
and imported between machines.

### What it refuses to do

These matter more than the measurement:

- **Runs plugged in** — no discharge, no ground truth.
- **Runs on a busy machine** — the sweep can only *add* load, so on a machine
  already at 85 % every level measures near the top and the fit has no spread
  to work with.
- **Stores a weak fit** — the fit is cross-validated against a model that
  ignores the CPU entirely. Below threshold the estimated profile is kept,
  because a bad *measured* profile inherits a sweep's authority without having
  earned it.
- **Calls typed numbers "measured"** — the entry form always records `entered`.
  Only a sweep, or importing a file already classified elsewhere, produces
  `measured`.

---

## Access control

The `--mode it` flag and the in-app unlock are **view switches, not
permissions**. Any employee can use either.

The real gate is the **filesystem**: the app attempts the write and lets Windows
refuse. On a managed fleet `hardware.db` is administrator-only. That matters
because the tool's entire output is a waste figure — if a flag were enough to
rewrite coefficients, anybody could drop their baseline and watch a third of
their reported waste disappear.

---

## What it will not tell you

Stated plainly, because a measurement tool that hides its limits is worse than
one that has none:

- **The component breakdown is not physical.** The total is defensible; the
  split between CPU, RAM and baseline is not. DRAM power scales with *installed*
  capacity, not bytes used, and a RAM sweep on the reference machine could not
  separate a memory effect from sensor noise.
- **Two CPU estimates disagree by ~28 %.** A synthetic-load sweep gives
  0.1345 W/%, the shipped calibration 0.1053 W/%, with non-overlapping
  intervals. Unresolved.
- **The screen is not in the model.** Brightness is recorded and charted but
  absorbed into the constant term, on a device where the panel is one of the
  largest consumers.
- **One machine model is calibrated.** The premise is a fleet of standardised
  PCs; n=1 does not test that.
- **Manufacturing carbon is a class estimate**, not a manufacturer datasheet.
  The panel says so and shows a range.

---

## Documentation

| | |
|---|---|
| [PROJECT.md](PROJECT.md) | Architecture, calibration methodology, design decisions, open work |
| [DEMO-setup.md](DEMO-setup.md) | Running the IT setup and calibration demo end to end |
| **Guide** tab, in the app | What each number means, for the person using it |

---

## Context

Built as a *stage de perfectionnement* project at **Sofrecom Tunisie**
(Orange Group), 2026. Carbon intensity defaults to **483 gCO₂eq/kWh**, the
Tunisian grid — over 98 % gas-fired. The factor is injected, not hardcoded into
the estimator, so another region needs a value rather than a code change.
