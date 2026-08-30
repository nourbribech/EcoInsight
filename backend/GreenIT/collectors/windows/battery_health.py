"""
How much of the battery's original capacity is left.

Every other collector here measures a flow — watts, bytes per second, percent
busy. This one measures wear, and it matters for a different reason: battery
degradation is the most common trigger for replacing a laptop that otherwise
works, and replacing a laptop costs far more carbon than running one ever
does. A tool that only counts electricity is looking at the small number.

Read from the root\\wmi namespace rather than Win32_Battery, because
Win32_Battery reports DesignCapacity and FullChargeCapacity as None on most
modern machines — verified here, both null — while BatteryStaticData and
BatteryFullChargedCapacity return real figures. Neither needs elevation.

Units are milliwatt-hours in both classes, so the ratio is dimensionless and
no conversion is involved.
"""

import wmi

# Below this the battery is generally considered worn enough that runtime is
# noticeably short — the point where users start asking for a replacement.
# Not a hardware threshold, just where the conversation usually starts.
POOR_HEALTH_PERCENT = 60
FAIR_HEALTH_PERCENT = 80


def collect() -> dict:
    """
    Returns design/full capacity in mWh and health as a percentage, or
    available=False when the machine has no battery or will not report it.

    `available` is separate from a zero or missing number for the same reason
    it is elsewhere in this project: a desktop with no battery and a battery
    that failed to answer are different facts, and neither is "0% health".
    """
    try:
        connection = wmi.WMI(namespace="root\\wmi")
        design = connection.BatteryStaticData()[0].DesignedCapacity
        full_charge = connection.BatteryFullChargedCapacity()[0].FullChargedCapacity
    except Exception:
        # Desktops, VMs, machines whose firmware does not expose the class,
        # and any WMI hiccup all land here. None of them should stop the
        # agent, so the failure is reported rather than raised.
        return {"available": False, "design_mwh": None,
                "full_charge_mwh": None, "health_percent": None}

    if not design or not full_charge:
        return {"available": False, "design_mwh": design,
                "full_charge_mwh": full_charge, "health_percent": None}

    return {
        "available": True,
        "design_mwh": design,
        "full_charge_mwh": full_charge,
        # Can exceed 100 on a new battery, since manufacturers rate design
        # capacity conservatively. Left uncapped: clamping would hide a
        # perfectly good reading behind a rounder-looking one.
        "health_percent": 100.0 * full_charge / design,
    }
