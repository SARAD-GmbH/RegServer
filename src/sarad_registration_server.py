"""Wrapper to start and stop SARAD Registration Server"""
import signal

import registrationserver.main


def signal_handler(_sig, _frame):
    """On Ctrl+C: stop MQTT loop"""
    registrationserver.main.set_file_flag(False)


def main():
    """Starting the RegistrationServer"""

    registrationserver.main.main()


if __name__ == "__main__":
    # Pyinstaller fix
    multiprocessing.freeze_support()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()
