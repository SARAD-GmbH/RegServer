"""Listening for new SARAD instruments appearing on USB or RS-232
(Linux implementation)

Created
    2021-06-08

Authors
    Michael Strey <strey@sarad.de>

.. uml :: uml-linux_usb_listener.puml
"""
import signal

import pyudev
# import registrationserver2.modules.usb.usb_actor
from registrationserver2 import logger
from sarad.cluster import SaradCluster

logger.info("%s -> %s", __package__, __file__)


class LinuxUsbListener:
    """Class to listen for SARAD instruments connected via USB."""

    def __init__(self):
        logger.info("Linux USB listener started")
        mycluster: SaradCluster = SaradCluster()
        context = pyudev.Context()
        for device in context.list_devices(subsystem="tty"):
            self.usb_device_event("add", device)
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by("tty")
        usb_stick_observer = pyudev.MonitorObserver(monitor, self.usb_device_event)
        usb_stick_observer.start()

    def usb_device_event(self, action, device):
        """docstring"""
        logger.debug("%s device %s", action, device)


if __name__ == "__main__":

    def signal_handler(_signal, _frame):
        logger.info("Linux USB listener stopped")

    _ = LinuxUsbListener()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.pause()
