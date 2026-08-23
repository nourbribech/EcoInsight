"""
One ranked list of things to do, gathered from every rule that produces them.

WHY THIS EXISTS
The dashboard grew three separate places that tell the user to act: power
settings from config_audit, developer workloads from workloads, and the
episodic recommendations feed. Three lists with no shared ranking fragment
the one output the product exists to deliver - the reader has to compare
across panels to work out what matters most, which is the job the tool was
supposed to do for them.

It got worse when the page was split into views: the WSL findings moved to
the "This machine" tab, so a finding marked "you can fix this" was sitting on
a different screen from every other actionable row.

WHAT IS AND IS NOT MERGED HERE
Standing findings only. config_audit and workloads both describe STATES -
true right now, and true until somebody changes something - so they rank
against each other honestly.

The recommendations feed is deliberately left out. Those are EVENTS with
timestamps, and nothing in the schema says whether one is still true. A
recommendation written three hours ago may have resolved itself, and there is
no "resolved" column to consult. Promoting them by recency would mean
inferring "still happening" from "happened recently", which is a guess
dressed as a fact. The feed stays a log.

WHY `ok` ROWS SURVIVE
An empty panel teaches its user that the feature does nothing - the exact
problem config_audit was written to solve. So rows with nothing to do are
kept, but separated: they are a reassurance, not a task, and mixing them into
a ranked action list would dilute it.
"""

from dataclasses import dataclass, asdict

from GreenIT.estimators.config_audit import Finding

# Severity first. A high-severity item somebody else has to fix still matters
# more than a cosmetic one the user could fix now - a battery at 46% outranks
# a screen timeout however convenient the timeout is to change.
_SEVERITY_ORDER = {"high": 0, "medium": 1, "ok": 2}

# Then who can act. Between two findings of equal severity, the one the user
# can do something about right now beats the one that needs a ticket raised
# with IT and a wait. A list that opens with three things requiring somebody
# else reads as a list of complaints.
_FIXABLE_ORDER = {"you": 0, "it": 1, "none": 2}

# Unknown values sort last rather than crashing, so adding a severity or an
# owner to a rule cannot take the panel down.
_UNKNOWN = 99


@dataclass(frozen=True)
class Action:
    """A Finding plus where it came from.

    `source` is carried so the UI can attribute a row without the reader
    having to guess which subsystem noticed - "power settings" and "developer
    workloads" want different mental models even when the advice looks alike.
    """
    key: str
    title: str
    detail: str
    action: str | None
    fixable: str
    severity: str
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


def _sort_key(entry: tuple[int, int, Action]) -> tuple:
    source_index, position, action = entry
    return (
        _SEVERITY_ORDER.get(action.severity, _UNKNOWN),
        _FIXABLE_ORDER.get(action.fixable, _UNKNOWN),
        # Ties keep the order each rule emitted them in, and sources keep the
        # order they were passed. Stable output matters more than it sounds:
        # a list that reshuffles between polls is unreadable even when every
        # row is correct.
        source_index,
        position,
    )


def rank(sources: list[tuple[str, list[Finding]]]) -> list[Action]:
    """
    `sources` is [(source_label, findings), ...] in preference order.

    Returns every finding as an Action, most important first.
    """
    entries: list[tuple[int, int, Action]] = []

    for source_index, (label, findings) in enumerate(sources):
        for position, finding in enumerate(findings):
            entries.append((source_index, position, Action(
                key=f"{label}:{finding.key}",
                title=finding.title,
                detail=finding.detail,
                action=finding.action,
                fixable=finding.fixable,
                severity=finding.severity,
                source=label,
            )))

    return [action for _, _, action in sorted(entries, key=_sort_key)]


def summarise(actions: list[Action]) -> dict:
    """
    Counts for the panel header.

    `yours` is called out separately because it answers the only question a
    reader has on arriving: is any of this mine to do?
    """
    todo = [a for a in actions if a.severity != "ok"]

    return {
        "total": len(actions),
        "todo": len(todo),
        "yours": sum(1 for a in todo if a.fixable == "you"),
        "needs_it": sum(1 for a in todo if a.fixable == "it"),
        "high": sum(1 for a in todo if a.severity == "high"),
    }
