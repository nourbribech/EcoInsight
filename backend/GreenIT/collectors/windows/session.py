"""
collectors/windows/session.py

Collect user session metrics.

Current metrics:
    - Idle time (seconds)

Future metrics:
    - Session locked
    - Active user
    - Screen saver state
"""

import ctypes
from ctypes import wintypes


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def get_idle_time() -> float:
    """
    Return the number of seconds since the last user input
    (keyboard or mouse).

    Returns:
        float: Idle time in seconds.
    """

    last_input = LASTINPUTINFO()
    last_input.cbSize = ctypes.sizeof(LASTINPUTINFO)

    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input))

    milliseconds = (
        ctypes.windll.kernel32.GetTickCount()
        - last_input.dwTime
    )

    return round(milliseconds / 1000, 2)


def is_session_locked():
    """
    Placeholder for future implementation.

    Returns:
        None
    """
    return None


def collect() -> dict:
    """
    Collect session-related metrics.

    Returns:
        dict: Session metrics.
    """

    return {
        "idle_time_seconds": get_idle_time(),
        "locked": is_session_locked(),
    }