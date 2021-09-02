"""Wrapper to start and stop SARAD Registration Server"""
import signal

import registrationserver.main


def signal_handler(_sig, _frame):
    """On Ctrl+C: stop MQTT loop"""
    registrationserver.main.main.run = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

registrationserver.main.main()
