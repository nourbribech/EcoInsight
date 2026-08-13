from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import before

from GreenIT.database import database
from GreenIT.models.recommendation import Recommendation
from GreenIT.models.snapshot import SystemMetricsSnapshot

MINIMUM_DATA_WINDOW_DAYS = 3
BASELINE_LOOKBACK_DAYS = 7
STDEV_THRESHOLD = 1.5
REMINDER_INTERVAL_HOURS = 1.5  # midpoint of "an hour or two"

WATCHED_METRICS = {
    "cpu_usage_percent": "CPU usage",
    "ram_usage_percent": "RAM usage",
}


@dataclass
class _ElevatedState:
    is_elevated: bool = False
    last_notified_at: Optional[datetime] = None


class RecommendationEngine:
    def __init__(self):
        self._state: dict[str, _ElevatedState] = {
            metric: _ElevatedState() for metric in WATCHED_METRICS
        }

    def _get_baseline(self, metric: str) -> Optional[tuple[float, float]]:
        connection = database.get_connection()
        cursor = connection.cursor()
        cutoff = (datetime.now() - timedelta(days=BASELINE_LOOKBACK_DAYS)).isoformat()

        rows = cursor.execute(
            f"SELECT {metric} FROM telemetry_history WHERE timestamp >= ? AND timestamp < ?",
            (cutoff, before.isoformat()),
        ).fetchall()
        connection.close()

        values = [row[0] for row in rows if row[0] is not None]
        if len(values) < 2:
            return None

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return mean, variance ** 0.5

    def _has_enough_history(self) -> bool:
        connection = database.get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT MIN(timestamp) FROM telemetry_history")
        earliest = cursor.fetchone()[0]
        connection.close()

        if earliest is None:
            return False
        return (datetime.now() - datetime.fromisoformat(earliest)) >= timedelta(days=MINIMUM_DATA_WINDOW_DAYS)

    def evaluate(self, snapshot: SystemMetricsSnapshot) -> list[Recommendation]:
        if not self._has_enough_history():
            return []

        recommendations = []
        current_values = {
            "cpu_usage_percent": snapshot.cpu.usage_percent,
            "ram_usage_percent": snapshot.memory.usage_percent,
        }

        for metric, label in WATCHED_METRICS.items():
            baseline = self._get_baseline(metric,before=snapshot.timestamp)
            if baseline is None:
                continue

            mean, stdev = baseline
            current = current_values[metric]
            is_elevated = stdev > 0 and (current - mean) / stdev >= STDEV_THRESHOLD
            state = self._state[metric]

            should_notify = False

            if is_elevated and not state.is_elevated:
                # First crossing into elevated — always notify.
                should_notify = True

            elif is_elevated and state.is_elevated:
                # Still elevated — only remind if enough time has passed
                # since the last notification (implying the earlier
                # suggestion wasn't acted on, or the condition persists).
                elapsed = snapshot.timestamp - state.last_notified_at
                if elapsed >= timedelta(hours=REMINDER_INTERVAL_HOURS):
                    should_notify = True

            elif not is_elevated and state.is_elevated:
                # Dropped back to normal — implicitly "resolved", whether
                # by user action or on its own. Reset silently, no message.
                pass

            if should_notify:
                message = (
                    f"{label} is unusually high right now "
                    f"({current:.1f} vs your typical {mean:.1f})"
                    if state.last_notified_at is None
                    else (
                        f"{label} is still elevated "
                        f"({current:.1f} vs your typical {mean:.1f}) — "
                        f"reminder, this has persisted"
                    )
                )
                recommendations.append(
                    Recommendation(
                        metric=metric,
                        message=message,
                        current_value=current,
                        baseline_mean=mean,
                        baseline_stdev=stdev,
                        triggered_at=snapshot.timestamp,
                    )
                )
                state.last_notified_at = snapshot.timestamp

            state.is_elevated = is_elevated
            if not is_elevated:
                state.last_notified_at = None

        return recommendations