"""
Turns detected facts into the sentence a person actually reads.

Split out of recommendations.py so that detection ("is this unusual?") and
wording ("how do I say it?") can change independently -- and so the wording
is testable on its own, with fabricated facts, without a database or a week
of telemetry behind it.

WHY THIS IS NOT A LANGUAGE MODEL
Two of the requirements here are absolute rather than stylistic: the energy
figure must be the measured one, and no cause may be named unless one process
genuinely dominates. Both are guarantees a template makes by construction and
a generative model can only be asked for. The intelligence in these messages
is not the phrasing -- it is knowing that MsMpEng is an antivirus that
finishes on its own, which lives in process_catalog.py and was written by a
human who can be held to it.

Every function here is pure: facts in, string out. No clock, no database.
"""

from dataclasses import dataclass
from typing import Optional

from GreenIT.estimators.process_catalog import ProcessInfo, info_for

# A process is "the cause" only if it holds at least this share of the
# resource AND is at least this many times the size of the runner-up. Both
# conditions are needed: 45% is not a cause when the second process holds
# 40%, and being 3x the runner-up means nothing when everything is small.
#
# This is the rule that keeps the messages honest. Without it the top row of
# a sorted list always looks like a culprit, and the tool starts inventing
# blame for ordinary load spread across a dozen programs.
DOMINANCE_SHARE = 0.40
DOMINANCE_RATIO = 1.5


@dataclass(frozen=True)
class Culprit:
    """The one process responsible, when there is one."""
    info: ProcessInfo
    share: float   # 0..1 of the resource
    detail: str    # human-readable size, e.g. "61% of the CPU power in use"


def _dominant(processes: list[dict], key: str, total: float) -> Optional[tuple[dict, float]]:
    """The top process and its share, or None if nothing clearly dominates."""
    if not processes or total <= 0:
        return None

    ranked = sorted(processes, key=lambda p: p.get(key, 0) or 0, reverse=True)
    top = ranked[0]
    top_value = top.get(key, 0) or 0
    if top_value <= 0:
        return None

    share = top_value / total
    if share < DOMINANCE_SHARE:
        return None

    if len(ranked) > 1:
        runner_up = ranked[1].get(key, 0) or 0
        if runner_up > 0 and top_value < runner_up * DOMINANCE_RATIO:
            return None

    return top, share


def find_cpu_culprit(processes: list[dict], total_cpu_percent: float) -> Optional[Culprit]:
    """
    Ranked on raw CPU percent rather than attributed watts, which are the
    same ordering -- attribution is a single multiplication by a shared
    constant -- but `total_cpu_percent` covers EVERY process, while the
    attributed list is only the top ten. Using the full total means a
    process holding 45% of a busy machine is not promoted to 80% just
    because the long tail was never sampled.
    """
    found = _dominant(processes, "cpu_percent", total_cpu_percent)
    if found is None:
        return None

    process, share = found
    return Culprit(
        info=info_for(process["name"]),
        share=share,
        detail=f"{share * 100:.0f}% of all CPU activity",
    )


def find_memory_culprit(processes: list[dict], total_memory_bytes: int) -> Optional[Culprit]:
    """
    Memory is the weaker of the two signals: RSS double-counts pages shared
    between a program's own child processes (see processes.py), so a browser's
    share is over-stated. The dominance test absorbs some of that -- a
    process has to be well clear of the field, not merely first -- and the
    message reports absolute GB, which is the number the user can check in
    Task Manager, rather than the inflated share.
    """
    found = _dominant(processes, "memory_bytes", total_memory_bytes)
    if found is None:
        return None

    process, share = found
    return Culprit(
        info=info_for(process["name"]),
        share=share,
        detail=f"{process['memory_bytes'] / 1e9:.1f} GB",
    )


def format_energy(watt_hours: float) -> str:
    if watt_hours < 1:
        return f"{watt_hours:.2f} Wh"
    if watt_hours < 10:
        return f"{watt_hours:.1f} Wh"
    return f"{watt_hours:.0f} Wh"


def format_carbon(grams: float) -> str:
    if grams < 1:
        return f"{grams:.2f} g CO2eq"
    if grams < 10:
        return f"{grams:.1f} g CO2eq"
    return f"{grams:.0f} g CO2eq"


def format_duration(seconds: float) -> str:
    """
    "under a minute", "40 min", "1h 20m".

    Exists because str(timedelta) renders "1:20:03.412197", which is what the
    reminder messages were previously showing users.
    """
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"

    hours, remainder = divmod(minutes, 60)
    return f"{hours}h" if remainder == 0 else f"{hours}h {remainder}m"


