"""
Standing findings about how the machine is CONFIGURED, as opposed to alerts
about what it is doing right now.

WHY THIS EXISTS AS A SEPARATE IDEA
The recommendation engine detects events: a spike, an idle stretch, a job
left running. Events are episodic by nature, so the panel is empty whenever
nothing is happening — and measured on this machine, "nothing is happening"
was over 24 hours straight. A panel that is usually blank teaches its user
that the feature does nothing.

Configuration findings have the opposite shape. They are always available,
they are true until someone changes a setting, and fixing one saves power
every day afterwards rather than once. For a tool whose purpose is helping an
employee waste less, "your display never turns off" is worth more than any
number of notifications about a busy CPU.

WHY `fixable` MATTERS MORE THAN SEVERITY
On a company-managed machine some settings belong to the user and some belong
to IT. Telling someone to change a policy their administrator has locked is
the fastest way to make a tool feel stupid and be ignored, so every finding
declares who can act on it. A finding nobody can act on is not a
recommendation, it is a complaint.

Pure functions: settings and observations in, findings out. No powercfg, no
database, no clock.
"""

from dataclasses import dataclass, asdict
from typing import Optional

# Thresholds. Deliberately generous — the aim is to flag policies that are
# clearly wasteful, not to nag someone whose display sleeps at 12 minutes
# instead of 10.
DISPLAY_OFF_MAX_MINUTES = 15
SLEEP_MAX_MINUTES = 30
HIGH_BRIGHTNESS_PERCENT = 80

# A display is a large share of a laptop's draw, but this project has never
# measured its own panel (see the brightness item in PROJECT.md). This is a
# deliberately round, conservative figure used ONLY to say "roughly this
# much" — it is labelled as an estimate everywhere it surfaces.
DISPLAY_WATTS_ESTIMATE = 3.0

NEVER = 0  # Windows encodes "never time out" as a zero timeout.


@dataclass(frozen=True)
class Finding:
    """
    key       stable identifier, so the UI can track dismissal later
    title     one short line
    detail    the reasoning, including any measured evidence
    action    what to actually do, or None when nobody can act
    fixable   "you" | "it" | "none" — who is able to change this
    severity  "high" | "medium" | "ok"
    """
    key: str
    title: str
    detail: str
    action: Optional[str]
    fixable: str
    severity: str

    def to_dict(self) -> dict:
        return asdict(self)


def _minutes(seconds: Optional[int]) -> Optional[int]:
    return None if seconds is None else seconds // 60


def _describe(seconds: Optional[int]) -> str:
    if seconds is None:
        return "unknown"
    if seconds == NEVER:
        return "never"
    return f"{seconds // 60} min"


def audit(settings: dict, observed: dict) -> list[Finding]:
    """
    settings  as returned by collectors/windows/power_settings.collect()
    observed  {"idle_awake_minutes_per_day": float|None,
               "idle_awake_watt_hours": float|None,
               "brightness_percent": int|None,
               "typical_watts": float|None}
    """
    findings: list[Finding] = []

    findings += _sleep_findings(settings, observed)
    findings += _display_findings(settings, observed)
    findings += _brightness_findings(observed)

    # Silence is ambiguous — it could mean "all good" or "this feature is
    # broken". Saying so explicitly is the difference, and it costs one row.
    if not any(f.severity != "ok" for f in findings):
        findings.append(Finding(
            key="all_clear",
            title="Power settings look sensible",
            detail=(
                f"Display turns off after {_describe(settings.get('display_off', {}).get('ac'))} "
                f"and the machine sleeps after {_describe(settings.get('sleep', {}).get('ac'))} "
                f"on mains power."
            ),
            action=None,
            fixable="none",
            severity="ok",
        ))

    return findings


# Task names that describe waking or updating are both the likeliest culprits
# and the only ones a reader can interpret. Everything else keeps its order.
_TELLING_WAKE_WORDS = ("wake", "update", "scan", "backup", "sync")


def _rank_wake_tasks(names: list[str]) -> list[str]:
    """
    Puts the informative task names first.

    Windows returns these alphabetically, which on this machine led with
    ".NET Framework NGEN v4.0.30319 64 Critical" and pushed
    "WakeUpAndScanForUpdates" out of the three shown. The list was accurate
    and the message was useless: only one of those names tells a reader
    anything, and it was the one that got cut.
    """
    def rank(name: str) -> int:
        lowered = name.lower()
        return 0 if any(word in lowered for word in _TELLING_WAKE_WORDS) else 1

    # Stable sort, so within each group Windows' own ordering survives.
    return sorted(names, key=rank)


