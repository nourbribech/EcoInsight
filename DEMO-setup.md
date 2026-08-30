# Demo runbook — IT setup and calibration

Four things to show:

1. **In-app IT unlock** — no command-line flag needed
2. **The setup wizard** — explains the role and the calibration flow
3. **A measured calibration, run from a button** — CPU sweep, validated, stored
4. **Instant sync** — the employee session picks it up without restarting

---

## Before anything else

### 1. Rebuild the frontend

The agent serves `frontend/dist`, **not** the source files. Any change to the
React code is invisible until the bundle is rebuilt.

```powershell
cd frontend
npm run build
```

> This is the single most common reason "the change isn't showing up". If the
> UI looks like an older version, this is why.

### 2. For the calibration step — unplug, and quiet the machine

The sweep measures power from the battery's discharge rate, so:

- **The charger must be disconnected.** Plugged in, it refuses immediately.
- **Battery between 30% and 100%.** Below that, Windows throttles the CPU and
  the fuel gauge gets noisy.
- **Close what you are not using.** The sweep can only *add* load. On a machine
  already at 85% with a browser, an IDE and PowerPoint open, every level
  measures near the top and the fit has no spread to work with — it will refuse
  rather than store a meaningless result.

Check the machine is quiet enough:

```powershell
cd backend
.\.venv\Scripts\python.exe -c "import psutil,statistics; print(round(statistics.fmean(psutil.cpu_percent(interval=1) for _ in range(3)),1), '%')"
```

Anything above **40%** and the sweep will decline to run.

---

## Run it

Two sessions side by side, from `backend/`:

```powershell
# 1 — the real machine, with its actual history
.\.venv\Scripts\python.exe -m GreenIT.agent --port 8001

# 2 — a machine whose model has never been calibrated
.\.venv\Scripts\python.exe -m GreenIT.agent `
    --port 8002 `
    --database .\demo.db `
    --machine-key "Acme FieldBook 14"
