#!/usr/bin/env python3
"""Wrapper to start and stop SARAD Registration Server

:Created:
    2021-09-17

:Author:
    | Michael Strey <strey@sarad.de>
"""
import multiprocessing
import signal

import registrationserver.main
from registrationserver.shutdown import system_shutdown


def signal_handler(_sig, _frame):
    """On Ctrl+C: stop MQTT loop

    The signal handler removes the flag file. This will cause the main MQTT
    loop to stop and call the cleanup function."""
    system_shutdown()


def main():
    """Starting the RegistrationServer"""

    registrationserver.main.main()


if __name__ == "__main__":
    # Pyinstaller fix
    multiprocessing.freeze_support()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()
