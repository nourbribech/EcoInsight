from dataclasses import dataclass


@dataclass(frozen=True)
class PowerEstimate:
    """
    Structured output of the Power Estimator: a per-component watt
    breakdown, not just a single total.

    total_watts is a computed property rather than a stored field so it's
    impossible to construct an inconsistent instance where the components
    don't actually sum to the total.

    The breakdown matters beyond the total itself: the Recommendation
    Engine needs to say which component is driving consumption, and later
    the Energy Estimator could choose to integrate components separately
    (e.g. "disk activity cost you X Wh this week") without any change to
    this object's shape.
    """

    cpu_watts: float
    ram_watts: float
    baseline_watts: float

    @property
    def total_watts(self) -> float:
        return self.cpu_watts + self.ram_watts + self.baseline_watts