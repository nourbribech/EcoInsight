"""
CPU calibration sweep. Manually get the CPU to each target load level,
press Enter, and it samples power + usage together. Run unplugged.
"""

import statistics

import psutil

from scripts.calibration.battery_power import read_discharge_watts, fit_line

TARGET_LOAD_LEVELS = [0, 25, 50, 75, 100]
SAMPLE_DURATION_SECONDS = 25


def _sample_level(duration_seconds: int) -> tuple:
    """
    Samples usage% and power together, once per second, and averages
    both. psutil.cpu_percent(interval=1) blocks for exactly 1s and
    returns usage measured over that same window, which conveniently
    paces the loop to match the battery sensor's ~1s refresh rate — so
    each pair genuinely describes the same second, not two different
    moments.
    """
    usages = []
    powers = []
    for _ in range(duration_seconds):
        usage = psutil.cpu_percent(interval=1)
        powers.append(read_discharge_watts())
        usages.append(usage)
    return statistics.mean(usages), statistics.mean(powers)


def run_cpu_sweep() -> tuple:
    """Returns (intercept_watts, watts_per_percent_usage)."""
    usage_percentages = []
    powers = []

    for target in TARGET_LOAD_LEVELS:
        input(f"Get CPU to ~{target}% load, then press Enter to sample...")
        usage, power = _sample_level(SAMPLE_DURATION_SECONDS)
        print(f"  -> {power:.2f} W at {usage:.1f}% usage\n")
        usage_percentages.append(usage)
        powers.append(power)

    intercept, slope, r_squared = fit_line(usage_percentages, powers)
    print(f"CPU fit: R²={r_squared:.3f}")
    if r_squared < 0.5:
        print("  WARNING: weak fit — measurements may be too noisy to trust.")
    return intercept, slope


if __name__ == "__main__":
    intercept, slope = run_cpu_sweep()
    print(f"intercept={intercept:.2f} W, watts_per_percent_usage={slope:.4f}")