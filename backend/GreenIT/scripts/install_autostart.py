"""
Registers the agent to start automatically at log-on.

    python -m GreenIT.scripts.install_autostart status
    python -m GreenIT.scripts.install_autostart install
    python -m GreenIT.scripts.install_autostart uninstall

This is the step that makes the product claim true. Everything else assumes
an agent that is already running; until this exists, EcoInsight is a program
you have to remember to start, which is exactly the thing nobody does.

WHY A TASK AND NOT A STARTUP SHORTCUT
A Startup-folder shortcut is simpler and worse: no control over battery
behaviour, no restart-on-failure, no way to stop a second copy launching. All
three matter here (see the settings below).

WHY XML AND NOT `schtasks /Create /SC ONLOGON`
The command-line form cannot set a working directory or touch the power
settings, and both are load-bearing:

  * `-m GreenIT.agent` needs the backend directory on sys.path, which comes
    from the working directory.
  * Task Scheduler's DEFAULTS WOULD BREAK THIS TOOL. A new task is created
    with DisallowStartIfOnBatteries and StopIfGoingOnBatteries both true, so
    on a laptop the agent would refuse to start on battery and would be
    killed the moment the charger came out -- silently switching itself off
    at precisely the times a power monitor is most interesting.

No administrator rights are required: the task runs as the logged-on user,
with no stored password.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

TASK_NAME = "EcoInsight Agent"

BACKEND_DIR = Path(__file__).resolve().parents[2]
# pythonw, not python: pythonw has no console, so the agent starts silently
# instead of leaving a black window on the desktop at every log-on.
PYTHONW = BACKEND_DIR / ".venv" / "Scripts" / "pythonw.exe"

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>EcoInsight power and carbon monitoring agent. Serves the dashboard on http://127.0.0.1:8000</Description>
    <URI>\\{task_name}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>-m GreenIT.agent</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

# Notes on the settings above, since several are deliberate:
#
#   MultipleInstancesPolicy=IgnoreNew  Two agents would both write to the
#       measurements table on their own timers, doubling every energy figure.
#       A duplicate collector is worse than none, because the numbers stay
#       plausible while being wrong.
#   Delay=PT30S  Log-on is the busiest moment in a Windows session. Starting
#       thirty seconds in keeps the agent out of that scramble, and its first
#       samples are then representative rather than measuring the log-on
#       storm itself.
#   ExecutionTimeLimit=PT0S  No limit. The default kills the task after three
#       days, which is how you end up with a monitoring agent that quietly
#       stops on Thursdays.
#   RestartOnFailure  A crash in the collector thread should not need a human.
#   Priority=7  Below normal. This tool must never be the reason a machine
#       feels slow.


def _user_id() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def status() -> int:
    """
    Reports the registered task by reading its XML rather than the human
    table.

    `schtasks /Query /V /FO LIST` prints LOCALISED field names -- on this
    machine, a French Windows install, "Task To Run" comes back as "Tâche à
    exécuter". Matching on English labels silently found nothing and printed
    an empty, reassuring report. The XML schema is not translated, so it is
    the only stable thing to parse.
    """
    result = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"])
    if result.returncode != 0:
        print(f"Not registered. Run:  python -m {__spec__.name} install")
        return 1

    xml = result.stdout.lstrip("﻿")
    try:
        tree = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        print(f"Registered, but its XML could not be parsed: {error}")
        return 1

    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    def text(path: str, default: str = "?") -> str:
        node = tree.find(path, ns)
        return default if node is None or node.text is None else node.text

    # schtasks omits settings that are at their default, so an absent
    # <Enabled> means enabled. Reporting "?" for the normal case was worse
    # than useless -- it looked like something had gone wrong.
    enabled = text(".//t:Settings/t:Enabled", "true")
    print(f"Registered '{TASK_NAME}'  (enabled: {enabled})")
    print(f"  runs     {text('.//t:Exec/t:Command')} {text('.//t:Exec/t:Arguments', '')}")
    print(f"  from     {text('.//t:Exec/t:WorkingDirectory')}")
    print(f"  trigger  log-on for {text('.//t:LogonTrigger/t:UserId')}, "
          f"delay {text('.//t:LogonTrigger/t:Delay', 'none')}")
    print()
    # The three defaults that would break a laptop power monitor. Printed
    # every time so a hand-edit in the Task Scheduler GUI is visible here.
    for label, path, want in (
            ("start on battery",  ".//t:DisallowStartIfOnBatteries", "false"),
            ("keep running on battery", ".//t:StopIfGoingOnBatteries", "false"),
            ("no time limit",     ".//t:ExecutionTimeLimit", "PT0S"),
            ("single instance",   ".//t:MultipleInstancesPolicy", "IgnoreNew"),
    ):
        actual = text(path)
        mark = "ok " if actual == want else "BAD"
        print(f"  [{mark}] {label:24} {actual}")
    return 0


def install() -> int:
    if not PYTHONW.is_file():
        print(f"ERROR: {PYTHONW} not found.")
        print("Create the virtualenv and install requirements.txt first.")
        return 1

    xml = TASK_XML.format(
        task_name=TASK_NAME,
        user=_user_id(),
        pythonw=PYTHONW,
        working_dir=BACKEND_DIR,
    )

    # schtasks /XML requires a real file, and insists on UTF-16 to match the
    # declaration in the prolog. Written to a temp file rather than into the
    # project, because it is a build artefact and contains this machine's
    # username.
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", encoding="utf-16", delete=False)
    try:
        handle.write(xml)
        handle.close()
        result = _run(["schtasks", "/Create", "/TN", TASK_NAME,
                       "/XML", handle.name, "/F"])
    finally:
        os.unlink(handle.name)

    if result.returncode != 0:
        print("FAILED to register the task:")
        print(result.stdout or result.stderr)
        return 1

    print(f"Registered '{TASK_NAME}'.")
    print(f"  runs      {PYTHONW} -m GreenIT.agent")
    print(f"  from      {BACKEND_DIR}")
    print(f"  trigger   at log-on for {_user_id()}, 30s delay")
    print(f"  dashboard http://127.0.0.1:8000")
    print()
    print("Start it now without logging out:")
    print(f'  schtasks /Run /TN "{TASK_NAME}"')
    print("Remove it again:")
    print(f"  python -m {__spec__.name} uninstall")
    return 0


def uninstall() -> int:
    result = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if result.returncode != 0:
        print("Nothing to remove (task not registered).")
        return 1
    print(f"Removed '{TASK_NAME}'. The agent will not start at log-on.")
    print("Any copy already running is left alone.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("action", choices=["status", "install", "uninstall"])
    return {"status": status, "install": install, "uninstall": uninstall}[
        parser.parse_args().action]()


if __name__ == "__main__":
    sys.exit(main())
