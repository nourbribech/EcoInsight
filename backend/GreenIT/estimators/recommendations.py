import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from GreenIT.database import database
from GreenIT.models.recommendation import Recommendation
from GreenIT.models.snapshot import SystemMetricsSnapshot
from GreenIT.estimators.carbon import TUNISIA_GRID_CARBON_INTENSITY_KG_PER_KWH
from GreenIT.estimators.recommendation_messages import (
    compose_elevated,
    compose_idle,
    compose_unattended,
    find_cpu_culprit,
    find_memory_culprit,
)

PROJECTION_HOURS = 1

MINIMUM_DATA_WINDOW_DAYS = 3
BASELINE_LOOKBACK_DAYS = 7
REMINDER_INTERVAL_HOURS = 1.5  # midpoint of "an hour or two"

# --- what counts as worth telling the user about -------------------------
#
# Replayed against six days of this machine's own telemetry, the old rule
# (mean + 1.5 stdev, fired on a single sample) would have sent 21.5
# notifications a day. Every part of the replacement below was chosen from
# that replay, not from taste.

# A percentile of the machine's own recent history, not a Gaussian tail.
# CPU usage is right-skewed and bimodal (idle vs working), so "mean + k
# stdev" describes a distribution that does not exist -- 1.5 stdev landed
# near the 88th percentile, which is a strange way to spell "p88".
#
# p90 rather than p95 because this metric saturates: measured here, p95 = 97%
# and p98 = 100%. Past p90 the threshold approaches the ceiling and the rule
# degenerates into "only fires when pinned". Volume is controlled by
# persistence below, which is a far stronger lever, so the threshold is free
# to stay at a level that still means something.
BASELINE_PERCENTILE = 90

# The condition must hold across this many consecutive samples. At the 120s
# telemetry cadence, 5 samples is 10 minutes.
#
# This is what actually made the difference: at p90, requiring 3 consecutive
# samples cut CPU notifications from 15.5/day to 2.8, and 5 took it to 0.7.
# Changing the threshold alone could not -- a rolling percentile fires on
# ~(100-N)% of samples by construction, on any machine.
#
# It also repairs the message. "If this continues for an hour" was being
# projected from one 2-minute sample; from six sustained minutes it is a
# defensible thing to say.
#
# WHY 3 AND NOT 5. It was 5, tuned on a six-day replay, and that over-corrected
# badly: on a later day the longest run of above-threshold samples was 3, so
# NOTHING fired for over 24 hours. An empty recommendations panel is a worse
# failure than a noisy one — it looks broken, and it teaches the user the
# feature does nothing. 3 samples gives ~2.8/day on the same replay, which is
# the target, while still refusing to fire on a single 2-minute spike.
CONSECUTIVE_SAMPLES_REQUIRED = 3

# Two samples four hours apart are not consecutive -- the machine was asleep
# in between. A run has to mean elapsed continuity, not adjacency in a list,
# or suspend/resume manufactures fake sustained episodes. 2.5x the telemetry
# cadence tolerates a slow tick without tolerating a gap.
MAX_SAMPLE_GAP_SECONDS = 300

# "Unusual for you" is not the same as "worth interrupting you". On a machine
# that idles at 5%, p90 might be 20% -- statistically unusual, and nobody's
# problem. The gate is expressed in the tool's own unit rather than as an
# arbitrary CPU percentage: how much MORE power is being drawn than this
# machine normally draws, projected over the notice window.
MINIMUM_IMPACT_WATT_HOURS = 5.0

# Idle-waste rule. 15 minutes is the usual default for a display/sleep
# timeout, so a machine still awake past it is past the point where anyone
# expected it to be drawing full power.
IDLE_THRESHOLD_SECONDS = 15 * 60
IDLE_REMINDER_INTERVAL_HOURS = 2.0

