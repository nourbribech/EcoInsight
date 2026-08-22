"""
WSL distributions, and what the utility VM behind them costs the host.

WHY THIS IS WORTH COLLECTING
A distribution left running is the developer version of a machine left awake:
nobody is using it, it is holding memory, and nothing about the desktop makes
it visible. The only sign on the host is a process called vmmemWSL, which
tells the user nothing.

WHAT THE HOST CAN AND CANNOT SEE
WSL2 runs EVERY running distribution inside ONE utility VM, so the host sees
a single vmmemWSL process for all of them. Per-distribution CPU and memory
cannot be recovered from the host at all - the numbers here describe the VM
as a whole, and are only attributable to a named distribution when exactly
one is running. Everything downstream is written to say so rather than
implying a precision the platform does not offer.

WHY `--quiet` AND NOT `--verbose`
`wsl --list --verbose` prints a table whose headers and STATE values are
localised - on the French Windows this project is developed on it would have
to match "Arrêté" rather than "Stopped". That is the same trap that already
broke the powercfg parser and the scheduled-task status report twice.

`wsl --list --quiet` prints distribution NAMES and nothing else, and
`wsl --list --running --quiet` prints only the running ones. Membership of
the second list IS the state, so no localised word is ever parsed. Names are
not translated.

The output is UTF-16LE with CRLF line endings and no BOM - decoding it as
UTF-8 yields text interleaved with NUL bytes that still "succeeds", which is
exactly how the requirements.txt corruption in this repo went unnoticed.
"""

import subprocess
from typing import Optional

import psutil

# The utility VM. Named vmmemWSL on current Windows builds; older ones and
# Hyper-V guests use a bare "vmmem", so both are accepted.
_VM_PROCESS_NAMES = ("vmmemwsl", "vmmem")

# One of these exists per attached interactive session. Their absence is the
# strongest available evidence that nobody is actually using the distro.
_SESSION_PROCESS_NAMES = ("wsl",)

# Docker Desktop installs its own distributions and runs containers inside
# this same VM. Worth naming, because it changes who the advice is for.
_DOCKER_DISTRO_NAMES = ("docker-desktop", "docker-desktop-data")

_TIMEOUT_SECONDS = 15

# psutil.Process.cpu_percent(interval=None) reports the average since the
# PREVIOUS call ON THE SAME OBJECT. Caching the object across calls therefore
# yields CPU averaged over the whole gap between collections - for the
# estimation loop, a genuine 120-second average rather than the instantaneous
# blip a fresh object plus a short sleep would give.
#
# The first call on a new object has no baseline and returns a meaningless
# 0.0, which is reported as None. A fabricated zero would read as "measured,
# and it was idle" - the one conclusion this module exists to draw.
_cpu_probes: dict[int, psutil.Process] = {}


def _run(arguments: list[str]) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["wsl.exe", *arguments],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        # FileNotFoundError here is the ordinary case on a machine without
        # WSL, not an error worth logging.
        return None

    if completed.returncode != 0:
        return None

    return completed.stdout.decode("utf-16-le", errors="replace")


def _names(output: Optional[str]) -> list[str]:
    if not output:
        return []
    # NULs can survive a mis-decode of a truncated final character; stripping
    # them costs nothing and prevents a name that renders as "U\x00buntu".
    return [
        line.strip().replace("\x00", "")
        for line in output.splitlines()
        if line.strip()
    ]


def _vm_process() -> Optional[psutil.Process]:
    for process in psutil.process_iter(["pid", "name"]):
        name = (process.info["name"] or "").lower().removesuffix(".exe")
        if name in _VM_PROCESS_NAMES:
            return process
    return None


def _attached_sessions() -> int:
    count = 0
    for process in psutil.process_iter(["name"]):
        name = (process.info["name"] or "").lower().removesuffix(".exe")
        if name in _SESSION_PROCESS_NAMES:
            count += 1
    return count


def collect() -> dict:
    """
    Returns
    -------
    {"available": bool,          WSL is installed and answered
     "installed": [names],
     "running":   [names],
     "docker": bool,             Docker Desktop's distros are present
     "vm": {"running": bool,
            "pid": int|None,
            "cpu_percent": float|None,     host CPU, normalised over cores
            "memory_bytes": int|None,
            "uptime_seconds": float|None,
            "attached_sessions": int}}

    `available` false means the question could not be asked - no WSL, or the
    command failed - which is not the same as "no distributions", and callers
    must not render it as such.
    """
    installed = _names(_run(["--list", "--quiet"]))
    if not installed:
        return {
            "available": False,
            "installed": [],
            "running": [],
            "docker": False,
            "vm": _no_vm(),
        }

    running = _names(_run(["--list", "--running", "--quiet"]))

    return {
        "available": True,
        # Docker's own distributions are filtered out of the user-facing
        # lists: "docker-desktop is running" is not advice anybody can act on,
        # and it would appear on every developer machine forever.
        "installed": [n for n in installed if n.lower() not in _DOCKER_DISTRO_NAMES],
        "running": [n for n in running if n.lower() not in _DOCKER_DISTRO_NAMES],
        "docker": any(n.lower() in _DOCKER_DISTRO_NAMES for n in installed),
        "vm": _vm_usage(),
    }


def _no_vm() -> dict:
    return {
        "running": False,
        "pid": None,
        "cpu_percent": None,
        "memory_bytes": None,
        "uptime_seconds": None,
        "attached_sessions": 0,
    }


def _vm_usage() -> dict:
    process = _vm_process()
    if process is None:
        _cpu_probes.clear()
        return _no_vm()

    # A restarted VM gets a new pid, and CPU measured against a dead process's
    # baseline would be nonsense. Keying the cache on the pid makes the first
    # sample after a restart correctly report None instead.
    probe = _cpu_probes.get(process.pid)
    first_sample = probe is None
    if first_sample:
        probe = process
        _cpu_probes.clear()
        _cpu_probes[process.pid] = probe

    cores = psutil.cpu_count() or 1

    try:
        # Normalised over cores, matching every other CPU figure in this
        # project: psutil reports 400% for four saturated cores.
        raw = probe.cpu_percent(None)
        cpu_percent = None if first_sample else raw / cores
        memory_bytes = probe.memory_info().rss
        uptime_seconds = max(0.0, psutil.time.time() - probe.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # vmmemWSL itself is readable without elevation on the machines tested;
        # the sibling wslhost.exe processes are not. Catching here keeps a
        # tightened build from turning a missing figure into a crashed loop.
        _cpu_probes.pop(process.pid, None)
        return _no_vm()

    return {
        "running": True,
        "pid": process.pid,
        "cpu_percent": cpu_percent,
        "memory_bytes": memory_bytes,
        "uptime_seconds": uptime_seconds,
        "attached_sessions": _attached_sessions(),
    }


if __name__ == "__main__":
    import json
    import time

    # Called twice on purpose: the first CPU figure is always None by design.
    collect()
    time.sleep(3)
    print(json.dumps(collect(), indent=2))
