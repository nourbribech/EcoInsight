"""
How wrong is the power model?

    python -m GreenIT.scripts.calibration.validate_model

Every watt-hour, every gram of CO2eq and every recommendation this project
produces traces back to one linear fit on 45 battery-discharge measurements.
Until now the only quality figure anyone had for it was the R-squared of that
fit, reported on the very data it was fitted to. That number cannot be
evidence: a model with enough freedom scores well on its own training data by
construction. The question a reader will ask is how wrong it is on
measurements it has never seen, and this script answers that.

WHY THE SPLIT IS BY SESSION AND SWEEP, NOT BY ROW
Rows inside one sweep are not independent observations. They share a battery
state of charge, a thermal state, and whatever else the machine happened to
be doing that afternoon. Splitting them at random puts near-duplicate rows on
both sides of the fence, and the held-out error that comes back is
optimistic - it measures interpolation between neighbouring points rather
than prediction of a new situation. Grouped splits are the honest version:

  leave-one-sweep-out    9 folds. Can the model predict a sweep it has not
                         seen, given others from the same day?
  leave-one-session-out  3 folds. The real deployment question: fitted on
                         some days, does it work on a different one?

Session is the harder test and the one that matters, because a calibration is
performed once and then used forever after.

A NOTE ON run_id
The CSV's run_id restarts at 1 in every session, so runs 1-3 exist on both
7 and 8 August. Grouping by run_id alone silently merges measurements from
different days into one "run" and leaks across the split - the exact mistake
this file exists to avoid. The grouping key is (date, run_id).
"""

import csv
import statistics
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "cpu_calibration_runs.csv"

# The coefficients currently shipped in hardware.db, for the Latitude 7480.
SHIPPED_BASELINE_WATTS = 1.9193185690699588
SHIPPED_CPU_WATTS_PER_PERCENT = 0.10531828148064165
SHIPPED_RAM_WATTS_PER_GB = 0.375

# The calibration CSV never recorded memory use, so the shipped model's RAM
# term CANNOT be reconstructed from it. Every number this file prints for the
# shipped model is conditional on the value below, and the sensitivity table
# in the output exists because that conditionality is easy to forget:
# the shipped model is unbiased at 7.4 GB and looks 1.35 W high at 11 GB,
# purely from this assumption. Live RAM use spans 7.0-16.5 GB.
#
# Do not read the shipped-model row as a measurement. The honest statement is
# that the CPU slope is validated and the constant term is not identifiable
# from this data -- see IDENTIFIABILITY below.
ASSUMED_RAM_GB = 11.0

# WHY THE CONSTANT TERM CANNOT BE VALIDATED HERE
# These 45 points constrain only the SUM (baseline + ram_term), because RAM
# never varied within them. Any split of that sum fits the data identically.
#
# The shipped baseline was itself derived by subtracting the RAM contribution
# from idle measurements, so the RAM coefficient defines the baseline and the
# fit can never contradict the RAM coefficient. That circularity means no
# amount of analysis of THIS file's data can say whether 0.375 W/GB (the
# CodeCarbon 3W/8GB value) is right.
#
# Only an experiment that varies memory at fixed CPU can answer it, and one
# is already written: ram_sweep.py. It has never been run -- there is no
# result file for it -- which is why the coefficient is still a literature
# value rather than a measurement of this machine.


