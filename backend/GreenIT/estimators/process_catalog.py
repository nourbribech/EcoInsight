"""
What a process actually IS, in words a person can act on.

Collectors never interpret their readings, so `processes.py` hands back what
Windows reports: "MsMpEng.exe", "TiWorker.exe", "msedgewebview2.exe". Those
are correct and useless. A recommendation saying "MsMpEng.exe is using 60% of
your CPU" tells you nothing unless you already know MsMpEng is Windows
Defender -- and if you knew that, you did not need the recommendation.

WHY THIS IS A TABLE AND NOT A MODEL
The set of programs that reach the top of a CPU list is small, stable, and
slow to change. A wrong entry here is worse than a missing one: telling
someone to close their antivirus, or naming the wrong culprit, costs more
trust than saying nothing. So every claim in this file is one a human wrote
and can be held to, and anything unrecognised falls back to a tidied name
with no claim attached.

WHERE THE ENTRIES CAME FROM
The Windows entries are the names actually observed in this machine's
`process_samples` table, so the ones that carry weight in practice are
covered rather than the ones that seem obvious in the abstract. That is also
how `MemCompression` got in with the right spelling (no space) and how the
Defender for Endpoint pair arrived at all -- both would have been missed by
writing the list from memory. Descriptions follow vendor documentation.
The application entries are a curated head for machines other than this one.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProcessInfo:
    """
    label   Human-readable application name.
    what    Noun phrase used as an appositive, so it must read correctly in
            "Windows Defender, the built-in antivirus, is using...".
            None when the label already explains itself (Chrome, Spotify).
            Keep it SHORT -- a notification is one or two lines, and two
            stacked appositives in one sentence is unreadable. Anything
            longer than a few words belongs in `advice`.
    advice  A full sentence saying what the user can do. None when there is
            nothing honest to suggest.
    closeable
            Whether "close it if you are not using it" is sensible advice.
            False for anything the OS needs, so the generic suggestion can
            never be aimed at a system service.
    """
    label: str
    what: Optional[str] = None
    advice: Optional[str] = None
    closeable: bool = False


def _app(label: str, what: Optional[str] = None, advice: Optional[str] = None) -> ProcessInfo:
    """A user application: closing it is a reasonable thing to suggest."""
    return ProcessInfo(label=label, what=what, advice=advice, closeable=True)


def _system(label: str, what: Optional[str] = None, advice: Optional[str] = None) -> ProcessInfo:
    """Part of Windows: never suggest closing it."""
    return ProcessInfo(label=label, what=what, advice=advice, closeable=False)


# Keyed lowercase: Office ships uppercase exe names ("EXCEL.EXE") while most
# other programs are mixed case, and matching has to survive both.
_CATALOG: dict[str, ProcessInfo] = {

    # ---- observed on this machine ----------------------------------------

    "msmpeng.exe": _system(
        "Windows Defender",
        "the built-in antivirus",
        "This is almost always a scheduled scan, which finishes on its own; "
        "you can move it to a better time in Windows Security.",
    ),
    "mssense.exe": _system(
        "Defender for Endpoint",
        "the security monitoring agent your organisation installed",
        "This one is managed centrally by IT and is not meant to be stopped.",
    ),
    "sensetvm.exe": _system(
        "Defender vulnerability scan",
        "a scheduled software inventory scan",
        "It runs to a schedule set by IT and stops by itself.",
    ),
    "svchost.exe": _system(
        "Windows Services",
        "a shared host for background Windows services",
        "Dozens of unrelated services run inside it; Task Manager's Details "
        "view shows which one is responsible.",
    ),
    "system": _system(
        "Windows kernel",
        "usually driver or disk activity",
    ),
    "memcompression": _system(
        "Memory Compression",
        "Windows compressing memory instead of writing it to disk",
        "Sustained activity here usually means the machine is short on RAM.",
    ),
    "dwm.exe": _system(
        "Desktop Window Manager",
        "the compositor that draws every window on screen",
    ),
    "audiodg.exe": _system(
        "Windows Audio",
        "audio mixing and any effects applied by your sound drivers",
    ),
    "wmiprvse.exe": _system(
        "WMI Provider Host",
        "the service that answers hardware queries",
        "Some of this is EcoInsight itself polling for sensor readings.",
    ),
    "explorer.exe": _system(
        "Windows Explorer",
        "the desktop, taskbar and file windows",
    ),
    "startmenuexperiencehost.exe": _system("Start Menu"),

    "code.exe": _app(
        "VS Code",
        None,
        "Extensions and language servers are the usual cause; the built-in "
        "process explorer shows which one.",
    ),
    "msedge.exe": _app("Edge", None, "Closing tabs you are finished with would cut this."),
    "chrome.exe": _app("Chrome", None, "Closing tabs you are finished with would cut this."),
    "msedgewebview2.exe": _app(
        "Edge WebView2",
        "a browser engine embedded in another app",
        "Teams, Outlook and Widgets all run inside one; it closes with "
        "whichever app is hosting it.",
    ),
    "python.exe": _app("Python", "a Python script or interpreter"),
    "pythonw.exe": _app("Python", "a Python script running without a window"),
    "powershell.exe": _app("PowerShell", "a PowerShell script or console"),
    "netdata.exe": _app("Netdata", "the Netdata monitoring agent"),
    "apps.plugin.exe": _app(
        "Netdata process plugin",
        "the part of Netdata that walks every process",
    ),

    # ---- curated head for other machines ---------------------------------

    "firefox.exe": _app("Firefox", None, "Closing tabs you are finished with would cut this."),
    "brave.exe": _app("Brave", None, "Closing tabs you are finished with would cut this."),
    "opera.exe": _app("Opera", None, "Closing tabs you are finished with would cut this."),

    "devenv.exe": _app("Visual Studio"),
    "pycharm64.exe": _app("PyCharm", None, "Background indexing settles once it finishes."),
    "idea64.exe": _app("IntelliJ IDEA", None, "Background indexing settles once it finishes."),
    "webstorm64.exe": _app("WebStorm", None, "Background indexing settles once it finishes."),
    "rider64.exe": _app("Rider", None, "Background indexing settles once it finishes."),
    "clion64.exe": _app("CLion", None, "Background indexing settles once it finishes."),
    "sublime_text.exe": _app("Sublime Text"),
    "notepad++.exe": _app("Notepad++"),
    "notepad.exe": _app("Notepad"),

    "discord.exe": _app("Discord", None, "Hardware acceleration and active voice calls are the usual cause."),
    "slack.exe": _app("Slack"),
    "teams.exe": _app("Microsoft Teams", None, "Video calls and background effects are the usual cause."),
    "ms-teams.exe": _app("Microsoft Teams", None, "Video calls and background effects are the usual cause."),
    "zoom.exe": _app("Zoom", None, "Video calls and virtual backgrounds are the usual cause."),
    "whatsapp.exe": _app("WhatsApp"),
    "telegram.exe": _app("Telegram"),
    "outlook.exe": _app("Outlook", None, "A large mailbox re-indexing can keep this busy for a while."),
    "thunderbird.exe": _app("Thunderbird"),

    "spotify.exe": _app("Spotify"),
    "vlc.exe": _app("VLC", "a media player, most likely decoding video"),
    "steam.exe": _app("Steam"),
    "steamwebhelper.exe": _app("Steam", "Steam's built-in browser, used by the store and the overlay"),
    "epicgameslauncher.exe": _app("Epic Games Launcher"),
    "obs64.exe": _app("OBS Studio", "screen recording or streaming software"),

    "excel.exe": _app("Excel", None, "A workbook with heavy formulas will recalculate continuously."),
    "winword.exe": _app("Word"),
    "powerpnt.exe": _app("PowerPoint"),
    "onenote.exe": _app("OneNote"),
    "acrord32.exe": _app("Adobe Acrobat Reader"),
    "acrobat.exe": _app("Adobe Acrobat"),

    "node.exe": _app("Node.js", "a Node.js process, often a dev server or a build watcher"),
    "java.exe": _app("Java", "a Java application"),
    "javaw.exe": _app("Java", "a Java application running without a window"),
    "pwsh.exe": _app("PowerShell", "a PowerShell script or console"),
    "cmd.exe": _app("Command Prompt"),
    "windowsterminal.exe": _app("Windows Terminal"),
    "git.exe": _app("Git"),
    "bash.exe": _app("Bash", "a shell script"),
    "docker desktop.exe": _app("Docker Desktop"),
    "com.docker.backend.exe": _app("Docker", "the Docker engine and its containers"),
    "vmmem.exe": _app("Virtual machine", "memory and CPU used by a running virtual machine"),
    "vmmemwsl.exe": _app("WSL", "the Linux subsystem and whatever is running inside it"),

    "onedrive.exe": _app("OneDrive", "file sync",
                         "Heavy activity usually means a large upload or download is in progress."),
    "dropbox.exe": _app("Dropbox", "file sync",
                        "Heavy activity usually means a large upload or download is in progress."),
    "googledrivefs.exe": _app("Google Drive", "file sync",
                              "Heavy activity usually means a large upload or download is in progress."),

    "searchindexer.exe": _system(
        "Windows Search",
        "the search index being rebuilt",
        "Indexing is a one-off catch-up after large file changes and stops when it is done.",
    ),
    "searchprotocolhost.exe": _system("Windows Search", "the search index being rebuilt"),
    "searchfilterhost.exe": _system("Windows Search", "the search index being rebuilt"),
    "tiworker.exe": _system(
        "Windows Update",
        "updates being installed or cleaned up in the background",
        "This ends on its own once the update finishes.",
    ),
    "trustedinstaller.exe": _system("Windows Update", "updates being installed in the background"),
    "usoclient.exe": _system("Windows Update", "the update scheduler checking for new updates"),
    "runtimebroker.exe": _system("Runtime Broker", "the service that manages permissions for Store apps"),
    "csrss.exe": _system("Windows Client/Server Runtime"),
    "lsass.exe": _system("Windows Security Authority", "sign-in and credential handling"),
    "services.exe": _system("Windows Service Manager"),
    "taskhostw.exe": _system("Windows Task Host", "scheduled background tasks"),
    "sihost.exe": _system("Shell Infrastructure Host"),
    "ctfmon.exe": _system("Windows Text Input"),
    "textinputhost.exe": _system("Windows Text Input"),
    "shellexperiencehost.exe": _system("Windows Shell"),
    "systemsettings.exe": _system("Windows Settings"),
    "securityhealthservice.exe": _system("Windows Security"),
    "nissrv.exe": _system("Windows Defender", "Defender's network inspection service"),
    "registry": _system("Windows Registry"),
}


def _tidy(executable_name: str) -> str:
    """
    "someapp.exe" -> "Someapp", "VsDebugConsole.exe" -> "VsDebugConsole".

    Title-casing is applied only to names that arrive entirely lowercase.
    Names that already carry capitals were cased deliberately by their author
    and usually read fine; forcing title case turns "VsDebugConsole" into
    "Vsdebugconsole", which is a regression rather than a cleanup.
    """
    stem = executable_name[:-4] if executable_name.lower().endswith(".exe") else executable_name
    if not stem:
        return executable_name
    return stem.title() if stem.islower() else stem


def info_for(executable_name: str) -> ProcessInfo:
    """
    Everything known about a process. Always returns a ProcessInfo -- an
    unrecognised name gets a tidied label, no description, no advice, and
    closeable=False, so nothing is ever claimed about a program this table
    does not actually know.
    """
    if not executable_name:
        return ProcessInfo(label="Unknown")

    known = _CATALOG.get(executable_name.lower())
    if known is not None:
        return known

    return ProcessInfo(label=_tidy(executable_name))


def label_for(executable_name: str) -> str:
    """Just the display name. Used by the API to decorate /api/processes."""
    return info_for(executable_name).label
