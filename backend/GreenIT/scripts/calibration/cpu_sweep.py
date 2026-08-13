"""
CPU calibration sweep.

Manually get the CPU to each target load level, press Enter,
and sample power + CPU usage together.

Run unplugged.
"""

import statistics

import psutil

from scripts.calibration.battery_power import (
    read_discharge_watts,
    fit_line,
)

TARGET_LOAD_LEVELS = [0, 25, 50, 75, 100]
SAMPLE_DURATION_SECONDS = 25


def _sample_level(duration_seconds: int) -> tuple[float, float]:
    """
    Samples CPU usage and total system power once per second.

    Returns:
        (average_cpu_usage_percent, average_power_watts)
    """
    usages = []
    powers = []

    for _ in range(duration_seconds):
        usage = psutil.cpu_percent(interval=1)
        power = read_discharge_watts()

        usages.append(usage)
        powers.append(power)

    return statistics.mean(usages), statistics.mean(powers)


def run_cpu_sweep() -> list[dict]:
    """
    Run one complete CPU calibration sweep.

    Returns a list containing the raw averaged measurement for
    each target load level.

    Each entry contains:
        target_load
        measured_usage_percent
        power_watts
    """

    measurements = []

    for target in TARGET_LOAD_LEVELS:
        input(
            f"Get CPU to ~{target}% load, "
            f"then press Enter to sample..."
        )

        usage, power = _sample_level(SAMPLE_DURATION_SECONDS)

        measurement = {
            "target_load": target,
            "measured_usage_percent": usage,
            "power_watts": power,
        }

        measurements.append(measurement)

        print(
            f"  -> {power:.2f} W at "
            f"{usage:.1f}% measured CPU usage\n"
        )

    # Calculate the regression for this individual run
    usages = [
        measurement["measured_usage_percent"]
        for measurement in measurements
    ]

    powers = [
        measurement["power_watts"]
        for measurement in measurements
    ]

    intercept, slope, r_squared = fit_line(usages, powers)

    print("Individual run result:")
    print(f"  Intercept: {intercept:.2f} W")
    print(f"  CPU coefficient: {slope:.4f} W/%")
    print(f"  R²: {r_squared:.4f}")

    return measurements