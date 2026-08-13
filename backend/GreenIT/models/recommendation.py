from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Recommendation:
    metric: str          # e.g. "cpu_usage_percent"
    message: str
    current_value: float
    baseline_mean: float
    baseline_stdev: float
    triggered_at: datetime