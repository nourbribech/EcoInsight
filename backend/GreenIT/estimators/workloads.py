"""
Findings about developer workloads left running - today, WSL distributions.

WHAT THIS IS FOR
A distribution left running is the developer's version of a machine left
awake: nothing on the desktop shows it, the only trace on the host is a
process called vmmemWSL, and it can sit there for days. The panel names it,
says how long it has been there, and says what it is actually costing.

THE HONEST PART, WHICH SHAPED THE WHOLE MODULE
An IDLE distribution costs almost nothing in electricity, and this file says
so out loud instead of implying a saving that is not there.

Two measurements force that. First, the CPU: a settled idle VM on this
machine averages 0.0-0.3% of four cores, which at the calibrated slope is
hundredths of a watt. Second, the memory: the RAM sweep run for this project
measured -0.09 +/- 0.22 W/GB, a coefficient statistically indistinguishable
from zero, so 1.3 GB of held memory cannot honestly be converted into watts
at all.

A panel that said "shut down WSL to save power" would therefore be making a
claim this project's own calibration refuses to support. So the module
separates two genuinely different situations:

  BUSY AND UNATTENDED   the VM is burning real CPU with nobody attached - a
                        forgotten build, a container, a runaway process. The
                        watts are real, quantified from the calibration, and
                        this is the finding worth acting on.

  IDLE AND LEFT RUNNING reported as reclaimable MEMORY, with the electricity
                        cost stated as the negligible figure it is.

Distinguishing those two is the insight. Collapsing them would be the lie.

WHAT THE HOST CANNOT SEE
WSL2 runs every running distribution in ONE utility VM, so CPU and memory
describe all of them together. When more than one is running, no figure here
is attributable to a named distribution, and the text says which case it is
in rather than picking a name and hoping.
"""

from typing import Optional

from GreenIT.estimators.config_audit import Finding

# Below this the VM is doing nothing worth calling work. Chosen from
# measurement, not taste: a settled idle Ubuntu-24.04 on the development
# machine sampled 0.00, 0.12, 0.25 and 0.00 percent over four intervals, so
# 1% sits clear of the noise while still catching anything genuinely running.
IDLE_CPU_PERCENT = 1.0

# Long enough that nobody is between two commands. Under an hour this would
# fire on a developer who stepped out for coffee.
STALE_UPTIME_HOURS = 4.0

# Below this there is not enough history to claim a pattern, only a snapshot.
# At the 120s telemetry cadence, 30 samples is an hour.
MINIMUM_SAMPLES = 30

# A finding needs the memory to be worth reclaiming. Under this it is noise
# next to what a browser holds.
NOTABLE_MEMORY_BYTES = 500 * 1024 * 1024

_GB = 1024 ** 3


def _hours(seconds: Optional[float]) -> str:
    if not seconds:
        return "an unknown time"
    hours = seconds / 3600
    if hours < 1:
        return f"{seconds / 60:.0f} minutes"
    if hours < 48:
        return f"{hours:.0f} hours"
    return f"{hours / 24:.1f} days"


def _subject(running: list[str]) -> tuple[str, bool]:
    """
    Names the distribution when exactly one is running, and refuses to when
    more than one is - because the VM's figures then cover all of them and
    attributing them to whichever name came first would be a fabrication.

    Returns the phrase and whether it is plural, because every sentence built
    from it needs a verb. Returning the phrase alone produced "2 distributions
    (Ubuntu-24.04, Debian) has been idle".
    """
    if len(running) == 1:
        return running[0], False
    if len(running) > 1:
        return f"{len(running)} distributions ({', '.join(running)})", True
    return "WSL", False


