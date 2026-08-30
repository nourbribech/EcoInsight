"""
SUPERSEDED by auto_calibration.py — kept as the record of the original
supervised procedure, not as a working entry point.

Two things stop it running as written. Its imports are unqualified
(`collectors.windows` rather than `GreenIT.collectors.windows`), so importing
it raises; and run_cpu_sweep() calls input() at every load level, waiting for
an operator to drive the CPU by hand, which no button or scheduled task can
answer. auto_calibration.py generates the load itself and is what the IT
screen runs.

Full calibration run: CPU sweep (manual) + RAM sweep (automated) + disk
sweep (automated), then saves the result to hardware.db.

Each sweep produces its own intercept (roughly: "power with that
component idle"). Since all three represent the same real baseline
(everything else idle too), we average them into one baseline_watts
rather than keeping three separate idle terms — a single total-power
sensor can't actually distinguish them anyway.

Run unplugged, from the backend/ directory:
    python -m ecoinsight.scripts.calibration.run_calibration
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from collectors.windows import system_identity
from scripts.calibration.cpu_sweep import run_cpu_sweep
from scripts.calibration.ram_sweep import run_ram_sweep
from scripts.calibration.battery_power import check_battery_in_safe_range

HARDWARE_DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "data" / "hardware.db"


def save(machine_key, baseline_watts, cpu_slope, ram_slope) -> None:
    with sqlite3.connect(HARDWARE_DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE calibration_profiles
            SET baseline_watts = ?,
                cpu_watts_per_percent_usage = ?,
                ram_watts_per_gb_used = ?,
                calibrated_at = ?
            WHERE machine_model = ?
            """,
            (
                baseline_watts, cpu_slope, ram_slope,
                datetime.now(timezone.utc).isoformat(), machine_key,
            ),
        )
        if cursor.rowcount == 0:
            raise RuntimeError(
                f"No existing row for {machine_key!r}. Run setup_hardware_db.py first."
            )


def main() -> None:
    check_battery_in_safe_range()

    identity = system_identity.collect()
    machine_key = system_identity.build_machine_key(identity)
    print(f"Calibrating: {machine_key}\n")

    print("=== CPU sweep ===")
    cpu_intercept, cpu_slope = run_cpu_sweep()

    print("\n=== RAM sweep ===")
    ram_intercept, ram_slope = run_ram_sweep()


    baseline_watts = (cpu_intercept + ram_intercept) / 2

    print(f"\nbaseline_watts={baseline_watts:.2f}")
    print(f"cpu_watts_per_percent_usage={cpu_slope:.4f}")
    print(f"ram_watts_per_gb_used={ram_slope:.4f}")

    save(machine_key, baseline_watts, cpu_slope, ram_slope)
    print(f"\nSaved to {HARDWARE_DB_PATH}")


if __name__ == "__main__":
    main()