"""
Scheduled tasks that are allowed to WAKE the machine.

This is the missing half of the most useful finding the agent makes. The
config audit can already spot the contradiction — "sleep is set to 15 minutes,
yet this machine averaged 48 idle minutes a day" — but until now it could only
shrug and say ask IT. A wake timer is the usual culprit, and Windows will name
them without any elevation at all.

WHY NOT powercfg /waketimers
That is the obvious command and it returns nothing useful here: it requires
administrator rights, exits 1 for a normal user, and only lists timers that
are armed at this instant rather than the tasks capable of arming them.
Get-ScheduledTask reads the task store, needs no elevation, and answers the
question actually being asked — what is *allowed* to wake this machine.

COST
About 3 seconds. PowerShell start-up dominates, and the task store is large.
Far too slow to sit on a request path, so the caller is expected to cache it
for a long time; the answer only changes when software is installed or a
policy is pushed. See _cached() in api.py.
"""

import subprocess

# -NoProfile skips the user's PowerShell profile, which can add seconds and
# arbitrary side effects. -NonInteractive guarantees it can never sit waiting
# for input in a process with no console attached.
_COMMAND = [
    "powershell", "-NoProfile", "-NonInteractive", "-Command",
    # State 3 is Disabled. A disabled task cannot wake anything, so including
    # it would inflate the count with tasks that are already switched off.
    "Get-ScheduledTask | Where-Object { $_.Settings.WakeToRun -and $_.State -ne 3 } "
    "| Select-Object -ExpandProperty TaskName",
]

_TIMEOUT_SECONDS = 20


def collect() -> dict:
    """
    Returns {"wake_tasks": [names], "available": bool}.

    `available` distinguishes "asked and there are none" from "could not ask" —
    the first means the machine has no wake timers, the second means we know
    nothing. Reporting both as an empty list would let the audit conclude
    there is no wake timer on a machine where the query simply failed.
    """
    try:
        completed = subprocess.run(
            _COMMAND,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return {"wake_tasks": [], "available": False}

    if completed.returncode != 0:
        return {"wake_tasks": [], "available": False}

    text = completed.stdout.decode("utf-8", errors="replace")
    names = [line.strip() for line in text.splitlines() if line.strip()]
    return {"wake_tasks": names, "available": True}
