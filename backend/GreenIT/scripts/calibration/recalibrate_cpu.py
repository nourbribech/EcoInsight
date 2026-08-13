"""
Repeated CPU calibration.

Loads all previous CPU calibration measurements for the current machine,
runs additional CPU sweeps, combines old and new measurements into one
regression, and updates only the CPU calibration coefficient in hardware.db.

RAM calibration and baseline_watts are left untouched.

Run unplugged.
"""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from GreenIT.collectors.windows import system_identity
from GreenIT.scripts.calibration.battery_power import (
    check_battery_in_safe_range,
    fit_line,
)
from GreenIT.scripts.calibration.cpu_sweep import run_cpu_sweep


NUMBER_OF_RUNS = 3

DATA_DIRECTORY = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA_DIRECTORY / "cpu_calibration_runs.csv"

HARDWARE_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "database"
    / "data"
    / "hardware.db"
)


def load_previous_measurements(machine_key: str) -> list[dict]:
    """
    Load all previously recorded measurements for this machine
    from the calibration CSV.
    """

    if not CSV_PATH.exists():
        return []

    measurements = []

    with CSV_PATH.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            if row["machine_model"] != machine_key:
                continue

            measurements.append(
                {
                    "target_load": float(row["target_load_percent"]),
                    "measured_usage_percent": float(
                        row["measured_usage_percent"]
                    ),
                    "power_watts": float(row["power_watts"]),
                }
            )

    return measurements


def get_next_run_id(machine_key: str) -> int:
    """
    Find the next available run ID for this machine.
    """

    if not CSV_PATH.exists():
        return 1

    highest_run_id = 0

    with CSV_PATH.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            if row["machine_model"] != machine_key:
                continue

            run_id = int(row["run_id"])
            highest_run_id = max(highest_run_id, run_id)

    return highest_run_id + 1


def save_measurements(
    machine_key: str,
    run_id: int,
    measurements: list[dict],
) -> None:
    """
    Append raw measurements from one CPU sweep to the CSV file.
    """

    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    file_exists = CSV_PATH.exists()

    with CSV_PATH.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow(
                [
                    "machine_model",
                    "run_id",
                    "timestamp",
                    "target_load_percent",
                    "measured_usage_percent",
                    "power_watts",
                ]
            )

        for measurement in measurements:
            writer.writerow(
                [
                    machine_key,
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    measurement["target_load"],
                    measurement["measured_usage_percent"],
                    measurement["power_watts"],
                ]
            )


def update_cpu_coefficient(
    machine_key: str,
    cpu_slope: float,
) -> None:
    """
    Update ONLY the CPU coefficient.

    RAM calibration and baseline_watts are deliberately untouched.
    """

    with sqlite3.connect(HARDWARE_DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE calibration_profiles
            SET cpu_watts_per_percent_usage = ?,
                calibrated_at = ?
            WHERE machine_model = ?
            """,
            (
                cpu_slope,
                datetime.now(timezone.utc).isoformat(),
                machine_key,
            ),
        )

        if cursor.rowcount == 0:
            raise RuntimeError(
                f"No calibration profile found for {machine_key!r}."
            )


def main() -> None:
    check_battery_in_safe_range()

    identity = system_identity.collect()
    machine_key = system_identity.build_machine_key(identity)

    print("=" * 60)
    print("CPU RECALIBRATION")
    print("=" * 60)
    print(f"Machine: {machine_key}")
    print(f"New runs: {NUMBER_OF_RUNS}")
    print(f"Output: {CSV_PATH}")
    print()

    # ---------------------------------------------------------
    # Load previous measurements
    # ---------------------------------------------------------

    previous_measurements = load_previous_measurements(machine_key)

    next_run_id = get_next_run_id(machine_key)

    print(
        f"Previous measurements loaded: "
        f"{len(previous_measurements)}"
    )

    if previous_measurements:
        print(
            f"Starting new runs at run ID: "
            f"{next_run_id}"
        )
    else:
        print("No previous measurements found.")

    print()

    # ---------------------------------------------------------
    # Run new calibration sweeps
    # ---------------------------------------------------------

    new_measurements = []

    for run_number in range(NUMBER_OF_RUNS):
        run_id = next_run_id + run_number

        print("=" * 60)
        print(
            f"CPU SWEEP "
            f"{run_number + 1}/{NUMBER_OF_RUNS} "
            f"(run ID {run_id})"
        )
        print("=" * 60)

        measurements = run_cpu_sweep()

        save_measurements(
            machine_key,
            run_id,
            measurements,
        )

        new_measurements.extend(measurements)

        # Show the result of this individual run
        usages = [
            measurement["measured_usage_percent"]
            for measurement in measurements
        ]

        powers = [
            measurement["power_watts"]
            for measurement in measurements
        ]

        intercept, slope, r_squared = fit_line(
            usages,
            powers,
        )

        print()
        print("Individual run result:")
        print(f"Intercept:       {intercept:.3f} W")
        print(f"CPU coefficient: {slope:.5f} W/%")
        print(f"R²:              {r_squared:.4f}")
        print()
        print(f"Run {run_id} saved.")

    # ---------------------------------------------------------
    # Combine ALL historical + new measurements
    # ---------------------------------------------------------

    all_measurements = (
        previous_measurements + new_measurements
    )

    usages = [
        measurement["measured_usage_percent"]
        for measurement in all_measurements
    ]

    powers = [
        measurement["power_watts"]
        for measurement in all_measurements
    ]

    intercept, slope, r_squared = fit_line(
        usages,
        powers,
    )

    print()
    print("=" * 60)
    print("COMBINED CALIBRATION RESULT")
    print("=" * 60)

    print(
        f"Previous measurements: "
        f"{len(previous_measurements)}"
    )

    print(
        f"New measurements:      "
        f"{len(new_measurements)}"
    )

    print(
        f"Total measurements:    "
        f"{len(all_measurements)}"
    )

    print(f"Intercept:              {intercept:.3f} W")
    print(f"CPU slope:              {slope:.5f} W/%")
    print(f"R²:                     {r_squared:.5f}")

    if r_squared < 0.5:
        print("\nWARNING: Combined fit is weak.")

    # ---------------------------------------------------------
    # Update database
    # ---------------------------------------------------------

    print()
    print("Updating hardware.db...")

    update_cpu_coefficient(
        machine_key,
        slope,
    )

    print("CPU coefficient updated.")
    print("RAM coefficient: UNCHANGED")
    print("Baseline watts:  UNCHANGED")
    print()
    print("Raw measurements saved to:")
    print(CSV_PATH)


if __name__ == "__main__":
    main()
