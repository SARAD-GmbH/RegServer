#!/usr/bin/env python3
"""Wrapper to start and stop SARAD Registration Server

:Created:
    2021-09-17

:Author:
    | Michael Strey <strey@sarad.de>
"""
import multiprocessing
import os
import re
import signal
import sys
import time

from regserver.config import actor_config, home
from regserver.main import main as start

FLAGFILENAME = f"{home}{os.path.sep}stop.file"


def signal_handler(_sig, _frame):
    """On Ctrl+C: stop MQTT loop

    The signal handler removes the flag file. This will cause the main MQTT
    loop to stop and call the cleanup function."""
    system_shutdown(with_error=False)


def set_file_flag(running, with_error=False):
    """Function to create a file that is used as flag in order to detect that the
    Instrument Server should be stopped.

    Args:
        running (bool): If False, the file will be created and the system shall be
                        shut down.
        with_error (bool): If True, the system shall be shut down with error
                           in order to restart the service automatically.

    Returns:
        None
    """
    if running:
        try:
            os.remove(FLAGFILENAME)
        except FileNotFoundError:
            pass
    elif not os.path.exists(FLAGFILENAME):
        with open(FLAGFILENAME, "w", encoding="utf8") as flag_file:
            flag_file.write(str(with_error))


def system_shutdown(with_error=True):
    """Initiate the shutdown process

    This is only a wrapper for set_file_flag()
    that was introduced in order to improve the readability of code

    Args:
       with_error (bool): True indicates that the programm shall be terminated with error
    """
    actor_config["OUTER_WATCHDOG_TRIALS"] = 0
    actor_config["KEEPALIVE_INTERVAL"] = 0
    set_file_flag(running=False, with_error=with_error)


def wait_for_termination():
    """Wait until all RegServer processes are terminated. OS independent."""
    if os.name == "posix":
        process_regex = "sarad_registrat"
    elif os.name == "nt":
        process_regex = "regserver-service.exe"
    else:
        return
    still_alive = True
    while still_alive:
        if os.name == "posix":
            try:
                my_pid = os.getpid()
                pids = []
                for line in os.popen(
                    "ps ax | grep -E -i " + process_regex + " | grep -v -E 'grep|pdm'"
                ):
                    fields = line.split()
                    pid = int(fields[0])
                    if pid != my_pid:
                        pids.append(pid)
                still_alive = bool(pids)
            except Exception:  # pylint: disable=broad-except
                still_alive = False
        elif os.name == "nt":
            try:
                my_pid = os.getpid()
                pids = []
                index = 0
                for line in (
                    os.popen("wmic process get description, processid")
                    .read()
                    .split("\n\n")
                ):
                    fields = re.split(r"\s{2,}", line)
                    if index and (fields != [""]):  # omit header and bottom lines
                        process = fields[0]
                        pid = int(fields[1])
                        if (pid != my_pid) and (process == "process_regex"):
                            pids.append(pid)
                    index = index + 1
                still_alive = bool(pids)
            except Exception:  # pylint: disable=broad-except
                still_alive = False
        if still_alive:
            time.sleep(0.5)


def main():
    """Starting the RegServer"""
    # Pyinstaller fix
    multiprocessing.freeze_support()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "stop":
        system_shutdown(with_error=False)
        wait_for_termination()
        return
    if start_stop == "start":
        start()
    else:
        print("Usage: <program> start|stop")


if __name__ == "__main__":
    main()
