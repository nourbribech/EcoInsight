from datetime import datetime
from typing import Optional

from GreenIT.models.power_estimate import PowerEstimate
from GreenIT.models.energy_estimate import EnergyEstimate


class EnergyEstimator:
    """
    Integrates PowerEstimate.total_watts over time into energy (Wh).

    Energy = Power x time, so this needs to know how much time elapsed
    since the previous estimate() call — the same "hold state, diff
    against a prior reading" pattern MetricsPollingService uses for disk
    throughput. Same consequence: the first call has no previous
    timestamp to diff against, so it returns None — callers should skip
    that tick, exactly like poll()'s first call.

    Holds the running cumulative total for the life of this instance
    (one instance per app session). Persisting that total across app
    restarts, if ever needed, is a history.db / database-layer concern,
    not this estimator's.
    """

    def __init__(self):
        self._previous_timestamp: Optional[datetime] = None
        self._cumulative_watt_hours: float = 0.0

    def estimate(self, power_estimate: PowerEstimate, timestamp: datetime) -> Optional[EnergyEstimate]:
        if self._previous_timestamp is None:
            self._previous_timestamp = timestamp
            return None

        elapsed_hours = (timestamp - self._previous_timestamp).total_seconds() / 3600
        interval_watt_hours = power_estimate.total_watts * elapsed_hours
        self._cumulative_watt_hours += interval_watt_hours
        self._previous_timestamp = timestamp

        return EnergyEstimate(
            interval_watt_hours=interval_watt_hours,
            cumulative_watt_hours=self._cumulative_watt_hours,
        )