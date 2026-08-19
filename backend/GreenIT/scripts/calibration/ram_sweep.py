"""
Does this machine's power draw actually rise with memory USED?

    python -m GreenIT.scripts.calibration.ram_sweep            # ~12 minutes
    python -m GreenIT.scripts.calibration.ram_sweep --rounds 3 # quicker, noisier

`ram_watts_per_gb_used = 0.375` currently comes from CodeCarbon (3 W / 8 GB),
not from this machine. It is the largest moving part of the power model and
the only one with no measurement behind it: live memory use spans 7-16.5 GB,
which swings that term between 2.6 and 6.2 W on a laptop drawing about 10 W.
This script measures it.

It also tests the SHAPE of the term, which matters more than its value. DRAM
refresh power scales with INSTALLED capacity, not with how many pages the OS
has handed out, so a per-GB-used coefficient may be the wrong form even if
0.375 is the right number. If allocating memory does not move the needle,
the term belongs in the constant.

WHY THIS IS NOT THE ORIGINAL SWEEP
The first version held CPU "idle", allocated 0/1/2/4 GB once each, and fitted
a line through four points. Run on a real machine that design falls apart:

  * It never ran at all -- it imported `scripts.calibration.battery_power`
    while the package is `GreenIT.scripts.calibration`, so it raised on
    import. That is why the coefficient is still a literature value.
  * CPU cannot be assumed idle. Measured just before writing this, the
    machine sat at 91% with a Defender scan, Chrome and the SCCM agent
    running. At 0.105 W per CPU percent that is several watts of movement
    against a RAM effect worth about 1 W -- the confounder is larger than
    the signal. So CPU is MEASURED and regressed out instead of wished away.
  * 4 GB was not allocatable. Only 3.9 GB was free, so the largest step
    would have started paging, and disk activity would have been measured
    as if it were memory cost.
  * Four points, once each, cannot separate a real effect from battery drift.
    Discharge readings here have a standard deviation of 2.4 W. Levels are
    now visited in RANDOMISED order across several rounds, so anything that
    changes monotonically with time -- battery voltage sag, a scan
    finishing, the machine warming up -- lands on every level roughly
    equally instead of masquerading as a memory effect.

Nothing is written to hardware.db. This prints a number and a confidence
interval; deciding what to do about it is a separate, deliberate step.
"""

import argparse
import csv
import gc
import math
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

import psutil

