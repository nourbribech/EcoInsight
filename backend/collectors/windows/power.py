"""
    - Battery information
    - AC power status
    - Active Windows power plan
"""

import subprocess
import psutil


def get_battery():
    """
    Retrieve battery information.

    Returns:
        dict | None
    """

    battery = psutil.sensors_battery()

    return battery._asdict() if battery else None


def is_on_ac_power():
    """
    Return whether the machine is plugged into AC power.

    Returns:
        bool | None
    """

    battery = psutil.sensors_battery()

    if battery is None:
        return None

    return battery.power_plugged


def get_power_plan():
    """
    Retrieve the currently active Windows power plan.

    Returns:
        str | None
    """

    try:
        result = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            check=True,
        )

        output = result.stdout.strip()

        # Example:
        # Power Scheme GUID: xxx (Balanced)

        if "(" in output and ")" in output:
            return output.split("(")[1].split(")")[0]

    except Exception:
        pass

    return None


def collect():

    return {
        "battery": get_battery(),
        "ac_power": is_on_ac_power(),
        "power_plan": get_power_plan(),
    }