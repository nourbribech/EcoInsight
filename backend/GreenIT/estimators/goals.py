"""
A soft weekly goal: "keep avoidable waste under 15% this week".

WHY A GOAL AND NOT JUST THE RATING
The rating grades a trailing 7-day window, which is a gauge - it moves
continuously and is never finished. Nobody can succeed at a gauge. A goal
needs three things the rating deliberately does not have: a target the person
CHOSE, a deadline they can reach, and a verdict when they reach it. Those are
what turn a number into something worth acting on before Friday.

WHY IT GRADES THE SHARE, NOT THE WATT-HOURS
The same argument as rating.py, and it matters more here because a goal is
something you can game. A watt-hour target is met by taking the week off,
which makes the tool an attendance monitor and rewards the one behaviour
nobody wants to encourage. A share cannot be gamed that way: working harder
raises numerator and denominator together, and the only way to move it is to
stop leaving the machine awake with nobody at it.

WHY THE BUDGET IS PROJECTED RATHER THAN MEASURED
"You are at 18%, target 15%" tells you that you are behind but not by how
much, and a percentage is hard to act on. The panel therefore converts the
target into watt-hours of idle time you can still afford this week.

Doing that naively is a trap. Budget = target x energy-so-far grows every
time you use the machine, so you could meet the goal by consuming MORE -
precisely the perverse incentive the share was chosen to avoid. Projecting
the week's total from the pace so far removes it: the projection scales with
usage, so extra consumption raises the budget and the waste in step and moves
the verdict not at all.

The projection is noisy while little of the week has elapsed - on Monday
morning it multiplies a few hours by twelve - so it is withheld until
MINIMUM_ELAPSED_FRACTION of the week has passed. Until then the panel shows
the measured share and says plainly that it is too early to project.

Pure functions. No database, no clock beyond what is passed in.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

SETTING_KEY = "weekly_waste_target"

# 15% - the boundary between "good" and "fair" in rating.py, so a user who
# accepts the default is aiming at the same line the grade already draws.
DEFAULT_TARGET_SHARE = 0.15

# Below 2% the goal is unreachable on any machine that is ever left unlocked
# for a coffee; above 50% it is not a goal. Clamped rather than rejected so a
# hand-edited setting degrades to something sane instead of breaking the page.
MINIMUM_TARGET_SHARE = 0.02
MAXIMUM_TARGET_SHARE = 0.50

# Roughly Tuesday lunchtime. Before this, one bad afternoon dominates the
# projection and the panel would swing between "on track" and "over" for
# reasons that say nothing about the week.
MINIMUM_ELAPSED_FRACTION = 0.20

# At least this many days must carry idle tracking before any verdict. One
# tracked day is a day, not a week.
MINIMUM_TRACKED_DAYS = 2

# How far over target still counts as recoverable rather than missed. A week
# sitting 5% above a 15% target is a bad Tuesday; one at 30% is a habit.
CLOSE_MULTIPLIER = 1.3

WEEK_DAYS = 7


def normalise_target(value) -> float:
    """
    Coerces whatever came out of the settings table into a usable target.

    The store round-trips arbitrary JSON, so this has to survive a string, a
    null, or a percentage somebody typed as 15 instead of 0.15.
    """
    try:
        target = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TARGET_SHARE

    # Accept 15 as well as 0.15. Anything above 1 can only have been meant as
    # a percentage - a share above 1 is not a share.
    if target > 1.0:
        target /= 100.0

    return max(MINIMUM_TARGET_SHARE, min(target, MAXIMUM_TARGET_SHARE))


def week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """
    The calendar week containing `now`, Monday 00:00 to the following Monday.

    Monday-start because that is the convention where this is used, and
    because a week that starts on the day people come back to their desks is
    the one they can actually plan against.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=now.weekday())
    return start, start + timedelta(days=WEEK_DAYS)


@dataclass(frozen=True)
class GoalStatus:
    """
    target_share          what the user is aiming at, 0..1
    share                 measured waste share so far, or None
    state                 "no_data" | "too_early" | "on_track" | "close" | "over"
    headline              one short line for the panel
    detail                the reasoning, including the numbers behind it
    wasted_watt_hours     idle-but-awake energy so far this week
    budget_watt_hours     what the target allows over the PROJECTED full week
    pace_watt_hours       what it allows for the energy used SO FAR
    remaining_watt_hours  week budget minus wasted; negative once overspent
    elapsed_fraction      how much of the week has passed, 0..1
    days_tracked          days this week with idle tracking
    """
    target_share: float
    share: Optional[float]
    state: str
    headline: str
    detail: str
    wasted_watt_hours: Optional[float]
    budget_watt_hours: Optional[float]
    pace_watt_hours: Optional[float]
    remaining_watt_hours: Optional[float]
    elapsed_fraction: float
    days_tracked: int

    def to_dict(self) -> dict:
        return asdict(self)


def _as_idle_time(watt_hours: float, typical_watts: Optional[float]) -> str:
    """
    Restates a watt-hour budget as time the machine could sit idle.

    Watt-hours are the unit the tool measures in and the unit nobody thinks
    in. "About 4 hours of leaving it awake" is the same fact in a form a
    reader can compare against their own Tuesday.
    """
    if not typical_watts or typical_watts <= 0 or watt_hours <= 0:
        return ""

    hours = watt_hours / typical_watts
    if hours < 1:
        return f" - about {hours * 60:.0f} minutes of leaving it awake"

    unit = "hour" if round(hours) == 1 else "hours"
    return f" - about {hours:.0f} {unit} of leaving it awake"


