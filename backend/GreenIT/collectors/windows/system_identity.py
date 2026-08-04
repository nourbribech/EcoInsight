import wmi


def collect() -> dict:
    """
    Read raw machine identity fields from WMI.

    Like the other collectors, this returns a raw dict with no
    interpretation — it does not know or care how the values will be
    used downstream. Combining these fields into a lookup key is a
    Service-layer concern (see services/hardware_service.py), not a
    collector concern.
    """
    c = wmi.WMI()
    system = c.Win32_ComputerSystem()[0]

    return {
        "manufacturer": system.Manufacturer,
        "model": system.Model,
    }


def build_machine_key(identity: dict) -> str:
    """
    Combines raw machine identity into the single string used as the
    hardware.db lookup key.

    This is the one place that logic lives. Both the runtime
    hardware_service and the offline calibration scripts must use this
    same function — if they built the key differently, calibration data
    written by one path could silently fail to match lookups from the
    other.
    """
    return f"{identity['manufacturer']} {identity['model']}"