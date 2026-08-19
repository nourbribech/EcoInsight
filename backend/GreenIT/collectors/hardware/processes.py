"""
Per-process CPU and memory sampling.

Like every other collector this returns raw readings and does no estimation —
turning a CPU share into watts is the attribution estimator's job.

THE STATEFULNESS THAT ISN'T HERE
psutil.Process.cpu_percent() reports usage since the PREVIOUS call for that
same process object, so it needs two readings to say anything. psutil keeps
an internal cache of Process instances keyed by (pid, create_time) and
process_iter() reuses it, which means successive calls to collect() measure
across the real interval between them without this module holding any state
of its own.

The consequence is the same one MetricsPollingService has: the FIRST call
after startup has nothing to compare against and reports 0.0 for everything.
Callers should prime it once and discard that result.
"""

import psutil

# Windows' "System Idle Process" (PID 0) is not a process that consumes CPU —
# it is the accounting fiction Windows uses to represent CPU that is doing
# NOTHING. It reports roughly (100 x core count) minus real usage, so on an
# idle machine it dominates the list.
#
# It has to be excluded from the denominator as well as the output, not just
# hidden from the UI. Left in the total it silently deflates every real
# process's share: with idle at 100% of a 335% total, a process using 63%
# would be credited with 19% of CPU power instead of its true 27%.
_EXCLUDED_PIDS = {0}
_EXCLUDED_NAMES = {"System Idle Process"}


def collect(limit: int = 10) -> dict:
    """
    Returns the `limit` busiest APPLICATIONS (processes grouped by
    executable name) plus the total CPU across all of them.

    The total is measured over every process, not just the ones returned,
    because it is the denominator for attribution — computing shares against
    only the top 10 would inflate each of them by whatever the long tail was
    using.
    """
    # Keyed by executable name: modern browsers and editors spread their work
    # over dozens of child processes, so a flat list shows "chrome.exe" eight
    # times at 15% each instead of once at 120%. Grouping answers the question
    # the user is actually asking — which APPLICATION is costing me power —
    # rather than which OS process object.
    grouped: dict[str, dict] = {}
    total_cpu_percent = 0.0

    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = process.info
            name = info.get("name") or "?"
            if info.get("pid") in _EXCLUDED_PIDS or name in _EXCLUDED_NAMES:
                continue

            # interval=None: percent since the last call, non-blocking.
            # Passing a number here would sleep, once per process.
            cpu_percent = process.cpu_percent(None)
            memory_info = info.get("memory_info")

            total_cpu_percent += cpu_percent

            entry = grouped.get(name)
            if entry is None:
                entry = {"name": name, "cpu_percent": 0.0,
                         "memory_bytes": 0, "instances": 0}
                grouped[name] = entry

            entry["cpu_percent"] += cpu_percent
            # RSS double-counts memory shared between a program's own child
            # processes, so this over-states a browser's true footprint. Kept
            # because the relative ranking stays useful and the alternative
            # (USS) costs a per-process syscall each.
            entry["memory_bytes"] += memory_info.rss if memory_info else 0
            entry["instances"] += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Processes die mid-iteration constantly, and some system ones are
            # unreadable without elevation. Both are normal; skip them.
            continue

    processes = sorted(
        grouped.values(), key=lambda item: item["cpu_percent"], reverse=True
    )

    return {
        "processes": processes[:limit],
        "total_cpu_percent": total_cpu_percent,
    }
