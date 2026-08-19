"""
Shared helpers for calibration scripts. Reads real total-system power
from the laptop's own battery discharge rate (no admin rights needed,
no external hardware) and provides a simple line-fitting utility.

Must be running unplugged — raises if AC power is connected.
"""

import statistics
import time

import psutil
import wmi


_connection = None


def _wmi_connection():
    """
    One WMI connection per process, reused.

    Building a wmi.WMI() object is expensive — it negotiates COM and walks the
    namespace, costing tens of milliseconds of CPU. Doing that once per
    reading was measurable work happening *during* a power measurement, so the
    act of sampling raised the number being sampled. Caching removes the
    instrument from its own reading.
    """
    global _connection
    if _connection is None:
        # Calibration scripts run on the main thread, where Python has already
        # initialised COM. The agent, which does not, calls CoInitialize
        # itself — see agent.py.
        _connection = wmi.WMI(namespace="root\\wmi")
    return _connection


def read_discharge_watts() -> float:
    """Current total system power draw (W), from the battery's fuel gauge."""
    battery = _wmi_connection().BatteryStatus()[0]
    if battery.PowerOnline:
        raise RuntimeError("Laptop is plugged in — unplug it before calibrating.")
    return battery.DischargeRate / 1000.0  # mW -> W


def check_battery_in_safe_range(min_percent: int = 30, max_percent: int = 100) -> None:
    """
    Raises if battery charge is outside a safe calibration range.

    Below ~20%, Windows battery-saver can throttle CPU frequency and
    suspend background apps, silently changing the CPU's actual power
    behavior mid-sweep. Fuel-gauge readings also tend to get noisier
    right at the extremes of the charge curve. Staying in the 30-80%
    middle avoids both.
    """
    battery = psutil.sensors_battery()
    if battery is None:
        raise RuntimeError("Could not read battery percentage.")
    if not (min_percent <= battery.percent <= max_percent):
        raise RuntimeError(
            f"Battery at {battery.percent:.0f}% — charge to within "
            f"{min_percent}-{max_percent}% before calibrating."
        )


def sample_average_watts(duration_seconds: float = 5.0, interval_seconds: float = 1.0) -> float:
    """Averages several readings over a window to smooth sensor noise."""
    readings = []
    sample_count = max(1, int(duration_seconds / interval_seconds))
    for _ in range(sample_count):
        readings.append(read_discharge_watts())
        time.sleep(interval_seconds)
    return statistics.mean(readings)


def fit_line(x_values: list, y_values: list) -> tuple:
    """Ordinary least squares: y = intercept + slope * x. Also returns R²
    so a bad/noisy fit is visible rather than silently trusted."""
    mean_x = statistics.mean(x_values)
    mean_y = statistics.mean(y_values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denominator = sum((x - mean_x) ** 2 for x in x_values)
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x

    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(x_values, y_values))
    ss_tot = sum((y - mean_y) ** 2 for y in y_values)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return intercept, slope, r_squared