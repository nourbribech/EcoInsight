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

    Gaps: the process survives laptop suspend, so `timestamp` can jump by
    hours between two consecutive calls. Integrating across such a gap
    attributes the machine's *awake* power draw to a period it spent
    asleep — see MAX_INTERVAL_SECONDS below.
    """

    # Any interval longer than this is treated as a discontinuity rather
    # than a measurement.
    #
    # Without this guard, resuming from a 38-hour suspend produced a single
    # tick worth 641 Wh — more than a normal week of real use — because the
    # estimator multiplied "16.8 W right now" by 38 hours of unmeasured
    # sleep. Across the existing history, six such ticks accounted for 78%
    # of all recorded energy.
    #
    # 60s is chosen from the observed tick distribution, which is sharply
    # bimodal: p99.9 of real intervals is 5.5s, and the next tier up is
    # 4.6 HOURS. Nothing legitimate falls between, so this sits ~10x above
    # normal jitter and still catches every genuine discontinuity.
    #
    # We drop the interval instead of clamping it. Clamping would invent a
    # plausible-looking 60s of consumption for a period we have no data
    # about; a suspended machine draws almost nothing anyway, so attributing
    # zero is both simpler and closer to the truth.
    MAX_INTERVAL_SECONDS = 60.0

    def __init__(self, max_interval_seconds: float = MAX_INTERVAL_SECONDS):
        self._previous_timestamp: Optional[datetime] = None
        self._cumulative_watt_hours: float = 0.0
        self._max_interval_seconds = max_interval_seconds

    def estimate(self, power_estimate: PowerEstimate, timestamp: datetime) -> Optional[EnergyEstimate]:
        if self._previous_timestamp is None:
            self._previous_timestamp = timestamp
            return None

        elapsed_seconds = (timestamp - self._previous_timestamp).total_seconds()

        if elapsed_seconds > self._max_interval_seconds:
            # Re-anchor and skip this tick, exactly like the first call.
            # The caller already handles a None return as "nothing to report
            # yet", so no special case is needed downstream.
            self._previous_timestamp = timestamp
            return None

        elapsed_hours = elapsed_seconds / 3600
        interval_watt_hours = power_estimate.total_watts * elapsed_hours
        self._cumulative_watt_hours += interval_watt_hours
        self._previous_timestamp = timestamp

        return EnergyEstimate(
            interval_watt_hours=interval_watt_hours,
            cumulative_watt_hours=self._cumulative_watt_hours,
        )