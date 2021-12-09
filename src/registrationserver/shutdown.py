"""Functions to enable the initiation of shutdown from all other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import os

from registrationserver.config import home

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
    else:
        if os.path.isfile(FLAGFILENAME):
            os.unlink(FLAGFILENAME)


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
