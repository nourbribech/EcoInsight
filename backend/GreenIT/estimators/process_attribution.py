"""
Splits the machine's CPU power between the processes responsible for it.
"""


def attribute_cpu_watts(
        processes: list[dict],
        total_cpu_percent: float,
        cpu_watts: float,
) -> list[dict]:
    """
    Returns the processes with an `estimated_watts` field added.

    Each process gets the share of cpu_watts matching its share of total CPU
    activity. Working in SHARES rather than applying the calibration
    coefficient to each process directly is deliberate: psutil's per-process
    percentages are normalised per core and generally do not add up to the
    system-wide figure the power model was calibrated against. Shares divide
    that discrepancy out, so the attributed watts always sum to the CPU power
    actually estimated.

    WHAT THIS DELIBERATELY DOES NOT DO
    Only CPU power is attributed. Baseline power belongs to no process — the
    motherboard draws it whether anything is running or not — and the RAM
    term is known to be standing in for display and chipset draw rather than
    genuine per-process memory cost, so splitting it by RSS would attach a
    confident-looking number to something the model cannot actually see.

    A pure function of its arguments, like the other estimators: no psutil,
    no database, no clock.
    """
    if total_cpu_percent <= 0:
        # Everything idle. Shares are undefined, and zero is the honest answer.
        return [{**process, "estimated_watts": 0.0} for process in processes]

    return [
        {
            **process,
            "estimated_watts": cpu_watts * (process["cpu_percent"] / total_cpu_percent),
        }
        for process in processes
    ]
