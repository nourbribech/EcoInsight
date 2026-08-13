"""
Measure baseline_watts directly, averaged over multiple independent runs.
Each run: sample CPU/power/RAM together, subtract CPU's and RAM's known
contributions using existing coefficients, get one baseline estimate.
Doesn't require CPU at literal 0% — corrects for whatever usage floor
the machine actually has.
"""

import statistics
import time

import psutil

from collectors.hardware import memory
from collectors.windows import system_identity
from scripts.calibration.battery_power import check_battery_in_safe_range, read_discharge_watts
from scripts.calibration.calibration_db import get_field, update_fields


def sample(duration_seconds: float = 10.0, interval_seconds: float = 1.0) -> tuple:
    """Averages CPU usage, discharge watts, and RAM used (GB) together."""
    cpu_readings, watt_readings, ram_readings = [], [], []
    sample_count = max(1, int(duration_seconds / interval_seconds))
    for _ in range(sample_count):
        cpu_readings.append(psutil.cpu_percent(interval=interval_seconds))
        watt_readings.append(read_discharge_watts())
        ram_readings.append(memory.collect()["virtual"]["used"] / (1024 ** 3))
    return (
        statistics.mean(cpu_readings),
        statistics.mean(watt_readings),
        statistics.mean(ram_readings),
    )


def run_once(machine_key: str, cpu_coefficient: float, ram_coefficient: float) -> float:
    avg_cpu, avg_watts, avg_ram_gb = sample()

    cpu_watts = cpu_coefficient * avg_cpu
    ram_watts = ram_coefficient * avg_ram_gb
    baseline_watts = avg_watts - cpu_watts - ram_watts

    print(f"  CPU {avg_cpu:5.2f}%  |  total {avg_watts:6.3f} W  |  RAM {avg_ram_gb:.2f} GB "
          f"-> baseline {baseline_watts:6.3f} W")
    return baseline_watts


def main() -> None:
    check_battery_in_safe_range()

    identity = system_identity.collect()
    machine_key = system_identity.build_machine_key(identity)
    print(f"Machine: {machine_key}\n")

    num_runs = int(input("How many runs to average? [default 5]: ").strip() or "5")

    cpu_coefficient = get_field(machine_key, "cpu_watts_per_percent_usage")
    ram_coefficient = get_field(machine_key, "ram_watts_per_gb_used")

    results = []
    for i in range(num_runs):
        print(f"\nRun {i + 1}/{num_runs}:")
        results.append(run_once(machine_key, cpu_coefficient, ram_coefficient))
        if i < num_runs - 1:
            time.sleep(5)  # brief gap between runs

    mean_baseline = statistics.mean(results)
    stdev_baseline = statistics.stdev(results) if len(results) > 1 else 0.0

    print(f"\n{num_runs} runs: {[f'{r:.3f}' for r in results]}")
    print(f"Mean baseline_watts:  {mean_baseline:.3f} W")
    print(f"Std dev:              {stdev_baseline:.3f} W")

    if mean_baseline <= 0:
        raise RuntimeError(
            f"Mean baseline_watts is non-positive ({mean_baseline:.3f} W). Not writing to DB."
        )

    if stdev_baseline > mean_baseline * 0.5:
        print(f"\nWarning: std dev is large relative to the mean — runs disagree a lot. "
              f"Consider investigating before trusting this value.")

    confirm = input("\nWrite this mean baseline_watts to the DB? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted — nothing written.")
        return

    notes = (
        f"Mean of {num_runs} direct measurements (stdev={stdev_baseline:.3f} W) — "
        f"CPU/RAM contributions subtracted using existing coefficients"
    )
    update_fields(machine_key, {"baseline_watts": mean_baseline}, notes=notes)
    print(f"Saved baseline_watts={mean_baseline:.6f} for {machine_key}")


if __name__ == "__main__":
    main()