def _sleep_findings(settings: dict, observed: dict) -> list[Finding]:
    sleep = settings.get("sleep", {})
    ac_seconds = sleep.get("ac")
    if ac_seconds is None:
        return []

    idle_minutes = observed.get("idle_awake_minutes_per_day")
    wasted_wh = observed.get("idle_awake_watt_hours")

    if ac_seconds == NEVER:
        return [Finding(
            key="sleep_never",
            title="This machine never sleeps on mains power",
            detail=(
                "Sleep is set to never while plugged in, so the machine keeps "
                "drawing power through every lunch break, evening and weekend."
            ),
            action="Set sleep to 30 minutes or less in Windows power settings.",
            fixable="you",
            severity="high",
        )]

    if ac_seconds // 60 > SLEEP_MAX_MINUTES:
        return [Finding(
            key="sleep_late",
            title=f"Sleep is set to {ac_seconds // 60} minutes",
            detail=(
                f"Anything above {SLEEP_MAX_MINUTES} minutes means a long wait "
                f"before an unattended machine stops drawing full power."
            ),
            action=f"Reduce it to {SLEEP_MAX_MINUTES} minutes or less.",
            fixable="you",
            severity="medium",
        )]

    # THE INTERESTING ONE: the policy says sleep, the machine did not.
    #
    # This is the only finding here that could not be produced by reading
    # settings alone — it needs the measurement to contradict the
    # configuration. Something is holding the machine awake (a scheduled task,
    # a management agent, a held power request), and on a company-managed
    # machine that is almost never the employee's doing.
    if idle_minutes and idle_minutes > (ac_seconds // 60) * 2:
        evidence = f"{idle_minutes:.0f} minutes a day"
        if wasted_wh:
            evidence += f" ({wasted_wh:.0f} Wh)"

        # Name the suspects when Windows will tell us who they are. A finding
        # that says "something is blocking sleep" is a shrug; one that says
        # "WakeUpAndScanForUpdates is allowed to wake this machine" is a lead
        # the user or their admin can actually follow.
        wake_tasks = _rank_wake_tasks(observed.get("wake_tasks") or [])
        if wake_tasks:
            shown = ", ".join(wake_tasks[:3])
            more = f" and {len(wake_tasks) - 3} more" if len(wake_tasks) > 3 else ""
            cause = (
                f" {len(wake_tasks)} scheduled task"
                f"{'s are' if len(wake_tasks) != 1 else ' is'} allowed to wake "
                f"this machine, including {shown}{more}."
            )
            action = (
                "Ask IT to disable wake timers for this power plan, or to "
                "reschedule those tasks for working hours."
            )
        else:
            cause = (
                " Something is preventing it from sleeping — often a management "
                "agent, a scheduled task or a held power request."
            )
            action = (
                "Ask IT to check what is blocking sleep — "
                "`powercfg /requests` run as administrator names it."
            )

        return [Finding(
            key="sleep_blocked",
            title="Configured to sleep, but staying awake anyway",
            detail=(
                f"Sleep is set to {ac_seconds // 60} minutes, yet this machine "
                f"has averaged {evidence} idle with nobody using it.{cause}"
            ),
            action=action,
            # Deliberately not "you": on a managed fleet this is a policy
            # problem, and sending the employee to fix it wastes their time.
            fixable="it",
            severity="high",
        )]

    return []


def _display_findings(settings: dict, observed: dict) -> list[Finding]:
    display = settings.get("display_off", {})
    ac_seconds = display.get("ac")
    if ac_seconds is None:
        return []

    if ac_seconds == NEVER:
        return [Finding(
            key="display_never",
            title="The screen never turns off by itself",
            detail=(
                "The display is one of the largest single consumers on a "
                "laptop, and it is set to stay on indefinitely while plugged in."
            ),
            action="Set the display to turn off after 10 minutes.",
            fixable="you",
            severity="high",
        )]

    if ac_seconds // 60 > DISPLAY_OFF_MAX_MINUTES:
        return [Finding(
            key="display_late",
            title=f"Screen stays on for {ac_seconds // 60} minutes when idle",
            detail=(
                "Every minute the panel stays lit for an empty chair is "
                "avoidable, and it is the easiest setting on the machine to fix."
            ),
            action=f"Reduce it to {DISPLAY_OFF_MAX_MINUTES} minutes or less.",
            fixable="you",
            severity="medium",
        )]

    return []


def _brightness_findings(observed: dict) -> list[Finding]:
    brightness = observed.get("brightness_percent")
    if brightness is None or brightness < HIGH_BRIGHTNESS_PERCENT:
        return []

    return [Finding(
        key="brightness_high",
        title=f"Screen brightness is at {brightness}%",
        detail=(
            f"Panel power scales with backlight level. Dropping to 70% is "
            f"usually unnoticeable indoors and saves roughly "
            f"{DISPLAY_WATTS_ESTIMATE * 0.3:.1f} W while the screen is on — "
            f"an estimate, since this build does not measure the panel directly."
        ),
        action="Lower the brightness a few steps.",
        fixable="you",
        severity="medium",
    )]