def assess(
    wsl: dict,
    history: dict,
    watts_per_cpu_percent: Optional[float] = None,
) -> list[Finding]:
    """
    `wsl`      collectors/windows/wsl.collect()
    `history`  database.get_workload_history("wsl", days)
    `watts_per_cpu_percent`
               the calibrated CPU slope, so a busy VM can be priced. None
               leaves the watts out rather than guessing at them.
    """
    if not wsl.get("available"):
        return []

    vm = wsl.get("vm") or {}
    running = wsl.get("running") or []

    if not vm.get("running") or not running:
        return [_not_running(wsl, history)]

    subject, plural = _subject(running)
    cpu = vm.get("cpu_percent")
    memory = vm.get("memory_bytes") or 0
    uptime = vm.get("uptime_seconds")
    attached = vm.get("attached_sessions") or 0

    # A first sample after the agent restarts has no CPU baseline. Saying so
    # beats reporting a 0.0 that would read as "measured, and idle".
    if cpu is None:
        return [Finding(
            key="wsl_running",
            title=f"{subject} {'are' if plural else 'is'} running",
            detail=(
                f"Up for {_hours(uptime)}, holding "
                f"{memory / _GB:.1f} GB. CPU has not been sampled yet - the "
                f"first reading after the agent starts has nothing to compare "
                f"against."
            ),
            action=None,
            fixable="none",
            severity="ok",
        )]

    if cpu >= IDLE_CPU_PERCENT and attached == 0:
        return [_busy_unattended(subject, plural, vm, history, watts_per_cpu_percent)]

    if _is_stale(vm, history, memory, attached):
        return [_idle_left_running(subject, plural, vm, history)]

    return [_in_use(subject, plural, vm, history)]


def _is_stale(vm: dict, history: dict, memory: int, attached: int) -> bool:
    """
    Left running, as opposed to merely running.

    Requires the LIVE sample to be idle and old, and separately requires the
    HISTORY to agree that it has never been busy. Either alone is wrong: a
    live sample cannot tell a forgotten distribution from a developer between
    two builds, and history alone would keep accusing somebody who shut it
    down an hour ago.
    """
    # An attached session is positive evidence that somebody is using it right
    # now, and it outranks every other signal here. Without this the panel
    # told a developer with a shell open that their distro was abandoned and
    # they should run `wsl --shutdown` - advice that would have killed the
    # session they were sitting in.
    #
    # Absence of a session is much weaker evidence the other way, which is why
    # it is not required anywhere: VS Code's Remote-WSL server keeps a distro
    # alive without leaving a wsl.exe on the host.
    if attached > 0:
        return False
    if memory < NOTABLE_MEMORY_BYTES:
        return False
    if (vm.get("uptime_seconds") or 0) < STALE_UPTIME_HOURS * 3600:
        return False

    peak = history.get("peak_cpu_percent")
    if history.get("samples", 0) < MINIMUM_SAMPLES or peak is None:
        # Not enough history to claim a pattern. Fall back to the live sample,
        # which the caller has already established is idle.
        return True

    return peak < IDLE_CPU_PERCENT


def _evidence(history: dict) -> str:
    """The measured record, or an explicit statement that there isn't one."""
    if history.get("samples", 0) < MINIMUM_SAMPLES:
        return ""

    running_hours = history.get("running_hours") or 0
    observed_hours = history.get("observed_hours") or 0
    peak = history.get("peak_cpu_percent")

    sentence = (
        f" Over the last {observed_hours:.0f} hours of monitoring it has been "
        f"up for {running_hours:.0f} of them"
    )
    if peak is not None:
        # "never once above 41% CPU" is not evidence of anything. The
        # never-above phrasing only carries meaning while the ceiling is low.
        sentence += (
            f", never once above {peak:.1f}% CPU"
            if peak < IDLE_CPU_PERCENT
            else f", peaking at {peak:.0f}% CPU"
        )

    unattended = history.get("unattended_hours") or 0
    if unattended > 1:
        sentence += f", and {unattended:.0f} of those with no session attached"

    return sentence + "."


def _idle_left_running(subject: str, plural: bool, vm: dict, history: dict) -> Finding:
    memory = vm.get("memory_bytes") or 0

    return Finding(
        key="wsl_idle",
        title=(
            f"{subject} {'have' if plural else 'has'} been idle for "
            f"{_hours(vm.get('uptime_seconds'))}"
        ),
        detail=(
            f"{'They are' if plural else 'It is'} holding "
            f"{memory / _GB:.1f} GB and doing nothing with it."
            f"{_evidence(history)} "
            # The whole point of the module, stated where the user reads it.
            f"This costs very little electricity - an idle VM draws hundredths "
            f"of a watt of CPU, and the RAM sweep run for this project could "
            f"not distinguish memory power from zero. The memory is what you "
            f"get back."
        ),
        action=(
            "`wsl --shutdown` releases it. The distribution restarts in a "
            "couple of seconds the next time you use it, and nothing on disk "
            "is lost."
        ),
        # Not "high": honest severity for a finding that is about reclaiming
        # memory, not carbon. Inflating it would spend the user's trust on
        # the least important row on the page.
        severity="medium",
        fixable="you",
    )


