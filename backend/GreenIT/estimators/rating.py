"""
A tier for the period: how much of this machine's energy was avoidable.

WHAT IS BEING GRADED, AND WHY IT IS NOT CONSUMPTION
Grading total watt-hours would grade how much somebody worked and how much
they were at their desk. The best score would go to whoever was on leave,
which makes the tool an attendance monitor and rewards absence — the same
trap a consumption leaderboard falls into.

The waste SHARE has none of that. It is a ratio, so a heavy user and a light
user can both score 3%; working more does not hurt you, and leaving the
machine awake through lunch does. It is also the only part of the figure the
person can actually change, which is the test any score has to pass before it
is fair to show anybody.

WHERE THE BANDS COME FROM
They are editorial, and this file says so rather than implying a standard
that does not exist. Nobody has published a "percentage of laptop energy
spent idle-but-awake" distribution, and one machine cannot produce one. The
boundaries below are round numbers chosen so that the top band means "there
is essentially nothing to recover here" and the bottom means "a sleep timer
would pay for itself immediately".

Once a fleet is reporting, these should be replaced by percentiles of the
real distribution — at which point "you are in the best quarter of your
building" replaces a judgement with a measurement. The shape of this module
does not change when that happens; only the thresholds do.

WHY IT REFUSES TO RATE SOMETIMES
Idle tracking has to have been running long enough for the share to mean
anything. Grading a machine on two days, one of which the agent was
restarted repeatedly, produces a confident letter over noise. Returning None
and saying "not enough data yet" is the honest output, and the dashboard
renders it as such.
"""

from dataclasses import dataclass, asdict
from typing import Optional

# Minimum days of idle tracking before a tier is shown at all.
MINIMUM_DAYS_TRACKED = 5

# Upper bound of each band, as a share of total energy spent idle-but-awake.
# Ordered best to worst; the last entry is the catch-all.
_BANDS = (
    (0.05, "excellent", "Almost nothing wasted",
     "Under a twentieth of this machine's energy went to an empty chair."),
    (0.15, "good", "Little waste",
     "Most of what this machine drew was while somebody was using it."),
    (0.30, "fair", "Worth a look",
     "A noticeable share went to a machine nobody was at."),
    (1.01, "poor", "Significant waste",
     "Close to a third or more went to an idle, awake machine."),
)


@dataclass(frozen=True)
class Rating:
    """
    tier     machine-readable band name, for styling
    label    short human phrase
    detail   one sentence of reasoning
    share    the waste share it was computed from, 0..1
    next_tier_share
             the share this machine would have to reach for the next band
             up, or None when already in the best one. Turns a static grade
             into something with a direction.
    """
    tier: str
    label: str
    detail: str
    share: float
    next_tier_share: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def rate_waste(share: Optional[float], days_tracked: int) -> Optional[Rating]:
    """
    `share`         idle-but-awake energy / total energy, 0..1
    `days_tracked`  days on which idle was actually recorded

    Returns None when there is not enough evidence to judge.
    """
    if share is None or days_tracked < MINIMUM_DAYS_TRACKED:
        return None

    share = max(0.0, min(share, 1.0))

    previous_bound: Optional[float] = None
    for bound, tier, label, detail in _BANDS:
        if share < bound:
            return Rating(
                tier=tier,
                label=label,
                detail=detail,
                share=share,
                # The target is the bound of the band ABOVE this one, which is
                # the lower bound of the current band.
                next_tier_share=previous_bound,
            )
        previous_bound = bound

    # Unreachable: the final band's bound is above 1.0 and share is clamped.
    return None
