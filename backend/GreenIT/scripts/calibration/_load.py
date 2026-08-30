"""
CPU load worker for the automated calibration sweep.

Deliberately a module of its own, importing nothing but `time`.

multiprocessing on Windows uses `spawn`, so every child process re-imports
the module that defines its target function. Pointing that at the calibration
module would make each worker import psutil and the WMI/COM stack — real CPU
work happening at precisely the moment CPU is being measured, and charged to
the level being sampled. Keeping the worker here makes a child cost almost
nothing to start.
"""

import time


def burn(duty: float, stop_at: float) -> None:
    """
    Occupy `duty` (0..1) of one core until `stop_at` (a time.time() stamp).

    Duty cycling rather than a plain busy-loop: a busy-loop can only produce
    0% or 100%, and the sweep needs the levels in between. The period is short
    enough that Windows' scheduler averages it into a steady load, and long
    enough that the sleep/wake overhead stays negligible against the work.
    """
    period = 0.05
    busy = period * duty
    idle = period - busy

    while time.time() < stop_at:
        start = time.perf_counter()
        while time.perf_counter() - start < busy:
            pass
        if idle > 0:
            time.sleep(idle)