def _name_phrase(info: ProcessInfo) -> str:
    """"Chrome" or "Windows Defender, the built-in antivirus," -- ready to be
    followed directly by a verb."""
    return info.label if info.what is None else f"{info.label}, {info.what},"


def _action(info: ProcessInfo) -> str:
    """
    What to do about it, or "" when there is nothing honest to say.

    The generic fallback is gated on `closeable`, so an unrecognised process
    -- which the catalog returns with closeable=False -- never gets told to
    close. Advising someone to kill a program neither of us can identify is
    exactly the kind of confident-sounding wrong answer this tool cannot
    afford.
    """
    if info.advice:
        return info.advice
    if info.closeable:
        return f"Closing {info.label} if you are not using it would cut this."
    return ""


def _join(*parts: str) -> str:
    return " ".join(part for part in parts if part)


# Below this, the figure would render as "0.00 Wh".
NEGLIGIBLE_WATT_HOURS = 0.005


def _share_clause(share_of_day: Optional[float]) -> str:
    """
    "27% of everything your machine has used today", or "".

    A raw "14.3 Wh" is unreadable -- nobody has a sense of what a watt-hour
    is, so the figure lands as noise no matter how correct it is. Expressed
    as a share of the day it needs no units and no prior knowledge.

    Only ever attached to MEASURED figures. A projection compared against the
    day's actual total would be two different kinds of number in one
    sentence, and the reader has no way to tell which is which.
    """
    if share_of_day is None or share_of_day < 0.01:
        return ""
    return f"{share_of_day * 100:.0f}% of everything your machine has used today"


def _cost_so_far(watt_hours: float, grams: float) -> str:
    """
    The measured-cost sentence, or "" when there is nothing to report.

    A reminder reads its figure from the measurements table, and that table
    can legitimately have no rows for the period: the agent may have been
    restarted mid-episode, or the machine may have been suspended (the energy
    estimator drops those intervals by design). The result is a real zero for
    "energy we recorded" and a false zero for "energy the machine used".

    Saying "this has cost about 0.00 Wh so far" would be the tool asserting a
    measurement it never took, which is the one thing it cannot do and stay
    trustworthy. Staying quiet about the cost is the honest option; the
    duration in the same message still conveys that the situation continues.
    """
    if watt_hours < NEGLIGIBLE_WATT_HOURS:
        return ""
    return f"That has cost about {format_energy(watt_hours)}, or {format_carbon(grams)}, so far."


def compose_elevated(
        *,
        metric_label: str,
        resource: str,
        current: float,
        baseline_mean: float,
        watt_hours: float,
        grams: float,
        is_first_notice: bool,
        culprit: Culprit,
        elapsed_seconds: float = 0.0,
        share_of_day: Optional[float] = None,
) -> str:
    """
    metric_label  "CPU usage" / "Memory usage"
    resource      "CPU" / "memory", for use mid-sentence
    watt_hours    Projected over the next hour on a first notice; actually
                  measured since onset on a reminder. The caller decides
                  which, and the wording here matches ("at this rate" vs
                  "has cost"), so the two can never be presented as the same
                  kind of number.

    `culprit` is REQUIRED. There used to be an aggregate variant for when
    nothing dominated, and it produced the single least useful sentence the
    tool has ever written: "CPU usage is at 100% against your usual 33%,
    spread across several applications with no single one responsible."
    That is a statistic, not a recommendation -- there is nothing to act on
    and no reason to interrupt anyone with it. The engine now stays silent
    instead, so the variant no longer exists to be produced by accident.
    """
    energy = f"about {format_energy(watt_hours)}, or {format_carbon(grams)},"

    if is_first_notice:
        return _join(
            # "overall usage", not metric_label again: the sentence has
            # already named the resource, and lowercasing the label to
            # fit mid-sentence produced "with cpu usage at 94%".
            f"{_name_phrase(culprit.info)} is taking most of your {resource} "
            f"right now: {culprit.detail}, with overall usage at "
            f"{current:.0f}% against your usual {baseline_mean:.0f}%.",
            _action(culprit.info),
            f"At this rate that is {energy} an hour.",
        )

    # Reminders deliberately drop the advice. It was given on the first
    # notice; repeating it verbatim every 90 minutes is nagging, and the
    # point of a reminder is that the situation is CONTINUING, which is what
    # the duration and the accumulated cost convey.
    duration = format_duration(elapsed_seconds)

    share = _share_clause(share_of_day)
    cost = (
        f"That has cost about {format_energy(watt_hours)} — {share}."
        if share and watt_hours >= NEGLIGIBLE_WATT_HOURS
        else _cost_so_far(watt_hours, grams)
    )

    return _join(
        f"{metric_label} has been elevated for {duration} and "
        f"{culprit.info.label} is still the largest share, at "
        f"{culprit.detail}.",
        cost,
    )