from GreenIT.scripts.calibration.battery_power import (
    check_battery_in_safe_range,
    read_discharge_watts,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
SAMPLES_PATH = DATA_DIR / "ram_calibration_samples.csv"

# Allocated in half-gigabyte blocks so moving between levels touches only the
# difference. Reallocating the whole block each time would zero-fill several
# gigabytes on every step, which is CPU and memory-bandwidth work being done
# precisely while power is being measured.
BLOCK_GB = 0.5
BYTES_PER_GB = 1024 ** 3

# Never drive the machine into paging. Swapping would show up as disk power
# and stalled CPU, and would be recorded as if memory had caused it.
MIN_FREE_GB_AFTER_ALLOCATION = 1.0

SAMPLE_INTERVAL_SECONDS = 2.0  # the fuel gauge refreshes about every 1.7 s


def _allocate(blocks: list, target_blocks: int) -> None:
    """Grows or shrinks the held allocation to `target_blocks` half-GB blocks."""
    while len(blocks) > target_blocks:
        blocks.pop()
        gc.collect()
    while len(blocks) < target_blocks:
        # bytearray zero-fills, which is what makes the pages genuinely
        # resident. A lazier allocation would reserve address space that the
        # OS never backs with physical memory, and the experiment would
        # measure nothing at all.
        blocks.append(bytearray(int(BLOCK_GB * BYTES_PER_GB)))


def _usable_levels(max_extra_gb: float) -> list[float]:
    available_gb = psutil.virtual_memory().available / BYTES_PER_GB
    headroom = available_gb - MIN_FREE_GB_AFTER_ALLOCATION
    ceiling = min(max_extra_gb, math.floor(headroom / BLOCK_GB) * BLOCK_GB)
    if ceiling < BLOCK_GB:
        raise RuntimeError(
            f"Only {available_gb:.1f} GB free — not enough headroom to vary "
            f"memory without paging. Close something and retry."
        )
    steps = int(ceiling / BLOCK_GB)
    return [round(i * BLOCK_GB, 2) for i in range(steps + 1)]


def collect(rounds: int, hold_seconds: float, max_extra_gb: float) -> list[dict]:
    check_battery_in_safe_range()
    levels = _usable_levels(max_extra_gb)

    total_seconds = rounds * len(levels) * hold_seconds
    print(f"levels    {levels} GB extra")
    print(f"rounds    {rounds}, randomised order within each")
    print(f"duration  about {total_seconds / 60:.0f} min\n")

    samples: list[dict] = []
    blocks: list[bytearray] = []
    started = time.monotonic()

    try:
        for round_index in range(rounds):
            order = levels[:]
            random.shuffle(order)
            print(f"round {round_index + 1}/{rounds}: {order}")

            for level in order:
                _allocate(blocks, int(level / BLOCK_GB))
                # Let the allocation settle before measuring: zero-filling is
                # itself CPU work, and its power cost is not what we are after.
                time.sleep(2.0)

                psutil.cpu_percent(None)  # prime the counter
                deadline = time.monotonic() + hold_seconds
                level_watts = []

                while time.monotonic() < deadline:
                    cpu = psutil.cpu_percent(SAMPLE_INTERVAL_SECONDS)
                    memory = psutil.virtual_memory()
                    watts = read_discharge_watts()
                    level_watts.append(watts)
                    samples.append({
                        "timestamp": datetime.now().isoformat(),
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                        "round": round_index + 1,
                        "target_extra_gb": level,
                        "ram_used_gb": round(memory.used / BYTES_PER_GB, 3),
                        "cpu_percent": cpu,
                        "watts": round(watts, 4),
                    })

                print(f"  {level:4.1f} GB  ->  {statistics.fmean(level_watts):6.2f} W "
                      f"(n={len(level_watts)})")
    finally:
        _allocate(blocks, 0)
        gc.collect()

    return samples


def _ols2(rows: list[dict]) -> dict:
    """
    watts = a + b*cpu_percent + c*ram_used_gb, by normal equations.

    Two predictors, so it is written out rather than pulled from a library:
    the project has no numpy dependency and adding one for six lines of
    arithmetic is not worth it.
    """
    x1 = [r["cpu_percent"] for r in rows]
    x2 = [r["ram_used_gb"] for r in rows]
    y = [r["watts"] for r in rows]
    n = len(rows)

    m1, m2, my = statistics.fmean(x1), statistics.fmean(x2), statistics.fmean(y)
    d1 = [v - m1 for v in x1]
    d2 = [v - m2 for v in x2]
    dy = [v - my for v in y]

    s11 = sum(v * v for v in d1)
    s22 = sum(v * v for v in d2)
    s12 = sum(a * b for a, b in zip(d1, d2))
    s1y = sum(a * b for a, b in zip(d1, dy))
    s2y = sum(a * b for a, b in zip(d2, dy))

    determinant = s11 * s22 - s12 * s12
    if determinant == 0:
        raise RuntimeError("CPU and memory did not vary independently at all.")

    b = (s22 * s1y - s12 * s2y) / determinant
    c = (s11 * s2y - s12 * s1y) / determinant
    a = my - b * m1 - c * m2

    residuals = [yi - (a + b * v1 + c * v2) for yi, v1, v2 in zip(y, x1, x2)]
    sse = sum(r * r for r in residuals)
    sigma2 = sse / (n - 3)

    return {
        "intercept": a,
        "cpu_coef": b,
        "ram_coef": c,
        "ram_se": math.sqrt(sigma2 * s11 / determinant),
        "cpu_se": math.sqrt(sigma2 * s22 / determinant),
        "residual_sd": math.sqrt(sigma2),
        # How badly the two predictors move together. Near +/-1 and the split
        # between them is arbitrary no matter how good the overall fit looks.
        "collinearity": s12 / math.sqrt(s11 * s22),
        "n": n,
    }


def report(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("RESULT")
    print("=" * 78)

    print("  mean power by allocation level:")
    for level in sorted({r["target_extra_gb"] for r in rows}):
        group = [r for r in rows if r["target_extra_gb"] == level]
        watts = [r["watts"] for r in group]
        cpu = statistics.fmean([r["cpu_percent"] for r in group])
        print(f"    +{level:4.1f} GB   {statistics.fmean(watts):6.2f} W  "
              f"(sd {statistics.pstdev(watts):4.2f}, n={len(watts)}, "
              f"mean cpu {cpu:4.1f}%)")

    fit = _ols2(rows)
    low = fit["ram_coef"] - 1.96 * fit["ram_se"]
    high = fit["ram_coef"] + 1.96 * fit["ram_se"]

    print(f"\n  watts = {fit['intercept']:.2f} "
          f"+ {fit['cpu_coef']:.4f} x cpu% "
          f"+ {fit['ram_coef']:.4f} x ram_gb        (n={fit['n']})")
    print(f"    cpu  coefficient  {fit['cpu_coef']:+.4f} +/- {1.96 * fit['cpu_se']:.4f} W per %")
    print(f"    ram  coefficient  {fit['ram_coef']:+.4f} +/- {1.96 * fit['ram_se']:.4f} W per GB")
    print(f"    95% interval for ram: [{low:+.3f}, {high:+.3f}] W/GB")
    print(f"    residual sd {fit['residual_sd']:.2f} W, "
          f"cpu/ram collinearity {fit['collinearity']:+.2f}")

    print("\n  verdict:")
    if low <= 0.375 <= high:
        print("    0.375 W/GB (CodeCarbon) is INSIDE the interval — consistent with this data.")
    else:
        print("    0.375 W/GB (CodeCarbon) is OUTSIDE the interval for memory USED here.")
    if low <= 0 <= high:
        print("    Zero is also inside it: this experiment cannot distinguish the")
        print("    per-GB-used term from no memory effect at all. On the physics")
        print("    (DRAM refresh tracks INSTALLED capacity) that favours folding")
        print("    the term into the constant.")
    else:
        print("    Zero is outside it: memory used does move power on this machine.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure watts per GB of memory used.")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--hold-seconds", type=float, default=20.0)
    parser.add_argument("--max-extra-gb", type=float, default=2.5)
    args = parser.parse_args()

    rows = collect(args.rounds, args.hold_seconds, args.max_extra_gb)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SAMPLES_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n{len(rows)} samples -> {SAMPLES_PATH}")

    report(rows)
    print("\nNothing was written to hardware.db.")


if __name__ == "__main__":
    main()
