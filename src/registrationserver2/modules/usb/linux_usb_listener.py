"""Listening for new SARAD instruments appearing on USB or RS-232
(Linux implementation)

Created
    2021-06-08

Authors
    Michael Strey <strey@sarad.de>

.. uml :: uml-linux_usb_listener.puml
"""
import hashlib
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
        self._cluster: SaradCluster = SaradCluster()
        self.connected_instruments = []
        context = pyudev.Context()
        for device in context.list_devices(subsystem="tty"):
            self.usb_device_event("add", device)
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by("tty")
        usb_stick_observer = pyudev.MonitorObserver(monitor, self.usb_device_event)
        usb_stick_observer.start()

    @staticmethod
    def __get_device_hash(device):
        id_model = device.get("ID_MODEL_ID")
        id_vendor = device.get("ID_VENDOR_ID")
        enc_vendor = device.get("ID_VENDOR_ENC")
        if not id_model or not id_vendor or not enc_vendor:
            return None
        identifier_string = id_model + id_vendor + enc_vendor
        return hashlib.sha224(identifier_string.encode("utf-8")).hexdigest()

    def is_valid_device(self, device):
        device_hash = self.__get_device_hash(device)
        if device_hash is not None:
            logger.debug("Device hash: %s", device_hash)
            return True
        return False

    def usb_device_event(self, action, device):
        """docstring"""
        if not self.is_valid_device(device):
            return
        port = device.get("DEVNAME")
        logger.debug("%s device %s", action, port)
        if action == "add":
            try:
                device_id = self._cluster.update_connected_instruments([port])[
                    0
                ].device_id
                logger.debug("Create actor %s", device_id)
                self.connected_instruments.append(
                    {"device_id": device_id, "port": port}
                )
            except IndexError:
                logger.degug("No SARAD instrument at %s", port)
        elif action == "remove":
            for instrument in self.connected_instruments:
                if instrument["port"] == port:
                    logger.debug("Kill actor %s", instrument["device_id"])
                    self.connected_instruments.remove(
                        {"device_id": instrument["device_id"], "port": port}
                    )
        else:
            logger.error("USB device event with action %s", action)


if __name__ == "__main__":

    def signal_handler(_signal, _frame):
        logger.info("Linux USB listener stopped")

    _ = LinuxUsbListener()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.pause()