def compose_idle(
        *,
        idle_seconds: float,
        power_watts: float,
        watt_hours: float,
        grams: float,
        sleep_timer_minutes: int,
        is_first_notice: bool,
        culprit: Optional[Culprit] = None,
        share_of_day: Optional[float] = None,
) -> str:
    """
    The idle message reports measured waste, never a projection: the machine
    has already drawn this, which is a stronger thing to say than a forecast
    and needs no caveat.
    """
    duration = format_duration(idle_seconds)

    # Same honesty rule as the reminders: the waste figure is read from the
    # measurements table and can legitimately be empty, so the sentence is
    # built with or without it rather than printing a zero.
    measured = watt_hours >= NEGLIGIBLE_WATT_HOURS
    energy = f"about {format_energy(watt_hours)}, or {format_carbon(grams)},"

    if is_first_notice:
        # Naming the process matters more here than anywhere else: an idle
        # machine that is still busy means something is running unattended,
        # and which thing it is decides whether that is fine (a scheduled
        # scan) or worth stopping (a forgotten render).
        cause = (
            f"Most of the CPU share is {culprit.info.label}."
            if culprit is not None else ""
        )
        share = _share_clause(share_of_day)
        if measured and share:
            # The strongest form the tool has: a measured waste figure with a
            # scale the reader can feel, and a fix that takes one click.
            opening = (
                f"Your machine has spent {duration} awake with nobody at it — "
                f"{format_energy(watt_hours)}, {share}."
            )
        elif measured:
            opening = (
                f"Nobody has used this machine for {duration}, but it is still "
                f"drawing {power_watts:.1f} W: {energy} spent with no one at "
                f"the keyboard."
            )
        else:
            opening = (
                f"Nobody has used this machine for {duration}, but it is still "
                f"drawing {power_watts:.1f} W with no one at the keyboard."
            )
        return _join(
            opening,
            cause,
            f"A {sleep_timer_minutes}-minute sleep timer would recover most of that.",
        )

    share = _share_clause(share_of_day)
    if measured and share:
        opening = f"Still idle after {duration} — {format_energy(watt_hours)} now, {share}."
    elif measured:
        opening = (
            f"Still idle after {duration}, drawing {power_watts:.1f} W: "
            f"{energy} in total now."
        )
    else:
        opening = f"Still idle after {duration}, still drawing {power_watts:.1f} W."
    return _join(
        opening,
        "Setting a sleep timeout in Windows power settings would stop this "
        "happening.",
    )


def compose_unattended(
        *,
        idle_seconds: float,
        cpu_percent: float,
        culprit: Culprit,
        watt_hours: float,
        grams: float,
        is_first_notice: bool,
        share_of_day: Optional[float] = None,
) -> str:
    """
    Idle AND busy -- something is running with nobody there.

    Kept apart from the plain idle message because the two mean genuinely
    different things. An idle machine at 9 W is a machine someone forgot to
    sleep. An idle machine at 26 W with Handbrake at 70% is a job running
    unattended, and the right response is completely different: check whether
    it is meant to be running, not set a sleep timer (which would kill it).
    """
    duration = format_duration(idle_seconds)
    share = _share_clause(share_of_day)
    cost = (
        f"{format_energy(watt_hours)} so far{', ' + share if share else ''}"
        if watt_hours >= NEGLIGIBLE_WATT_HOURS else ""
    )

    if is_first_notice:
        return _join(
            f"Something has been running unattended for {duration}: "
            f"{_name_phrase(culprit.info)} at {culprit.detail}, with nobody "
            f"at the keyboard." + (f" {cost}." if cost else ""),
            culprit.info.advice or "",
        )

    return _join(
        f"{culprit.info.label} is still running unattended after {duration}, "
        f"at {culprit.detail}." + (f" {cost}." if cost else ""),
        "If this is not meant to be running, stopping it is the whole saving.",
    )
