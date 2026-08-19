from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Recommendation:
    """
    One thing worth telling the user about.

    Two kinds of rule produce these, and they don't carry the same evidence:

      * Statistical rules (CPU/RAM against a rolling 7-day baseline) know the
        mean and standard deviation that made the current value unusual.
      * Threshold rules (idle waste) have no baseline — "the machine sat idle
        for 40 minutes" is a fact, not a deviation from anything.

    So the baseline fields are Optional rather than required. Storing 0.0 for
    a rule that has no baseline would look like a measured zero instead of an
    absent value, and anything reading these back could not tell the two
    apart.
    """

    metric: str          # e.g. "cpu_usage_percent", "idle_waste"
    message: str
    current_value: float
    triggered_at: datetime
    baseline_mean: Optional[float] = None
    baseline_stdev: Optional[float] = None
