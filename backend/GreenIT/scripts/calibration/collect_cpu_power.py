"""
Developer calibration tool: measures real CPU Package Power at controlled
load levels using LibreHardwareMonitor's WMI provider, fits a linear
model (idle_watts + watts_per_percent_usage), and saves the result into
hardware.db for the current machine model.

NOT part of the runtime application. Run manually, once per machine
model, whenever (re)calibration is needed.

Prerequisites:
- LibreHardwareMonitor must already be running, as Administrator, with
  WMI sharing enabled (on by default in recent versions). If it isn't
  running elevated, sensor values read back as empty/zero.
- A row for this exact machine model must already exist in hardware.db
  (e.g. via scripts/setup_hardware_db.py) — this script UPDATEs the CPU
  columns of that existing row; it does not create a new row from
  scratch, since it doesn't know reasonable defaults for RAM/disk/
  baseline coefficients it isn't calibrating here.

Important: power is regressed against psutil's cpu_percent() — the exact
same signal the runtime PowerEstimator reads live — not against
LibreHardwareMonitor's own "CPU Total" load sensor, which can report a
slightly different number. Calibrating against any other signal than the
one actually used at runtime would silently degrade accuracy.

Procedure: for each target load level, get the CPU to roughly that load
(a stress-testing tool, or manually opening enough work), then press
Enter. The script samples both power and usage for a few seconds and
averages the readings before moving to the next level.

Run from the backend/ directory:
    python -m ecoinsight.scripts.calibration.collect_cpu_power
"""

import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

import psutil
import wmi

from GreenIT.collectors.windows import system_identity

HARDWARE_DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "data" / "hardware.db"

TARGET_LOAD_LEVELS = [0, 25, 50, 75, 100]  # percent — for operator guidance only
SAMPLE_DURATION_SECONDS = 5
SAMPLE_INTERVAL_SECONDS = 0.5


def read_cpu_package_power() -> float:
    """Reads the current CPU Package Power (W) from LibreHardwareMonitor via WMI."""
    c = wmi.WMI(namespace="root\\LibreHardwareMonitor")
    for sensor in c.Sensor():
        if sensor.SensorType == "Power" and "Package" in sensor.Name:
            return float(sensor.Value)
    raise RuntimeError(
        "No 'CPU Package Power' sensor found. Is LibreHardwareMonitor "
        "running as Administrator with WMI sharing enabled?"
    )


def sample_power_and_usage() -> tuple[float, float]:
    """
    Averages CPU Package Power and psutil CPU usage over a short window,
    to smooth out sensor noise while the CPU is held at a roughly steady
    load level.
    """
    power_readings = []
    usage_readings = []

    sample_count = int(SAMPLE_DURATION_SECONDS / SAMPLE_INTERVAL_SECONDS)
    for _ in range(sample_count):
        power_readings.append(read_cpu_package_power())
        usage_readings.append(psutil.cpu_percent(interval=SAMPLE_INTERVAL_SECONDS))

    return statistics.mean(power_readings), statistics.mean(usage_readings)


def fit_linear_model(usage_percentages: list, powers: list) -> tuple:
    """
    Fits power = idle_watts + slope * usage_percent via ordinary least
    squares. Returns (idle_watts, watts_per_percent_usage).
    """
    mean_x = statistics.mean(usage_percentages)
    mean_y = statistics.mean(powers)

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(usage_percentages, powers))
    denominator = sum((x - mean_x) ** 2 for x in usage_percentages)

    slope = numerator / denominator
    intercept = mean_y - slope * mean_x

    return intercept, slope


def save_cpu_calibration(machine_key: str, idle_watts: float, watts_per_percent_usage: float) -> None:
    with sqlite3.connect(HARDWARE_DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE calibration_profiles
            SET cpu_idle_watts = ?,
                cpu_watts_per_percent_usage = ?,
                calibrated_at = ?
            WHERE machine_model = ?
            """,
            (idle_watts, watts_per_percent_usage, datetime.now(timezone.utc).isoformat(), machine_key),
        )
        if cursor.rowcount == 0:
            raise RuntimeError(
                f"No existing row for machine model {machine_key!r} in hardware.db. "
                "Run scripts/setup_hardware_db.py (or insert a row manually) first."
            )


def main() -> None:
    identity = system_identity.collect()
    machine_key = system_identity.build_machine_key(identity)
    print(f"Calibrating CPU power model for: {machine_key}\n")

    usage_percentages = []
    powers = []

    for target in TARGET_LOAD_LEVELS:
        input(
            f"Get the CPU to roughly {target}% load, then press Enter to sample "
            f"({SAMPLE_DURATION_SECONDS}s window)..."
        )
        power, usage = sample_power_and_usage()
        print(f"  -> measured {power:.2f} W at {usage:.1f}% usage\n")
        usage_percentages.append(usage)
        powers.append(power)

    idle_watts, watts_per_percent_usage = fit_linear_model(usage_percentages, powers)
    print(
        f"Fitted model: idle_watts={idle_watts:.2f}, "
        f"watts_per_percent_usage={watts_per_percent_usage:.4f}"
    )

    save_cpu_calibration(machine_key, idle_watts, watts_per_percent_usage)
    print(f"Saved to {HARDWARE_DB_PATH}")


if __name__ == "__main__":
    main()