def load_rows() -> list[dict]:
    rows = []
    with open(DATA_PATH, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append({
                "usage": float(row["measured_usage_percent"]),
                "watts": float(row["power_watts"]),
                "target": int(row["target_load_percent"]),
                "date": row["timestamp"][:10],
                # See the module docstring: run_id alone is not unique.
                "sweep": (row["timestamp"][:10], row["run_id"]),
            })
    return rows


def fit_linear(rows: list[dict]) -> tuple[float, float]:
    """Ordinary least squares of watts on CPU usage. Returns (intercept, slope)."""
    xs = [r["usage"] for r in rows]
    ys = [r["watts"] for r in rows]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return mean_y, 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
    return mean_y - slope * mean_x, slope


def errors(predictions: list[float], actuals: list[float]) -> dict:
    residuals = [p - a for p, a in zip(predictions, actuals)]
    mean_actual = statistics.fmean(actuals)
    ss_res = sum(r ** 2 for r in residuals)
    ss_tot = sum((a - mean_actual) ** 2 for a in actuals)
    return {
        "mae": statistics.fmean([abs(r) for r in residuals]),
        "rmse": (ss_res / len(residuals)) ** 0.5,
        "mape": statistics.fmean([abs(r) / a for r, a in zip(residuals, actuals)]) * 100,
        "bias": statistics.fmean(residuals),
        # Held-out R-squared can go negative, and that is not a bug: it means
        # the model predicts the unseen fold worse than simply guessing that
        # fold's own average. Worth printing precisely because the in-sample
        # version can never do this and so can never warn anyone.
        "r2": 1 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "n": len(residuals),
    }


def cross_validate(rows: list[dict], group_key: str, model: str) -> dict:
    """Grouped leave-one-out. `model` is 'linear' or 'constant'."""
    groups = sorted({r[group_key] for r in rows}, key=str)
    predictions, actuals = [], []

    for held_out in groups:
        train = [r for r in rows if r[group_key] != held_out]
        test = [r for r in rows if r[group_key] == held_out]

        if model == "constant":
            # The null model: ignore CPU entirely, predict the training mean.
            # Any model that cannot beat this has learned nothing, and this is
            # the comparison R-squared is silently making.
            mean_watts = statistics.fmean([r["watts"] for r in train])
            predictions += [mean_watts] * len(test)
        else:
            intercept, slope = fit_linear(train)
            predictions += [intercept + slope * r["usage"] for r in test]

        actuals += [r["watts"] for r in test]

    return errors(predictions, actuals)


def evaluate_shipped(rows: list[dict]) -> dict:
    """The coefficients actually in production, applied to every row."""
    constant = SHIPPED_BASELINE_WATTS + SHIPPED_RAM_WATTS_PER_GB * ASSUMED_RAM_GB
    predictions = [constant + SHIPPED_CPU_WATTS_PER_PERCENT * r["usage"] for r in rows]
    return errors(predictions, [r["watts"] for r in rows])


def show(title: str, result: dict) -> None:
    print(f"  {title:34} MAE {result['mae']:5.2f} W   RMSE {result['rmse']:5.2f} W   "
          f"MAPE {result['mape']:5.1f}%   bias {result['bias']:+5.2f} W   "
          f"R2 {result['r2']:6.3f}")


def main() -> None:
    rows = load_rows()
    watts = [r["watts"] for r in rows]

    print("=" * 100)
    print("POWER MODEL VALIDATION")
    print("=" * 100)
    print(f"  {len(rows)} measurements, "
          f"{len({r['sweep'] for r in rows})} sweeps, "
          f"{len({r['date'] for r in rows})} sessions")
    print(f"  power {min(watts):.2f}-{max(watts):.2f} W "
          f"(mean {statistics.fmean(watts):.2f}, sd {statistics.pstdev(watts):.2f})")
    print()

    intercept, slope = fit_linear(rows)
    in_sample = errors([intercept + slope * r["usage"] for r in rows], watts)
    print("  IN-SAMPLE (fitted and scored on all 45 points -- the flattering number)")
    show(f"linear, {intercept:.2f} + {slope:.4f}*cpu%", in_sample)
    print()

    print("  HELD OUT (scored only on data the fit never saw)")
    show("leave-one-sweep-out, linear", cross_validate(rows, "sweep", "linear"))
    show("leave-one-sweep-out, constant", cross_validate(rows, "sweep", "constant"))
    show("leave-one-session-out, linear", cross_validate(rows, "date", "linear"))
    show("leave-one-session-out, constant", cross_validate(rows, "date", "constant"))
    print()

    print("  SHIPPED COEFFICIENTS -- CONDITIONAL, memory use was never recorded")
    show(f"{SHIPPED_BASELINE_WATTS:.2f} + {SHIPPED_RAM_WATTS_PER_GB}*{ASSUMED_RAM_GB}GB "
         f"+ {SHIPPED_CPU_WATTS_PER_PERCENT:.4f}*cpu%", evaluate_shipped(rows))
    print()
    print("    sensitivity to that assumption (live RAM use spans 7.0-16.5 GB):")
    for assumed_gb in (7.0, 7.4, 9.0, 11.0, 13.0, 16.0):
        constant = SHIPPED_BASELINE_WATTS + SHIPPED_RAM_WATTS_PER_GB * assumed_gb
        result = errors(
            [constant + SHIPPED_CPU_WATTS_PER_PERCENT * r["usage"] for r in rows], watts)
        note = "  <-- unbiased" if abs(result["bias"]) < 0.02 else ""
        print(f"      {assumed_gb:5.1f} GB   constant {constant:5.2f} W   "
              f"bias {result['bias']:+5.2f} W   MAE {result['mae']:4.2f} W{note}")
    print()
    print("    The shipped model is unbiased if calibration ran near 7.4 GB, which is")
    print("    plausible for a stress-test session. This row is NOT evidence of error.")
    print()

    print("  PER-SESSION FITS (does the relationship hold still between days?)")
    for date in sorted({r["date"] for r in rows}):
        session = [r for r in rows if r["date"] == date]
        a, b = fit_linear(session)
        print(f"    {date}  n={len(session):2}  {a:5.2f} + {b:.4f}*cpu%   "
              f"mean power {statistics.fmean([r['watts'] for r in session]):5.2f} W")

    print()
    _report_history_impact(intercept, slope)


def _report_history_impact(intercept: float, slope: float) -> None:
    """
    What the shipped model's bias has done to the numbers already stored.

    Kept separate from the validation itself: everything above is a statement
    about the model, this is a statement about the database, and conflating
    the two is how a calibration error quietly becomes a reporting error.
    """
    try:
        from GreenIT.database import database
    except Exception as error:  # pragma: no cover - script convenience
        print(f"  (skipping history impact: {error})")
        return

    connection = database.get_connection()
    rows = connection.execute(
        "SELECT cpu_watts, total_watts, interval_watt_hours FROM measurements "
        "WHERE total_watts > 0"
    ).fetchall()
    connection.close()

    if not rows:
        print("  (no measurements recorded yet)")
        return

    recorded_wh = corrected_wh = 0.0
    for row in rows:
        # Recover the CPU usage percentage the estimator saw, so the
        # two-parameter model can be replayed against the same input.
        usage = row["cpu_watts"] / SHIPPED_CPU_WATTS_PER_PERCENT
        corrected_watts = intercept + slope * usage
        recorded_wh += row["interval_watt_hours"]
        corrected_wh += row["interval_watt_hours"] * corrected_watts / row["total_watts"]

    delta = 100 * (recorded_wh - corrected_wh) / corrected_wh
    print("  IF the two-parameter model were used instead")
    print(f"    recorded    {recorded_wh:8.1f} Wh   ({len(rows)} measurements)")
    print(f"    replayed    {corrected_wh:8.1f} Wh   ({delta:+.1f}%)")
    print("    A difference, not an error: the two models disagree because they")
    print("    assume different memory use, and neither has been tested against a")
    print("    measurement where memory varied. Run ram_sweep.py to break the tie.")


if __name__ == "__main__":
    main()
