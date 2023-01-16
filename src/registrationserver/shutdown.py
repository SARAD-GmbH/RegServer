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

FLAGFILENAME = f"{home}{os.path.sep}stop.file"


def set_file_flag(running, with_error=False):
    """Function to create a file that is used as flag in order to detect that the
    Instrument Server should be stopped.

    Args:
        running (bool): If False, the file will be created and the system shall be shutdown.
        with_error (bool): If True, the system shall be shutdown with error
                           in order to restart the service automatically.

    Returns:
        None
    """
    try:
        os.remove(FLAGFILENAME)
        logger.info("Remove %s", FLAGFILENAME)
    except FileNotFoundError:
        logger.info("%s not found", FLAGFILENAME)
    if not running:
        with open(FLAGFILENAME, "w", encoding="utf8") as flag_file:
            flag_file.write(str(with_error))
        logger.info("Write %s, with_error = %s", FLAGFILENAME, with_error)


def is_flag_set():
    """Function to detect whether the flag indicating that the RegServer shall
    be stopped was set.

    Returns:
        {bool, bool}: 1st: True if the programm was started and shall stay running.
              False if the system shall be stopped by the main program.
              2nd: True if the system shall be terminated with error
    """
    if os.path.isfile(FLAGFILENAME):
        with open(FLAGFILENAME, "r", encoding="utf8") as flag_file:
            with_error_str = flag_file.read(4)
            if with_error_str == "True":
                with_error = True
            elif with_error_str == "Fals":
                with_error = False
            else:
                logger.error("Stop file corrupted: %s", with_error_str)
                with_error = True
    else:
        with_error = False
    return not os.path.isfile(FLAGFILENAME), with_error


def system_shutdown(with_error=True):
    """Initiate the shutdown process

    This is only a wrapper for set_file_flag()
    that was introduced in order to improve the readability of code

    Args:
       with_error (bool): True indicates that the programm shall be terminated with error
    """
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
