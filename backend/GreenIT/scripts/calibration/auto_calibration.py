"""
Automated end-to-end calibration — the version the IT screen can actually run.

    python -m GreenIT.scripts.calibration.auto_calibration           # ~6 min
    python -m GreenIT.scripts.calibration.auto_calibration --quick   # ~75 s
    python -m GreenIT.scripts.calibration.auto_calibration --json    # for the API

WHY THIS EXISTS ALONGSIDE run_calibration.py
`run_calibration.py` drives the CPU by asking a human to do it: cpu_sweep.py
calls input() at every level and waits for somebody to get the machine to
~75% by hand. That is a supervised laboratory procedure, and it cannot be
started from a button — in a subprocess with no console, the first input()
raises EOFError before a single sample is taken. (It also never ran at all:
its imports are unqualified, so importing it fails outright.)

This module generates the load itself, which removes the operator from the
loop and makes the levels reproducible between runs instead of depending on
how well somebody rode a stress tool.

WHAT IS MEASURED AND WHAT IS NOT
CPU coefficient and baseline are measured here. The RAM coefficient is NOT:
this machine's RAM sweep could not separate a memory effect from sensor noise
(see ram_sweep.py), so a reference value is carried through and reported as
such. Writing a measured-looking number we did not measure would be the one
thing this whole design is built to prevent.

THE ORDER OF LEVELS IS RANDOMISED
Battery voltage sags, a scan finishes, the machine warms up. Anything that
changes monotonically with time lands on whichever level happens to be
sampled late. Visiting levels in a shuffled order across rounds spreads that
drift across every level roughly equally instead of letting it masquerade as
a CPU effect.
"""

import argparse
import json
import multiprocessing
import os
import random
import statistics
import sys
import time

import psutil

from GreenIT.database.calibration_writer import (
    CalibrationWriter,
    CalibrationPermissionError,
    CalibrationWriteError,
)
from GreenIT.scripts.calibration._load import burn
from GreenIT.scripts.calibration.battery_power import (
    check_battery_in_safe_range,
    read_discharge_watts,
)
from GreenIT.services.estimation_loop import HARDWARE_DB_PATH

# Carried through, never claimed as measured. Origin: CodeCarbon's 3 W / 8 GB.
REFERENCE_RAM_WATTS_PER_GB = 0.375

# Below this, the fit is refused rather than written. The threshold is on the
# CROSS-VALIDATED figure, not the in-sample one: the in-sample R² is computed
# on the points that produced the line and can never warn about anything.
MINIMUM_R2 = 0.5

# The sweep can only ADD load, never remove it. On a machine already sitting
# at 85% because a browser, an IDE and a presentation are open, every level
# from 0 to 100 measures somewhere between 80 and 100 — and a line fitted
# through a 15-point spread is arithmetic, not calibration.
#
# Checked before the sweep so a busy machine costs three seconds rather than
# a full run that was never going to mean anything.
MAXIMUM_IDLE_PERCENT = 40
IDLE_CHECK_SECONDS = 3

# And checked again afterwards on what was actually measured, because the
# machine can get busy in the middle of a run that started quiet.
MINIMUM_USAGE_SPREAD = 25

FULL = {"levels": [0, 25, 50, 75, 100], "seconds": 20, "settle": 4, "rounds": 3}
QUICK = {"levels": [0, 35, 70, 100], "seconds": 12, "settle": 3, "rounds": 1}


# --- machine identity -------------------------------------------------------

def resolve_machine_key() -> str:
    """
    The same resolution the running agent uses (hardware_service.py).

    The env override has to win here too. A demo session started with
    --machine-key writes its profile under that key; resolving the real WMI
    identity instead would have a demonstration silently overwrite the
    profile of the machine it is being demonstrated on.
    """
    override = os.environ.get("ECOINSIGHT_MACHINE_KEY")
    if override:
        return override

    from GreenIT.collectors.windows import system_identity

    return system_identity.build_machine_key(system_identity.collect())


# --- load generation --------------------------------------------------------

class CpuLoad:
    """Holds total system CPU near `target_percent` for as long as it is open."""

    def __init__(self, target_percent: float, seconds: float):
        self._target = target_percent
        self._seconds = seconds
        self._workers: list = []

    def __enter__(self):
        if self._target <= 0:
            # Level 0 is whatever the machine does when left alone. It is not
            # forced to literal zero — the regression uses measured usage, so
            # the real idle floor is a data point rather than a problem.
            return self

        duty = min(1.0, self._target / 100.0)
        stop_at = time.time() + self._seconds
        for _ in range(psutil.cpu_count(logical=True) or 1):
            worker = multiprocessing.Process(target=burn, args=(duty, stop_at))
            worker.daemon = True
            worker.start()
            self._workers.append(worker)
        return self

    def __exit__(self, *_) -> None:
        for worker in self._workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=2)
        self._workers.clear()


# --- sampling ---------------------------------------------------------------