# Idle AND busy. Either alone is ordinary -- a machine at 60% CPU is working,
# a machine at 8 W with nobody there was left on. Together they mean a job is
# running unattended, which is a different situation with a different answer,
# so the message switches framing rather than reporting "idle" and losing the
# most interesting half of the fact.
UNATTENDED_CPU_PERCENT = 30.0

# `label` opens a sentence, `resource` sits inside one ("most of your CPU").
# Kept together so adding a third watched metric is one entry, not a grep for
# every place its name is spelled out.
WATCHED_METRICS = {
    "cpu_usage_percent": {"label": "CPU usage", "resource": "CPU"},
    "ram_usage_percent": {"label": "Memory usage", "resource": "memory"},
}


def _percentile(values: list[float], percentile: int) -> float:
    """The same cut points the offline replay used, so the measured firing
    rates carry over to the running agent."""
    if len(values) < 2:
        return max(values, default=0.0)
    return statistics.quantiles(values, n=100)[percentile - 1]


@dataclass
class _Baseline:
    """What this machine normally does, and where "unusual" starts."""
    mean: float       # shown to the user as "your usual X%"
    stdev: float      # stored on the row; no longer used to trigger
    threshold: float  # BASELINE_PERCENTILE of recent history


@dataclass
class _ElevatedState:
    is_elevated: bool = False
    last_notified_at: Optional[datetime] = None
    elevated_since: Optional[datetime] = None
    # How many consecutive qualifying samples have been seen, and when the
    # last one arrived -- needed to tell a genuine run from two samples with
    # a suspend in between.
    run_length: int = 0
    last_sample_at: Optional[datetime] = None


