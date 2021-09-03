"""Wrapper to start and stop SARAD Registration Server"""
import signal

import registrationserver.main


def main():
    """Starting the RegistrationServer"""

    def signal_handler(_sig, _frame):
        """On Ctrl+C: stop MQTT loop"""
        registrationserver.main.set_file_flag(False)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    registrationserver.main.main()


if __name__ == "__main__":
    main()