def sample(seconds: int) -> tuple[float, float, float]:
    """
    One reading per second of CPU usage, discharge watts and RAM used.

    cpu_percent(interval=1) is what paces the loop: it blocks for the second
    it averages, so the battery is read once per second alongside it rather
    than on a timer of its own that could drift out of step with it.
    """
    usages, watts, rams = [], [], []
    for _ in range(max(1, seconds)):
        usages.append(psutil.cpu_percent(interval=1))
        watts.append(read_discharge_watts())
        rams.append(psutil.virtual_memory().used / (1024 ** 3))
    return statistics.mean(usages), statistics.mean(watts), statistics.mean(rams)


def run_sweep(plan: dict, progress=None) -> list[dict]:
    """Visit every level in every round, in shuffled order, and record each."""
    measurements = []
    total = plan["rounds"] * len(plan["levels"])
    done = 0

    for round_index in range(plan["rounds"]):
        levels = list(plan["levels"])
        random.shuffle(levels)

        for target in levels:
            with CpuLoad(target, plan["seconds"] + plan["settle"] + 2):
                # Let the load settle before sampling: the first second or two
                # after workers start is a ramp, not the level being asked for.
                time.sleep(plan["settle"])
                usage, power, ram_gb = sample(plan["seconds"])

            measurements.append({
                "round": round_index,
                "target_percent": target,
                "usage_percent": usage,
                "watts": power,
                "ram_gb": ram_gb,
            })

            done += 1
            if progress:
                progress(done, total, target, usage, power)

    return measurements


# --- fitting ----------------------------------------------------------------

def fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Ordinary least squares. Returns (intercept, slope)."""
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return mean_y, 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
    return mean_y - slope * mean_x, slope


def r_squared(actuals: list[float], predictions: list[float]) -> float:
    mean_actual = statistics.fmean(actuals)
    ss_res = sum((a - p) ** 2 for a, p in zip(actuals, predictions))
    ss_tot = sum((a - mean_actual) ** 2 for a in actuals)
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


def cross_validate(measurements: list[dict], group_key: str, model: str) -> float:
    """
    Grouped leave-one-out. `model` is 'linear' or 'constant'.

    The constant model is the null hypothesis: ignore CPU entirely and predict
    the training mean. Any model that cannot beat it has learned nothing, and
    that is the comparison R² is silently making anyway. Making it explicit is
    what turns a number into evidence.
    """
    groups = sorted({m[group_key] for m in measurements})
    if len(groups) < 2:
        return float("nan")

    actuals, predictions = [], []
    for held_out in groups:
        train = [m for m in measurements if m[group_key] != held_out]
        test = [m for m in measurements if m[group_key] == held_out]

        if model == "constant":
            mean_watts = statistics.fmean([m["watts"] for m in train])
            predictions += [mean_watts] * len(test)
        else:
            intercept, slope = fit([(m["usage_percent"], m["watts"]) for m in train])
            predictions += [intercept + slope * m["usage_percent"] for m in test]

        actuals += [m["watts"] for m in test]

    return r_squared(actuals, predictions)


def analyse(measurements: list[dict]) -> dict:
    points = [(m["usage_percent"], m["watts"]) for m in measurements]
    intercept, slope = fit(points)
    in_sample = r_squared(
        [y for _, y in points],
        [intercept + slope * x for x, _ in points],
    )

    # Hold out whole rounds when there are several — a round is an independent
    # visit to every level, so leaving one out asks the honest question. With a
    # single round the only grouping available is by level.
    grouping = "round" if len({m["round"] for m in measurements}) > 1 else "target_percent"

    # The baseline comes from the idle level, not from the intercept. The
    # intercept is where the line would cross zero CPU, and the sweep never
    # measures anywhere near zero — it is an extrapolation outside the data.
    # The idle samples are real measurements, corrected for the CPU and RAM
    # actually in use while they were taken.
    idle = min(measurements, key=lambda m: m["usage_percent"])
    baseline = (
        idle["watts"]
        - slope * idle["usage_percent"]
        - REFERENCE_RAM_WATTS_PER_GB * idle["ram_gb"]
    )

    return {
        "cpu_watts_per_percent": slope,
        "baseline_watts": baseline,
        "ram_watts_per_gb": REFERENCE_RAM_WATTS_PER_GB,
        "ram_is_reference_value": True,
        "intercept_watts": intercept,
        "r2_in_sample": in_sample,
        "r2_cross_validated": cross_validate(measurements, grouping, "linear"),
        "r2_null_model": cross_validate(measurements, grouping, "constant"),
        "cross_validation_grouping": grouping,
        "samples": len(measurements),
        "rounds": len({m["round"] for m in measurements}),
        "usage_min": min(m["usage_percent"] for m in measurements),
        "usage_max": max(m["usage_percent"] for m in measurements),
    }


# --- entry point ------------------------------------------------------------

def calibrate(quick: bool = False, write: bool = True, progress=None) -> dict:
    """
    Runs the whole procedure and returns a result dict.

    Never raises for an expected refusal — a plugged-in machine or a weak fit
    are answers, not faults, and the caller has to show them to somebody.
    """
    try:
        check_battery_in_safe_range()
        read_discharge_watts()  # fails fast if AC is connected
    except RuntimeError as error:
        return {"ok": False, "reason": "preconditions", "error": str(error)}

    idle_percent = statistics.fmean(
        psutil.cpu_percent(interval=1) for _ in range(IDLE_CHECK_SECONDS)
    )
    if idle_percent > MAXIMUM_IDLE_PERCENT:
        return {
            "ok": False,
            "reason": "machine_busy",
            "idle_percent": idle_percent,
            "error": (
                f"The machine is already at {idle_percent:.0f}% CPU with nothing "
                f"asked of it. The sweep can only add load, so every level would "
                f"measure near the top and the fit would have almost no spread to "
                f"work with. Close the applications that are running and try again."
            ),
        }

    machine_key = resolve_machine_key()
    plan = QUICK if quick else FULL

    measurements = run_sweep(plan, progress=progress)
    result = analyse(measurements)
    result.update({"ok": True, "machine_key": machine_key, "quick": quick,
                   "idle_percent": idle_percent})

    spread = result["usage_max"] - result["usage_min"]
    if spread < MINIMUM_USAGE_SPREAD:
        result.update({
            "ok": False,
            "reason": "narrow_spread",
            "written": False,
            "error": (
                f"Measured CPU usage only spanned {spread:.0f} points "
                f"({result['usage_min']:.0f}–{result['usage_max']:.0f}%). That is too "
                f"narrow to fit a slope against. Something started competing for the "
                f"processor during the run."
            ),
        })
        return result

    cross_validated = result["r2_cross_validated"]
    if cross_validated == cross_validated and cross_validated < MINIMUM_R2:
        result.update({
            "ok": False,
            "reason": "low_r2",
            "written": False,
            "error": (
                f"Fit rejected: cross-validated R² is {cross_validated:.3f}, "
                f"below the {MINIMUM_R2} threshold. The estimated profile is kept "
                f"rather than storing a measurement that does not hold up."
            ),
        })
        return result

    if not write:
        result["written"] = False
        return result

    notes = (
        f"Automated sweep, {result['samples']} samples over {result['rounds']} round(s), "
        f"cross-validated R²={cross_validated:.3f}. "
        f"RAM coefficient is a reference value, not measured on this machine."
    )

    try:
        CalibrationWriter(HARDWARE_DB_PATH).save(
            machine_model=machine_key,
            cpu_watts_per_percent=result["cpu_watts_per_percent"],
            ram_watts_per_gb=result["ram_watts_per_gb"],
            baseline_watts=result["baseline_watts"],
            source="measured",
            notes=notes,
        )
    except CalibrationPermissionError as error:
        result.update({"ok": False, "reason": "permission", "written": False,
                       "error": str(error)})
        return result
    except CalibrationWriteError as error:
        result.update({"ok": False, "reason": "rejected", "written": False,
                       "error": str(error)})
        return result

    result.update({"written": True, "notes": notes})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated power calibration")
    parser.add_argument("--quick", action="store_true",
                        help="short sweep (~75s) — for demonstrations")
    parser.add_argument("--json", action="store_true",
                        help="emit a single JSON object on stdout")
    parser.add_argument("--no-write", action="store_true",
                        help="analyse only, do not touch hardware.db")
    args = parser.parse_args()

    def report(done, total, target, usage, watts):
        if not args.json:
            print(f"  [{done}/{total}] target {target:3}%  ->  "
                  f"measured {usage:5.1f}%  |  {watts:6.2f} W", flush=True)

    if not args.json:
        plan = QUICK if args.quick else FULL
        print(f"Machine: {resolve_machine_key()}")
        print(f"Plan: {plan['rounds']} round(s) x {len(plan['levels'])} levels "
              f"x {plan['seconds']}s\n", flush=True)

    result = calibrate(quick=args.quick, write=not args.no_write, progress=report)

    if args.json:
        print(json.dumps(result))
        sys.exit(0 if result.get("ok") else 1)

    if not result.get("ok"):
        print(f"\nRefused: {result.get('error')}")
        sys.exit(1)

    print(f"\n  baseline_watts            {result['baseline_watts']:.3f} W")
    print(f"  cpu_watts_per_percent     {result['cpu_watts_per_percent']:.5f} W/%")
    print(f"  ram_watts_per_gb          {result['ram_watts_per_gb']:.3f} W/GB (reference)")
    print(f"  R² in-sample              {result['r2_in_sample']:.3f}")
    print(f"  R² cross-validated        {result['r2_cross_validated']:.3f}")
    print(f"  R² null model             {result['r2_null_model']:.3f}")
    print(f"\n  written: {result.get('written')}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
