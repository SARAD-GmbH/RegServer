"""Functions to enable the initiation of shutdown from all other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import os
import re
import signal

from registrationserver.config import home
from registrationserver.logger import logger

FLAGFILENAME = f"{home}{os.path.sep}startstop.file"


def set_file_flag(running):
    """Function to create a file that is used as flag in order to detect that the
    Instrument Server should be stopped.

    Args:
        running (bool): If False, the system shall be shutdown.

    Returns:
        None
    """
    if running:
        with open(FLAGFILENAME, "w", encoding="utf8") as flag_file:
            flag_file.write("run")
        logger.info("Write %s", FLAGFILENAME)
    else:
        if os.path.isfile(FLAGFILENAME):
            os.unlink(FLAGFILENAME)
        logger.info("Remove %s", FLAGFILENAME)


def is_flag_set():
    """Function to detect whether the flag indicating that the RegServer/InstrServer shall
    proceed to run was set.

    Returns:
        bool: True if the programm was started and shall stay running.
              False if the system shall be stopped by the main program.
    """
    return os.path.isfile(FLAGFILENAME)


def system_shutdown():
    """Initiate the shutdown process

    This is only a wrapper for set_file_flag()
    that was introduced in order to improve the readability of code"""
    set_file_flag(False)


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
            pids = []
            for line in os.popen("ps ax | grep " + regex + " | grep -v grep"):
                fields = line.split()
                pid = int(fields[0])
                if pid != my_pid:
                    pids.append(pid)
            pids.sort(reverse=True)
            for pid in pids:
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
