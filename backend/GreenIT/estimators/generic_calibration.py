"""
A usable calibration profile for a machine model nobody has measured yet.

WHY THIS IS NOT A LITERATURE VALUE
Watts-per-CPU-percent looks like the kind of number you could look up, and it
is not. It is not a property of the processor: it depends on the platform's
power management, its cooling, and on what Windows decides to call "100%".
Any published figure is somebody else's regression on somebody else's laptop,
and a worse one than ours because its conditions cannot be inspected.

What DOES transfer is a ratio. On the one machine measured here — an
i5-6300U, a 15 W part — the fitted coefficient is 0.1053 W per CPU percent,
so at 100% CPU the CPU term is 10.5 W, or about 70% of the rated TDP. TDP is
published for every processor, so scaling that ratio gives a defensible
estimate for a part nobody has put on battery yet.

It does not reach 100% of TDP for several ordinary reasons: TDP is a thermal
design rating rather than a power ceiling, "100% CPU" in Windows is not the
most power-hungry instruction mix, and part of the package draw (uncore,
memory controller) is already inside the measured baseline term.

THE HONEST CAVEAT
This ratio rests on ONE anchor point. It could be 0.6 or 0.85 on another
platform and nothing here would know. That is exactly why a profile built by
this module is marked `source="estimated"` and surfaced in the dashboard as
uncalibrated: it is an assumption with a single supporting measurement, not a
result.

It also improves by itself. Once a second machine model is calibrated the
ratio can be checked rather than assumed, and with three it can be fitted —
at which point this module stops being a fallback and becomes the first data
point of the fleet model the deployment plan already implies.
"""

import re
from typing import Optional

from GreenIT.models.calibration import (
    CalibrationProfile,
    CpuCalibration,
    RamCalibration,
)

# Measured: 0.10531828 W/% on a 15 W part => 10.53 W at full load => 0.702.
CPU_POWER_TO_TDP_RATIO = 0.70

# Anchor machine, recorded so the number above is traceable to something.
ANCHOR_MACHINE = "Dell Inc. Latitude 7480 (i5-6300U, 15 W TDP)"

# Generic constant draw: mainboard, chipset, SSD, fans, panel backlight.
# Platform-dependent and not obtainable from any published specification, so
# this one genuinely is a literature-style figure, chosen near the low end of
# the range measured here (baseline + RAM term came to 4.6-6.1 W).
GENERIC_BASELINE_WATTS = 5.0

# Unchanged from the calibrated profile, and for the same reason it was chosen
# there: CodeCarbon's 3 W / 8 GB. Measured on the anchor machine it turned out
# not to vary with memory USED at all, so it behaves as part of the constant —
# but leaving it in place keeps estimated and measured profiles the same shape.
GENERIC_RAM_WATTS_PER_GB = 0.375

# Typical TDP by processor suffix. Suffixes are used rather than a list of
# every part number because they are the manufacturer's own power-class
# marking and they stay valid across generations, so a laptop released next
# year still lands in the right class without anyone updating a table.
_SUFFIX_TDP_WATTS = {
    "Y": 7,     # ultra-low-power fanless
    "U": 15,    # mainstream corporate laptop
    "G7": 15,   # Ice/Tiger Lake with Iris graphics, still 15 W class
    "G4": 15,
    "P": 28,    # performance thin-and-light
    "H": 45,    # mobile workstation
    "HQ": 45,
    "HK": 45,
    "HX": 55,
    "T": 35,    # power-optimised desktop
}

# Most corporate fleets are U-series, so an unrecognised part is far more
# likely to be 15 W than anything else. Guessing high would inflate every
# estimate on exactly the machines we know least about.
DEFAULT_TDP_WATTS = 15

# "i5-6300U", "i7-1185G7", "Ryzen 7 PRO 5850U" -> the trailing letters.
_MODEL_SUFFIX = re.compile(r"\b[a-zA-Z]*\d{3,5}([A-Z]{1,2}\d?)\b")


def tdp_for_cpu(cpu_model: Optional[str]) -> tuple[int, bool]:
    """
    Returns (tdp_watts, recognised).

    `recognised` is reported separately so the caller can tell a real match
    from the default. Both produce a number, but only one of them is evidence.
    """
    if not cpu_model:
        return DEFAULT_TDP_WATTS, False

    match = _MODEL_SUFFIX.search(cpu_model)
    if match is None:
        return DEFAULT_TDP_WATTS, False

    suffix = match.group(1).upper()
    if suffix in _SUFFIX_TDP_WATTS:
        return _SUFFIX_TDP_WATTS[suffix], True

    # A two-character suffix that is not itself known often ends in a known
    # one ("HK" -> "K" is not useful, but "UL" -> "U" is). Try the first
    # letter before giving up.
    if suffix[0] in _SUFFIX_TDP_WATTS:
        return _SUFFIX_TDP_WATTS[suffix[0]], True

    return DEFAULT_TDP_WATTS, False


def estimated_profile(machine_model: str, cpu_model: Optional[str]) -> CalibrationProfile:
    """
    Builds an uncalibrated profile for `machine_model`, scaled from the anchor
    measurement by the processor's thermal design power.
    """
    tdp_watts, recognised = tdp_for_cpu(cpu_model)

    # watts_at_full_load / 100 percent = watts per percent.
    watts_per_percent = CPU_POWER_TO_TDP_RATIO * tdp_watts / 100.0

    detail = f"{tdp_watts} W TDP" if recognised else f"{tdp_watts} W TDP assumed"
    return CalibrationProfile(
        machine_model=machine_model,
        cpu=CpuCalibration(watts_per_percent_usage=watts_per_percent),
        ram=RamCalibration(watts_per_gb_used=GENERIC_RAM_WATTS_PER_GB),
        baseline_watts=GENERIC_BASELINE_WATTS,
        source="estimated",
        notes=(
            f"Uncalibrated. CPU term scaled from {ANCHOR_MACHINE} by "
            f"{detail} ({CPU_POWER_TO_TDP_RATIO:.0%} of TDP at full load). "
            f"Run the calibration sweeps on this model to replace it."
        ),
    )