```

Open **http://127.0.0.1:8001** and **http://127.0.0.1:8002**.

`--machine-key` makes the agent look itself up under a name no profile exists
for, so it falls back to an estimate. `--database` keeps the demo's
measurements out of the real history.

> Both sessions read the same fleet-wide `hardware.db`. That is what makes the
> cross-session sync work — and it is also why `--machine-key` matters: without
> it, a demo sweep would overwrite the real machine's profile.

---

## What to show

### 1 — The real dashboard, on :8001

| Where | What to say |
|---|---|
| Today | Weeks of real measurements from this machine |
| This week's goal | The target is chosen by the user, not imposed |
| What you can improve | One ranked list, not three unranked ones |
| Live | Power decomposed: baseline, CPU, RAM |
| Machine | Manufacturing carbon against operating carbon |

### 2 — An uncalibrated machine, on :8002

The employee sees a one-time notice:

> **This model has not been calibrated yet**
> Power figures are scaled from the CPU class of this machine rather than
> measured on it. Day-to-day trends and the share of energy wasted are
> reliable; the absolute watts carry an unknown error until IT runs a
> calibration.

Points to make:

- A one-time acknowledgement, not a block and not a choice
- Until a sweep runs, the only alternative to estimated coefficients is no
  absolute numbers at all — a "wait for IT" button would have nowhere to go
- The consent is keyed to the coefficients' **source**. If IT later changes the
  profile, the notice returns, because that is a different claim about the
  numbers

### 3 — Unlocking IT mode

On :8002, go to the **IT setup** tab.

- With write access to `hardware.db` → **🔓 Unlock IT Mode**
- Without it → an explanation of why the option is not offered

Click it. The page reloads in IT mode and the wizard appears.

> The tab is visible to everyone, because it is the only route to the unlock
> button. What it *contains* depends on the session.

**Going back** is a press of **← Return to the employee view**, at the bottom
of the IT setup panel. Worth showing: it makes the point that IT mode is a
view, not a state somebody gets trapped in.

The way out appears only when IT mode came from the button. A session started
with `--mode it` says so instead, because the flag is re-read on every request
and no button could undo it — an option that silently did nothing would be
worse than an explanation.

### 4 — The wizard (5 steps)

| Step | Content |
|---|---|
| 1 | The IT role: calibrate power models for the fleet |
| 2 | Measured → entered/imported → automatic sync |
| 3 | This machine's status and what it means for employees |
| 4 | **Measure this machine** — the sweep |
| 5 | What IT can now do |

**Step 4 is the one to dwell on.** Two buttons:

- **Quick sweep · ~90 s** — 4 load levels, one round. For demonstrating.
- **Full sweep · ~6 min** — 5 levels, 3 randomised rounds. For real use.

What happens while it runs:

- Worker processes drive the CPU to each target level
- Usage and battery discharge are sampled together, once a second
- Levels are visited in **randomised order**, so battery drift spreads across
  all of them instead of masquerading as a CPU effect
- A line is fitted, and its quality is checked before anything is stored

What comes back:

```
Baseline · x.xx W
CPU · 0.xxxxx W/%
RAM · 0.375 W/GB   (reference value, not measured here)
R² cross-validated · 0.8xx   vs -0.0xx for a model that ignores the CPU
```

**The R² line is the point.** Say it out loud:

> The figure on the left is scored on data the fit never saw. The one on the
> right is what you would get from a model that ignores the processor entirely.
> The gap between them is the evidence that the coefficient means something.

### 5 — What it refuses to do

Worth showing deliberately, because refusals are the credibility argument:

| Try this | What happens |
|---|---|
| Run the sweep plugged in | *"Laptop is plugged in — unplug it before calibrating."* |
| Run it with everything open | *"The machine is already at 85% CPU with nothing asked of it…"* |
| Type `1.05` for CPU W per % | *"outside the plausible range 0.02–0.6. Check for a misplaced decimal point."* |

And the one that does not need a demo, only a sentence:

> The form saves as **"entered"**, never **"measured"** — typing three numbers
> is not running a sweep. Only the sweep itself, and importing a file already
> classified elsewhere, can produce "measured".

### 6 — The employee picks it up

Back on :8001 — or reload :8002's user view. Within one poll cycle the new
profile is in use, and the acknowledgement returns because the basis of the
numbers changed.

> The profile cache is keyed on the calibration file's modification time, so a
> profile written by one session is visible to every other one without anybody
> restarting anything.

---

## Reversibility — worth demonstrating

In the calibration table, each row has a **Remove** button. Press it once and
it asks again in place, naming what it is about to do; press **Keep** to back
out. On a row marked `measured` the confirming button says so explicitly,
because that row may be the only record of a sweep that cost hours.

The file is copied before every removal regardless, so a mistake is recoverable
even past the confirmation.

Once removed, machines of that model fall back to an estimate — no restart, no
support ticket. Say it out loud:

> A calibration is never permanent. Adding one and removing one are the same
> amount of work, which is what makes it safe for IT to add one at all.

---

## Reset between runs

Removing the demo profile is a **Remove** press in the calibration table. The
script below is for resetting everything at once between rehearsals.

```powershell
# from backend/
Remove-Item .\demo.db -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe -c @'
import sqlite3
from GreenIT.services.estimation_loop import HARDWARE_DB_PATH
c = sqlite3.connect(HARDWARE_DB_PATH)
c.execute("DELETE FROM calibration_profiles WHERE machine_model LIKE 'Acme%'")
c.commit()
print("demo profile removed")
'@
```

Deleting `demo.db` resets the wizard and the acknowledgement, so the
first-login flow appears again.

### Replaying the wizard between rehearsals

Press **↻ Replay the walkthrough** at the bottom of the IT setup panel. No
terminal, no restart, and it does not disturb the stored profile.

> The walkthrough is shown once per **database**, not once per machine model.
> Changing `--machine-key` does not bring it back, and neither does deleting a
> profile — the flag records that this operator has read it, which is a fact
> about the person rather than about the machine.

The command below still exists for a fully clean state:

```powershell
.\.venv\Scripts\python.exe -c @'
import sqlite3
c = sqlite3.connect("demo.db")
c.execute("DELETE FROM settings WHERE key IN ('it_wizard_completed','calibration_acknowledged','it_mode_unlocked')")
c.commit()
print("wizard reset")
'@
```

---

## Access control — what is actually enforcing it

`--mode it` and the unlock button are **view switches, not permissions**. Any
employee can pass the flag or click the button.

The real gate is the **filesystem**: the app tries to take a write lock on
`hardware.db` and lets Windows refuse. On a managed fleet that file is
administrator-only.

To demonstrate:

1. Deny your account write access to
   `backend\GreenIT\database\data\hardware.db`
2. Reload the app
3. The unlock button disappears, the form disappears, the table becomes
   read-only, and the reason is stated rather than looking like a fault

---

## If something goes wrong

| Symptom | Cause |
|---|---|
| UI looks like an old version | `npm run build` was not run |
| Wizard does not appear | It is shown once per database. Press **↻ Replay the walkthrough** at the bottom of the IT setup panel |
| Sweep refuses instantly | Plugged in, battery out of range, or machine too busy |
| Sweep runs but is rejected | Cross-validated R² below 0.5 — usually a busy machine |
| Port already in use | Another agent is still running; pick another `--port` |
| Stuck in IT mode | **← Return to the employee view**, bottom of the IT setup panel. If the session was started with `--mode it`, restart without the flag |

**Record a video of the full run the day before.** A live demo that fails in
front of a jury costs more than the time it takes — announce the recording
plainly and move on.
