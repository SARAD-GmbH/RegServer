"""Wrapper to start and stop SARAD Registration Server"""
import os
import signal

import registrationserver.main


def main():
    """Starting the RegistrationServer"""

    def signal_handler(_sig, _frame):
        """On Ctrl+C: stop MQTT loop"""
        registrationserver.main.set_file_flag(False)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if os.name == "nt":
        signal.signal(signal.CTRL_C_EVENT, signal_handler)

    registrationserver.main.main()


if __name__ == "__main__":
    main()
