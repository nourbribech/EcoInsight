"""
The EcoInsight agent — the single process a user actually runs.

Starts the estimation loop on a background thread and serves the dashboard
plus its API on a local port from the same process. That's the whole product
model in one entry point: the agent runs quietly in the background collecting
and estimating, and when the user wants to look at it they open
http://127.0.0.1:8000 — the same shape as Netdata.

Previously these were two separate manual commands (`python -m
GreenIT.services.estimation_loop` and a separate uvicorn), which meant the
collector died whenever its terminal closed and the dashboard silently served
stale data. Running them together removes that failure mode: if the agent is
up, collection is up.

Run it with:
    python -m GreenIT.agent

CONCURRENCY NOTES
1. The loop thread writes to SQLite while the API thread reads from it.
   That's safe here only because every function in database.py opens its own
   connection for the call and closes it — no sqlite3 connection is ever
   shared across threads, which is the thing sqlite3 actually forbids by
   default.

2. The collectors reach Windows through WMI, which is built on COM, and COM
   state is PER-THREAD. Moving the loop off the main thread is exactly what
   makes CoInitialize() necessary here — see _run_estimation_loop.
"""

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import pythoncom
import uvicorn

from GreenIT.api.api import app
from GreenIT.services.estimation_loop import EstimationLoop

# Next to the database, because they are the same kind of thing: state this
# machine's agent produced.
LOG_PATH = Path(__file__).resolve().parent / "data" / "agent.log"

# Loopback only. The agent holds a detailed record of what the user does with
# their machine, so it should never be reachable from the network without a
# deliberate decision to expose it.
HOST = "127.0.0.1"
PORT = 8000


def _attach_log() -> None:
    """
    Gives the agent somewhere to speak when nobody is listening.

    Started from Task Scheduler there is no console at all, and pythonw sets
    sys.stdout and sys.stderr to None. The first print() then raises
    AttributeError -- inside the daemon collection thread, where the only
    handler tries to report the crash by printing, and raises again. The agent
    dies at log-on with no window, no error, and no trace of why. That is
    exactly how this was found: the scheduled task reported success and
    nothing was ever listening on port 8000.

    Redirecting rather than adding a logging framework keeps every existing
    print() working unchanged, including uvicorn's.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return  # Started from a terminal; leave the user's console alone.

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # line_buffering so a crash is on disk before the process dies, and utf-8
    # because the messages contain characters cp1252 cannot represent.
    handle = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = handle
    sys.stderr = handle
    print(f"\n=== agent started {datetime.now():%Y-%m-%d %H:%M:%S} ===")


def _run_estimation_loop() -> None:
    """Body of the background collection thread."""
    # REQUIRED before any WMI call on this thread.
    #
    # system_identity.collect() and cpu_info.get_cpu_info() go through WMI,
    # which is COM-based, and COM demands that every thread initialise it
    # separately. Without this the very first call raises
    # x_wmi_uninitialised_thread and the loop dies before its first tick.
    #
    # It's needed here and not in estimation_loop.py because the loop only
    # became a non-main thread when this agent started hosting it — running
    # `python -m GreenIT.services.estimation_loop` directly puts it on the
    # main thread, where Python has already initialised COM.
    pythoncom.CoInitialize()
    try:
        EstimationLoop().run_forever()
    except Exception:
        # A daemon thread that dies silently would leave the dashboard up and
        # apparently healthy while it quietly served frozen data — the exact
        # failure this entry point exists to prevent. Make it loud.
        print("\n[agent] ESTIMATION LOOP CRASHED — collection has stopped.")
        traceback.print_exc()
    finally:
        pythoncom.CoUninitialize()


def main() -> None:
    _attach_log()

    collector = threading.Thread(
        target=_run_estimation_loop,
        name="estimation-loop",
        # Daemon so Ctrl+C on the server exits the whole process instead of
        # hanging on a thread whose while-True loop never returns.
        daemon=True,
    )
    collector.start()

    print(f"EcoInsight agent running — dashboard at http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Last resort. If main() fails before _attach_log() runs -- an import
        # error, a missing database directory -- there is no console and no
        # redirect, so the traceback has nowhere to go. Write it straight to
        # the file instead of letting the process vanish without a word.
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"\n=== agent FAILED {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            traceback.print_exc(file=handle)
        raise
