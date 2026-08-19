"""
The machine's Windows power policy: which plan is active, and how long it
waits before turning off the display or sleeping.

Everything else this project collects is a MEASUREMENT of what the machine
did. This is a reading of what it was CONFIGURED to do, which is a different
kind of fact and the more useful one for advice: a measurement tells you 96
minutes were wasted, the configuration tells you whether that was the user's
habit or the machine's policy, and only one of those is worth writing a
recommendation about.

Read through powercfg rather than the registry because the registry layout
for power schemes is undocumented and version-dependent, while powercfg is a
stable, shipped interface. No administrator rights are needed for /query.
"""

import re
import subprocess

# Well-known GUIDs from the Windows power scheme schema. These are constants
# of the OS, identical on every machine, which is what makes them safe to
# hardcode — unlike the human-readable setting names, which are localised.
_SUBGROUP_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
_SETTING_VIDEO_IDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"

_SUBGROUP_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
_SETTING_STANDBY_IDLE = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"
_SETTING_HIBERNATE_IDLE = "9d7815a6-7ee4-497e-8888-515a05f02364"

_GUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_INDEX_PATTERN = re.compile(r"0x([0-9a-f]{8})")


def _powercfg(*args: str) -> str:
    """
    Runs powercfg and decodes its output defensively.

    Decoding is explicitly utf-8 with errors="replace" rather than the
    default. On this machine — a French Windows install — letting Python use
    the console codepage raised UnicodeDecodeError on the accented text in
    powercfg's own labels, taking the whole call down. Since every value this
    module wants is a hex number or a GUID, mangling a few accented
    characters costs nothing and never crashing is worth a great deal.
    """
    try:
        completed = subprocess.run(
            ["powercfg", *args],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.decode("utf-8", errors="replace")


def _timeout_seconds(scheme_guid: str, subgroup: str, setting: str) -> dict:
    """
    Returns {"ac": seconds|None, "battery": seconds|None}.

    The two values are read POSITIONALLY — powercfg prints the AC index
    first, then the DC one — because the labels around them ("Current AC
    Power Setting Index") are translated, and matching English text finds
    nothing on a localised Windows. The GUIDs printed earlier in the output
    contain hyphens, so a strict 0x + 8 hex digits pattern cannot collide
    with them.
    """
    output = _powercfg("/query", scheme_guid, subgroup, setting)
    indices = _INDEX_PATTERN.findall(output)
    if len(indices) < 2:
        return {"ac": None, "battery": None}
    return {
        "ac": int(indices[-2], 16),
        "battery": int(indices[-1], 16),
    }


def collect() -> dict:
    """
    Current power policy, or None values throughout if powercfg is
    unavailable. A timeout of 0 means "never" in the Windows schema and is
    preserved as 0 rather than translated here — deciding what "never" means
    is the estimator's job, not the collector's.
    """
    scheme_output = _powercfg("/getactivescheme")
    match = _GUID_PATTERN.search(scheme_output)
    if match is None:
        return {
            "plan_name": None, "plan_guid": None,
            "display_off": {"ac": None, "battery": None},
            "sleep": {"ac": None, "battery": None},
            "hibernate": {"ac": None, "battery": None},
        }

    guid = match.group(0)
    # The friendly name is the parenthesised part of the same line. Localised,
    # so it is only ever displayed, never matched against.
    name_match = re.search(r"\(([^)]*)\)", scheme_output)

    return {
        "plan_name": name_match.group(1).strip() if name_match else None,
        "plan_guid": guid,
        "display_off": _timeout_seconds(guid, _SUBGROUP_VIDEO, _SETTING_VIDEO_IDLE),
        "sleep": _timeout_seconds(guid, _SUBGROUP_SLEEP, _SETTING_STANDBY_IDLE),
        "hibernate": _timeout_seconds(guid, _SUBGROUP_SLEEP, _SETTING_HIBERNATE_IDLE),
    }