def _busy_unattended(
    subject: str, plural: bool, vm: dict, history: dict,
    watts_per_cpu_percent: Optional[float],
) -> Finding:
    """
    The one that is genuinely about energy.

    Real CPU, nobody attached: a build that never finished, a container
    nobody stopped, a process in a loop. Unlike the idle case these watts are
    measured and worth naming.
    """
    cpu = vm.get("cpu_percent") or 0.0
    cost = ""
    if watts_per_cpu_percent:
        watts = cpu * watts_per_cpu_percent
        cost = (
            f" At this machine's calibration that is about {watts:.1f} W, "
            f"or {watts * 24 / 1000:.2f} kWh if it runs for a day."
        )

    return Finding(
        key="wsl_busy_unattended",
        title=(
            f"{subject} {'are' if plural else 'is'} using {cpu:.0f}% CPU "
            f"with nobody attached"
        ),
        detail=(
            f"No shell or editor is connected to it, yet something inside is "
            f"working - a build that never finished, a container left up, or a "
            f"process in a loop.{cost}{_evidence(history)}"
        ),
        action=(
            "`wsl -d <name> -- top -bn1` shows what is running inside. "
            "`wsl --shutdown` stops all of it."
        ),
        severity="high",
        fixable="you",
    )


def _in_use(subject: str, plural: bool, vm: dict, history: dict) -> Finding:
    """
    Running and legitimately in use. Reported as "ok" rather than omitted:
    a panel that shows nothing when WSL is running teaches its user that the
    panel is broken, and silence is the one message that can never be
    checked.
    """
    attached = vm.get("attached_sessions") or 0
    memory = vm.get("memory_bytes") or 0

    return Finding(
        key="wsl_in_use",
        # "in use" is a claim, and only an attached session supports it.
        # Without one this is the honest fallback - running, not yet old
        # enough or quiet enough to call abandoned - so it says only that.
        title=(
            f"{subject} {'are' if plural else 'is'} "
            f"{'in use' if attached else 'running'}"
        ),
        detail=(
            f"Up {_hours(vm.get('uptime_seconds'))}, "
            f"{vm.get('cpu_percent') or 0:.1f}% CPU, {memory / _GB:.1f} GB held"
            + (f", {attached} session{'s' if attached != 1 else ''} attached"
               if attached else "")
            + f".{_evidence(history)}"
        ),
        action=None,
        fixable="none",
        severity="ok",
    )


def _not_running(wsl: dict, history: dict) -> Finding:
    installed = wsl.get("installed") or []
    running_hours = history.get("running_hours") or 0

    detail = f"{', '.join(installed)} installed, none running." if installed else \
        "WSL is installed with no distributions."

    if history.get("samples", 0) >= MINIMUM_SAMPLES and running_hours > 0:
        detail += (
            f" It has been up {running_hours:.0f} of the last "
            f"{history.get('observed_hours', 0):.0f} monitored hours."
        )

    return Finding(
        key="wsl_stopped",
        title="No WSL distribution is running",
        detail=detail + " Nothing to reclaim.",
        action=None,
        fixable="none",
        severity="ok",
    )


def samples_from(wsl: dict) -> list[dict]:
    """
    Flattens a collector reading into rows for database.save_workload_samples.

    One row per INSTALLED distribution, not per running one. A stopped distro
    has to be recorded as stopped, because "running 6 of the last 24 hours"
    needs the hours it was down as much as the hours it was up - and a table
    that only ever holds running rows can only ever conclude "always on".

    The VM's figures are attached to whichever distributions are running, and
    are therefore shared rather than per-distro. Aggregates over this table
    treat them as a property of the VM, which is what they are.
    """
    if not wsl.get("available"):
        return []

    vm = wsl.get("vm") or {}
    running = set(wsl.get("running") or [])

    return [
        {
            "kind": "wsl",
            "name": name,
            "running": name in running,
            "cpu_percent": vm.get("cpu_percent") if name in running else None,
            "memory_bytes": vm.get("memory_bytes") if name in running else None,
            "uptime_seconds": vm.get("uptime_seconds") if name in running else None,
            "attached_sessions": vm.get("attached_sessions") if name in running else None,
        }
        for name in (wsl.get("installed") or [])
    ]