def evaluate(
    target_share: float,
    week: dict,
    now: datetime,
    typical_watts: Optional[float] = None,
) -> GoalStatus:
    """
    `week` is a get_waste_between() result for the current calendar week.
    """
    start, end = week_bounds(now)
    span = (end - start).total_seconds()
    elapsed = max(0.0, min((now - start).total_seconds() / span, 1.0))

    share = week.get("share")
    wasted = week.get("wasted_watt_hours")
    tracked_energy = week.get("tracked_energy_watt_hours")
    days_tracked = week.get("days_tracked") or 0
    percent = f"{target_share * 100:.0f}%"

    if share is None or days_tracked < MINIMUM_TRACKED_DAYS:
        return GoalStatus(
            target_share=target_share,
            share=share,
            state="no_data",
            headline=f"Goal set: keep avoidable waste under {percent}",
            detail=(
                f"Needs {MINIMUM_TRACKED_DAYS} days of idle tracking this week "
                f"before it can say how you are doing - {days_tracked} so far."
            ),
            wasted_watt_hours=wasted,
            budget_watt_hours=None,
            pace_watt_hours=None,
            remaining_watt_hours=None,
            elapsed_fraction=elapsed,
            days_tracked=days_tracked,
        )

    # TWO budgets, because there are two different questions and answering
    # both with one number produced a sign error that shipped for one test
    # run: "About -7 Wh above the week's budget".
    #
    #   pace    what the target allowed for the energy used SO FAR. This is
    #           the one the verdict must be stated against, because `wasted`
    #           is also a to-date figure. wasted - pace is exactly
    #           tracked_energy x (share - target), so it can never disagree
    #           in sign with the band the status was chosen by.
    #
    #   budget  what the target allows over the whole week, projected from
    #           the pace so far. Forward-looking, so it is the right basis
    #           for "how much idle time can I still afford", and only for
    #           that. See the module docstring for why it is projected rather
    #           than taken from energy already used.
    pace = target_share * tracked_energy
    projected_energy = tracked_energy / elapsed if elapsed > 0 else tracked_energy
    budget = target_share * projected_energy
    remaining = budget - wasted
    standing = wasted - pace

    if elapsed < MINIMUM_ELAPSED_FRACTION:
        return GoalStatus(
            target_share=target_share,
            share=share,
            state="too_early",
            headline=f"{share * 100:.0f}% wasted so far, aiming for under {percent}",
            detail=(
                "Too early in the week to project a total - one slow afternoon "
                "still moves this figure a long way. Check back tomorrow."
            ),
            wasted_watt_hours=wasted,
            # Deliberately withheld rather than shown with a caveat: a number
            # on screen gets read and the caveat next to it does not.
            budget_watt_hours=None,
            pace_watt_hours=pace,
            remaining_watt_hours=None,
            elapsed_fraction=elapsed,
            days_tracked=days_tracked,
        )

    def status(state: str, headline: str, detail: str) -> GoalStatus:
        return GoalStatus(
            target_share=target_share,
            share=share,
            state=state,
            headline=headline,
            detail=detail,
            wasted_watt_hours=wasted,
            budget_watt_hours=budget,
            pace_watt_hours=pace,
            remaining_watt_hours=remaining,
            elapsed_fraction=elapsed,
            days_tracked=days_tracked,
        )

    if share <= target_share:
        return status(
            "on_track",
            f"On track - {share * 100:.0f}% wasted against a {percent} goal",
            f"{wasted:.0f} Wh went to an idle, awake machine this week. At this "
            f"pace the week allows {budget:.0f} Wh, so {remaining:.0f} Wh is "
            f"still unspent{_as_idle_time(remaining, typical_watts)}.",
        )

    # How much of the week's forward allowance survives being over pace. Can
    # be positive even in the "over" band - that is the useful case, because
    # it says the week is still winnable and by how little.
    slack = (
        f"{remaining:.0f} Wh of the week's allowance is left"
        if remaining > 0
        else "the whole week's allowance is already spent"
    )

    if share <= target_share * CLOSE_MULTIPLIER:
        return status(
            "close",
            f"Just over - {share * 100:.0f}% against a {percent} goal",
            f"{standing:.0f} Wh above pace"
            f"{_as_idle_time(standing, typical_watts)}, and {slack}. Sleeping "
            f"the machine over lunch for the rest of the week would cover it.",
        )

    return status(
        "over",
        f"Over the goal - {share * 100:.0f}% against {percent}",
        f"{wasted:.0f} Wh went to an idle, awake machine, against the "
        f"{pace:.0f} Wh a {percent} goal allows for the energy used so far - "
        f"{standing:.0f} Wh over{_as_idle_time(standing, typical_watts)}. Now "
        f"{slack}. The 'Fix once' findings below are where this usually "
        f"comes from.",
    )


def verdict(target_share: float, week: dict) -> Optional[dict]:
    """
    The closed verdict on a FINISHED week, for the "last week" line.

    This is what makes it a goal rather than a gauge. Without a week that
    ends, the user never gets to have met anything - and a target that can
    never be satisfied stops being motivating within days.

    Returns None when the finished week carries too little tracking to judge,
    which the panel renders as an absence rather than a pass.
    """
    share = week.get("share")
    if share is None or (week.get("days_tracked") or 0) < MINIMUM_TRACKED_DAYS:
        return None

    return {
        "share": share,
        "met": share <= target_share,
        "wasted_watt_hours": week.get("wasted_watt_hours"),
        "days_tracked": week.get("days_tracked"),
    }
