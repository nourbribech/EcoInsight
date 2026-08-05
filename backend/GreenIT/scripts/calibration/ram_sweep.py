"""
RAM calibration sweep. Allocates controlled amounts of memory itself
(no manual action needed) and samples power at each level. Run unplugged,
with CPU/disk otherwise idle.
"""

import gc
import time

from scripts.calibration.battery_power import sample_average_watts, fit_line

TARGET_EXTRA_GB = [0, 1, 2, 4]
SAMPLE_DURATION_SECONDS = 20
_BYTES_PER_GB = 1024 ** 3


def run_ram_sweep() -> tuple:
    """Returns (intercept_watts, watts_per_gb_used)."""
    gb_levels = []
    powers = []

    for extra_gb in TARGET_EXTRA_GB:
        print(f"Allocating {extra_gb} GB extra...")
        # Keep a reference so it isn't garbage collected during sampling.
        block = bytearray(int(extra_gb * _BYTES_PER_GB))
        power = sample_average_watts(SAMPLE_DURATION_SECONDS)
        print(f"  -> {power:.2f} W\n")
        gb_levels.append(extra_gb)
        powers.append(power)

        # del alone doesn't guarantee the OS reclaims the pages before the
        # next level starts — force collection and give it a moment, so
        # each level starts from a clean baseline rather than accumulating.
        del block
        gc.collect()
        time.sleep(1)

    intercept, slope, r_squared = fit_line(gb_levels, powers)
    print(f"RAM fit: R²={r_squared:.3f}")
    if r_squared < 0.5:
        print("  WARNING: weak fit — measurements may be too noisy to trust.")
    return intercept, slope


if __name__ == "__main__":
    from collectors.windows import system_identity
    from scripts.calibration.calibration_db import update_fields

    intercept, slope = run_ram_sweep()
    print(f"intercept={intercept:.2f} W, watts_per_gb_used={slope:.4f}")

    identity = system_identity.collect()
    machine_key = system_identity.build_machine_key(identity)
    update_fields(machine_key, {"ram_watts_per_gb_used": slope})
    print(f"Saved ram_watts_per_gb_used for {machine_key}")