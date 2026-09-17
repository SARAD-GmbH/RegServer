"""Functions to enable the initiation of shutdown from all other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""

import os
import signal
from datetime import datetime

import psutil

from regserver.config import actor_config, home
from regserver.logger import logger

FLAGFILENAME = f"{home}{os.path.sep}stop.file"


def set_file_flag(running, with_error=False, fast=False):
    """Function to create a file that is used as flag in order to detect that the
    Instrument Server should be stopped.

    Args:
        running (bool): If False, the file will be created and the system shall be
                        shut down.
        with_error (bool): If True, the system shall be shut down with error
                           in order to restart the service automatically.
        fast (bool): If True, the system shall be shut down in the fastest possible way.

    Returns:
        None
    """
    if running:
        try:
            os.remove(FLAGFILENAME)
            if with_error:
                logger.info("Remove %s", FLAGFILENAME)
        except FileNotFoundError:
            if with_error:
                logger.info("%s not found", FLAGFILENAME)
            else:
                pass
    elif not os.path.exists(FLAGFILENAME):
        with open(FLAGFILENAME, "w", encoding="utf8") as flag_file:
            flag_file.write(f"{with_error},{fast}")
        if with_error:
            logger.info(
                "Write %s, with_error = %s, fast = %s", FLAGFILENAME, with_error, fast
            )


def is_flag_set():
    """Function to detect whether the flag indicating that the RegServer shall
    be stopped was set.

    Returns:
        {bool, bool, bool}: 1st: True if the programm was started and shall stay running.
              False if the system shall be stopped by the main program.
              2nd: True if the system shall be terminated with error.
              3rd: True if the system shall be terminated in the fastest way.
    """
    stop_file_exists = os.path.isfile(FLAGFILENAME)
    if stop_file_exists:
        try:
            with open(FLAGFILENAME, mode="r", encoding="utf8") as flag_file:
                file_content = flag_file.read()
                parts = file_content.split(",")
                with_error_str = parts[0] if len(parts) > 0 else "False"
                fast_str = parts[1] if len(parts) > 1 else "False"
                if with_error_str == "True":
                    with_error = True
                elif with_error_str == "False":
                    with_error = False
                else:
                    logger.error("Stop file corrupted: %s", with_error_str)
                    with_error = True
                if fast_str == "True":
                    fast = True
                elif fast_str == "False":
                    fast = False
                else:
                    logger.error("Stop file corrupted: %s", fast_str)
                    fast = False
        except IOError:
            stop_file_exists = False
            with_error = False
            fast = False
    else:
        with_error = False
        fast = False
    return not stop_file_exists, with_error, fast


def system_shutdown(with_error=True, fast=False):
    """Initiate the shutdown process

    This is only a wrapper for set_file_flag()
    that was introduced in order to improve the readability of code

    Args:
       with_error (bool): True indicates that the programm shall be terminated with error
    """
    actor_config["OUTER_WATCHDOG_TRIALS"] = 0
    actor_config["KEEPALIVE_INTERVAL"] = 0
    set_file_flag(running=False, with_error=with_error, fast=fast)


def kill_processes(regex):
    """Try to kill residual processes

    Args:
        regex (string): regular expression for the names of the
                        processes to be killed
    Returns:
        string: None in the case of success, exception string elsewise.
    """
    if os.name == "posix":
        try:
            my_pid = os.getpid()
            logger.info("My pid is %s", my_pid)
            pids = []
            for line in os.popen(
                "ps ax | grep -E -i " + regex + " | grep -v -E 'grep|pdm'"
            ):
                fields = line.split()
                pid = int(fields[0])
                if pid != my_pid:
                    pids.append(pid)
            pids.sort(reverse=True)
            for pid in pids:
                logger.info("Killing pid %s", pid)
                os.kill(pid, signal.SIGKILL)
            return None
        except Exception as exception:  # pylint: disable=broad-except
            return exception
    elif os.name == "nt":
        my_pid = os.getpid()
        logger.info("My pid is %s", my_pid)
        pids = []
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                if (proc.info["name"] == regex) and (proc.info["pid"] != my_pid):
                    pids.append(proc.info["pid"])
        except Exception as exception:  # pylint: disable=broad-except
            return exception
        pids.sort(reverse=True)
        for pid in pids:
            try:
                logger.info("Killing pid %s", pid)
                os.kill(pid, signal.SIGTERM)
            except OSError as exception:
                logger.warning("Could not kill pid %d: %s", pid, exception)
            except Exception as exception:  # pylint: disable=broad-except
                return exception
        return None
    else:
        return None


def write_ping_file(ping_file_name, time_format):
    """Write the current datetime into a file"""
    with open(ping_file_name, "w", encoding="utf8") as pingfile:
        pingfile.write(datetime.utcnow().strftime(time_format))
    logger.debug("Wrote datetime to %s", ping_file_name)
