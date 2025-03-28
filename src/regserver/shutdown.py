"""Functions to enable the initiation of shutdown from all other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""

import os
import re
import signal
from datetime import datetime

from regserver.config import actor_config, home
from regserver.logger import logger

FLAGFILENAME = f"{home}{os.path.sep}stop.file"


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
            if with_error:
                logger.info("Remove %s", FLAGFILENAME)
        except FileNotFoundError:
            if with_error:
                logger.info("%s not found", FLAGFILENAME)
            else:
                pass
    elif not os.path.exists(FLAGFILENAME):
        with open(FLAGFILENAME, "w", encoding="utf8") as flag_file:
            flag_file.write(str(with_error))
        if with_error:
            logger.info("Write %s, with_error = %s", FLAGFILENAME, with_error)


def is_flag_set():
    """Function to detect whether the flag indicating that the RegServer shall
    be stopped was set.

    Returns:
        {bool, bool}: 1st: True if the programm was started and shall stay running.
              False if the system shall be stopped by the main program.
              2nd: True if the system shall be terminated with error
    """
    stop_file_exists = os.path.isfile(FLAGFILENAME)
    try:
        with open(FLAGFILENAME, mode="r", encoding="utf8") as flag_file:
            with_error_str = flag_file.read(4)
            if with_error_str == "True":
                with_error = True
            elif with_error_str == "Fals":  # sic! We read only 4 characters.
                with_error = False
            else:
                logger.error("Stop file corrupted: %s", with_error_str)
                with_error = True
        stop_file_exists = stop_file_exists or True
    except IOError:
        stop_file_exists = False
        with_error = False
    return not stop_file_exists, with_error


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
        try:
            my_pid = os.getpid()
            pids = []
            index = 0
            for line in (
                os.popen("wmic process get description, processid").read().split("\n\n")
            ):
                fields = re.split(r"\s{2,}", line)
                if index and (fields != [""]):  # omit header and bottom lines
                    process = fields[0]
                    pid = int(fields[1])
                    if (pid != my_pid) and (process == "regserver-service.exe"):
                        pids.append(pid)
                index = index + 1
            pids.sort(reverse=True)
            for pid in pids:
                os.kill(pid, signal.SIGTERM)
            return None
        except Exception as exception:  # pylint: disable=broad-except
            return exception
    else:
        return None


def write_ping_file(ping_file_name, time_format):
    """Write the current datetime into a file"""
    with open(ping_file_name, "w", encoding="utf8") as pingfile:
        pingfile.write(datetime.utcnow().strftime(time_format))
    logger.debug("Wrote datetime to %s", ping_file_name)