class RecommendationEngine:
    def __init__(self):
        self._state: dict[str, _ElevatedState] = {
            metric: _ElevatedState() for metric in WATCHED_METRICS
        }
        self._idle_state = _ElevatedState()
        self._restore_state()

    def _restore_state(self) -> None:
        """
        Picks up where the last run left off.

        Without this, restarting the agent re-announces every condition it had
        already reported -- and the agent is meant to start at log-on, so that
        is not a rare event.

        Only recommendations newer than one reminder interval are restored.
        Anything older is not evidence of an ongoing episode, and a fresh
        first notice is the correct behaviour there.
        """
        cutoff = datetime.now() - timedelta(hours=REMINDER_INTERVAL_HOURS)
        try:
            recent = database.get_latest_recommendation_per_metric(cutoff)
        except Exception:
            # A missing or half-migrated table must not stop the agent from
            # starting. Losing the restore costs one duplicate notification;
            # failing here costs all collection.
            return

        for metric, row in recent.items():
            state = self._state.get(metric) if metric in self._state else (
                self._idle_state
                if metric in ("idle_waste", "unattended_activity")
                else None
            )
            if state is None:
                continue

            notified_at = datetime.fromisoformat(row["timestamp"])
            state.is_elevated = True
            state.last_notified_at = notified_at
            # The true onset is at or before the last notification, so this
            # under-reports how long the episode has run and how much it has
            # cost. Erring toward under-claiming is the right direction for a
            # measurement tool; the alternative invents history.
            state.elevated_since = notified_at

    def _get_baseline(self, metric: str, before: datetime) -> Optional[_Baseline]:
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
        return _Baseline(
            mean=mean,
            stdev=variance ** 0.5,
            threshold=_percentile(values, BASELINE_PERCENTILE),
        )

    def _typical_power_watts(self) -> Optional[float]:
        """
        What this machine usually draws, from the measurements table.

        Measured rather than modelled: the impact gate asks "is the machine
        drawing meaningfully more than normal", and the honest answer to that
        is in the recorded watts, not in a coefficient.
        """
        connection = database.get_connection()
        cursor = connection.cursor()
        cutoff = (datetime.now() - timedelta(days=BASELINE_LOOKBACK_DAYS)).isoformat()
        row = cursor.execute(
            "SELECT AVG(total_watts) FROM measurements WHERE timestamp >= ?",
            (cutoff,),
        ).fetchone()
        connection.close()
        return row[0]

    def _is_worth_reporting(self, power_watts: float) -> bool:
        """
        Whether the excess draw is large enough to be worth an interruption.

        Returns True when the baseline is unknown, so a fresh install is not
        silently muted -- the statistical rule already refuses to fire
        without history, which is the gate that matters there.
        """
        typical = self._typical_power_watts()
        if typical is None:
            return True
        excess_watt_hours = (power_watts - typical) * PROJECTION_HOURS
        return excess_watt_hours >= MINIMUM_IMPACT_WATT_HOURS

    def _project_impact(self, power_watts: float) -> tuple[float, float]:
        """Returns (projected_wh, projected_g_co2eq) if elevated usage persists for PROJECTION_HOURS."""
        projected_wh = power_watts * PROJECTION_HOURS
        projected_kg = (projected_wh / 1000) * TUNISIA_GRID_CARBON_INTENSITY_KG_PER_KWH
        return projected_wh, projected_kg * 1000  # kg -> g

    def _accumulated_impact(self, since: datetime, until: datetime) -> tuple[float, float]:
        """Actual Wh/gCO2eq incurred between `since` and `until`, from real measurements."""
        connection = database.get_connection()
        cursor = connection.cursor()
        row = cursor.execute(
            "SELECT SUM(interval_watt_hours), SUM(interval_kg_co2eq) "
            "FROM measurements WHERE timestamp >= ? AND timestamp < ?",
            (since.isoformat(), until.isoformat()),
        ).fetchone()
        connection.close()
        wh = row[0] or 0.0
        kg = row[1] or 0.0
        return wh, kg * 1000

    def _share_of_day(self, watt_hours: float, at: datetime) -> Optional[float]:
        """
        This figure as a fraction of everything the machine used that day.

        The unit problem, solved with data already on disk: nobody knows what
        14 Wh is, but everybody understands "a quarter of today". Returns None
        when the day's total is missing or smaller than the figure itself,
        which happens around midnight and on the first day of collection --
        better to drop the clause than to print "180% of today".
        """
        if watt_hours <= 0:
            return None

        connection = database.get_connection()
        cursor = connection.cursor()
        row = cursor.execute(
            "SELECT SUM(interval_watt_hours) FROM measurements "
            "WHERE timestamp >= ? AND timestamp < ?",
            (at.strftime("%Y-%m-%dT00:00:00"), at.isoformat()),
        ).fetchone()
        connection.close()

        total = row[0]
        if not total or total < watt_hours:
            return None
        return watt_hours / total

    def _has_enough_history(self) -> bool:
        connection = database.get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT MIN(timestamp) FROM telemetry_history")
        earliest = cursor.fetchone()[0]
        connection.close()

        if earliest is None:
            return False
        return (datetime.now() - datetime.fromisoformat(earliest)) >= timedelta(days=MINIMUM_DATA_WINDOW_DAYS)

    def _evaluate_idle(
            self,
            snapshot: SystemMetricsSnapshot,
            power_watts: float,
            processes: list[dict],
            total_cpu_percent: float,
    ) -> Optional[Recommendation]:
        """
        Flags a machine left awake and drawing full power with nobody using it.

        This is the one rule that needs no history at all. The statistical
        rules ask "is this unusual for you?", which is unanswerable until
        there are days of baseline. "Nobody has touched this machine for 40
        minutes and it is still pulling 10 W" is a fact about right now, so
        it works from the first minute the agent runs.

        The idle START time comes free from GetLastInputInfo — idle_seconds
        counts back to the last keypress — so there is no need to track it
        across ticks and no risk of losing it when the agent restarts.

        The wasted energy is read from the measurements table rather than
        projected from current power, so it reflects what the machine
        actually drew. Since the energy estimator now drops suspend gaps,
        time asleep is correctly excluded: a laptop that idled 15 minutes and
        then slept for 8 hours is charged for the 15 minutes only.
        """
        idle_seconds = snapshot.idle_seconds
        if idle_seconds is None:
            return None

        state = self._idle_state

        if idle_seconds < IDLE_THRESHOLD_SECONDS:
            # Someone is using the machine. Reset silently — coming back to
            # your desk is not an event worth a notification.
            state.is_elevated = False
            state.elevated_since = None
            state.last_notified_at = None
            return None

        idle_since = snapshot.timestamp - timedelta(seconds=idle_seconds)

        should_notify = False
        is_first_notice = False
        if not state.is_elevated:
            should_notify = True
            is_first_notice = True
            state.elevated_since = idle_since
        elif state.last_notified_at is not None:
            elapsed = snapshot.timestamp - state.last_notified_at
            should_notify = elapsed >= timedelta(hours=IDLE_REMINDER_INTERVAL_HOURS)

        state.is_elevated = True
        if not should_notify:
            return None

        wasted_wh, wasted_g = self._accumulated_impact(
            state.elevated_since or idle_since, snapshot.timestamp
        )

        share = self._share_of_day(wasted_wh, snapshot.timestamp)
        culprit = find_cpu_culprit(processes, total_cpu_percent)

        # One state machine, two framings. "Left on" and "running a job
        # unattended" are the same detection -- nobody at the keyboard -- but
        # opposite advice, so the wording forks here rather than the rule.
        is_unattended_work = (
            culprit is not None
            and snapshot.cpu.usage_percent >= UNATTENDED_CPU_PERCENT
        )

        if is_unattended_work:
            metric = "unattended_activity"
            message = compose_unattended(
                idle_seconds=idle_seconds,
                cpu_percent=snapshot.cpu.usage_percent,
                culprit=culprit,
                watt_hours=wasted_wh,
                grams=wasted_g,
                is_first_notice=is_first_notice,
                share_of_day=share,
            )
        else:
            metric = "idle_waste"
            message = compose_idle(
                idle_seconds=idle_seconds,
                power_watts=power_watts,
                watt_hours=wasted_wh,
                grams=wasted_g,
                sleep_timer_minutes=IDLE_THRESHOLD_SECONDS // 60,
                is_first_notice=is_first_notice,
                culprit=culprit,
                share_of_day=share,
            )

        state.last_notified_at = snapshot.timestamp

        return Recommendation(
            metric=metric,
            message=message,
            current_value=wasted_wh,
            triggered_at=snapshot.timestamp,
        )

    def evaluate(
            self,
            snapshot: SystemMetricsSnapshot,
            power_watts: float,
            processes: Optional[list[dict]] = None,
            total_cpu_percent: float = 0.0,
    ) -> list[Recommendation]:
        """
        `processes` is the attributed per-application sample taken on the same
        tick, and is what lets a message name a cause. Optional with a default
        so the engine still works without it -- the messages simply fall back
        to their aggregate wording, which is exactly what they do anyway when
        no single process dominates. That keeps the two failure modes
        identical rather than adding a separate broken path.
        """
        recommendations = []
        processes = processes or []

        # Runs before the history gate on purpose: it is a threshold rule and
        # needs no baseline, so it works on a machine that installed the
        # agent an hour ago.
        idle_recommendation = self._evaluate_idle(
            snapshot, power_watts, processes, total_cpu_percent
        )
        if idle_recommendation is not None:
            recommendations.append(idle_recommendation)

        if not self._has_enough_history():
            return recommendations

        current_values = {
            "cpu_usage_percent": snapshot.cpu.usage_percent,
            "ram_usage_percent": snapshot.memory.usage_percent,
        }

        # Each metric asks a different question of the process list: "which
        # app is burning CPU" and "which app is holding memory" are not the
        # same app, so the culprit is resolved per metric rather than once.
        # One query per tick, not one per metric: the answer does not depend
        # on which metric is being evaluated.
        worth_reporting = self._is_worth_reporting(power_watts)

        culprits = {
            "cpu_usage_percent": lambda: find_cpu_culprit(processes, total_cpu_percent),
            "ram_usage_percent": lambda: find_memory_culprit(
                processes, snapshot.memory.total_bytes
            ),
        }

        for metric, wording in WATCHED_METRICS.items():
            baseline = self._get_baseline(metric,before=snapshot.timestamp)
            if baseline is None:
                continue

            current = current_values[metric]
            state = self._state[metric]

            # A run means the condition held CONTINUOUSLY. A gap in sampling
            # breaks it: we cannot claim persistence across a period we did
            # not observe, and a suspend would otherwise glue two unrelated
            # spikes into one "sustained" episode.
            if (
                    state.last_sample_at is not None
                    and (snapshot.timestamp - state.last_sample_at).total_seconds()
                    > MAX_SAMPLE_GAP_SECONDS
            ):
                state.run_length = 0
            state.last_sample_at = snapshot.timestamp

            over_threshold = current >= baseline.threshold
            state.run_length = state.run_length + 1 if over_threshold else 0

            # The EPISODE is defined by the run alone. The impact gate is
            # applied further down, as a veto on speaking rather than as part
            # of this condition.
            #
            # Folding the gate in here was the first version, and replaying it
            # showed why it is wrong: power hovering around the gate makes
            # is_elevated flicker, which tears one continuous episode into a
            # dozen, each re-announcing itself as a first notice. Measured on
            # six days of real data it made RAM notifications go UP, 2.3/day
            # to 5.7/day -- a gate that increases the noise it was added to
            # reduce.
            is_elevated = state.run_length >= CONSECUTIVE_SAMPLES_REQUIRED
            mean, stdev = baseline.mean, baseline.stdev

            should_notify = False
            is_first_notice = False

            if is_elevated and not state.is_elevated:
                # First crossing into elevated — always notify.
                should_notify = True
                is_first_notice = True
                state.elevated_since = snapshot.timestamp

            elif is_elevated and state.is_elevated:
                if state.last_notified_at is None:
                    # The episode started but the impact gate silenced the
                    # first notice. It is still owed: if the draw later rises
                    # past the gate, the user should get the opening message,
                    # not a reminder about something never mentioned.
                    should_notify = True
                    is_first_notice = True
                else:
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

            # The veto. Placed after the state machine so that a silenced
            # episode stays ONE episode: state.is_elevated still tracks the
            # run, and only the speaking is suppressed.
            if should_notify and not worth_reporting:
                should_notify = False

            culprit = culprits[metric]()

            # If we cannot say WHAT is responsible, we have nothing worth
            # saying. The alternative was "spread across several applications
            # with no single one responsible", which is a statistic wearing a
            # recommendation's clothes -- it names no cause, offers no action,
            # and was what filled the feed.
            if should_notify and culprit is None:
                should_notify = False

            if should_notify:
                if is_first_notice:
                    wh, g_co2eq = self._project_impact(power_watts)
                    elapsed_seconds = 0.0
                else:
                    wh, g_co2eq = self._accumulated_impact(state.elevated_since, snapshot.timestamp)
                    elapsed_seconds = (
                        snapshot.timestamp - state.elevated_since
                    ).total_seconds()

                message = compose_elevated(
                    metric_label=wording["label"],
                    resource=wording["resource"],
                    current=current,
                    baseline_mean=mean,
                    watt_hours=wh,
                    grams=g_co2eq,
                    is_first_notice=is_first_notice,
                    culprit=culprit,
                    elapsed_seconds=elapsed_seconds,
                    share_of_day=(
                        None if is_first_notice
                        else self._share_of_day(wh, snapshot.timestamp)
                    ),
                )

                recommendations.append(
                    Recommendation(
                        metric=metric, message=message, current_value=current,
                        baseline_mean=mean, baseline_stdev=stdev,
                        triggered_at=snapshot.timestamp,
                    )
                )
                state.last_notified_at = snapshot.timestamp

            state.is_elevated = is_elevated
            if not is_elevated:
                state.last_notified_at = None
                state.elevated_since = None

        return recommendations