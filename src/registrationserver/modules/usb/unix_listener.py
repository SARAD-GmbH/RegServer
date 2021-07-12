"""Listening for new SARAD instruments appearing on USB or RS-232
(Linux implementation)

Created
    2021-06-08

Authors
    Michael Strey <strey@sarad.de>

.. uml :: uml-unix_listener.puml
"""
import hashlib

import pyudev  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.logger import logger
from registrationserver.modules.usb.base_listener import BaseListener
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore

logger.debug("%s -> %s", __package__, __file__)


class UsbListener(BaseListener):
    """Class to listen for SARAD instruments connected via USB."""

    @staticmethod
    def __get_device_hash(device):
        id_model = device.get("ID_MODEL_ID")
        id_vendor = device.get("ID_VENDOR_ID")
        enc_vendor = device.get("ID_VENDOR_ENC")
        if not id_model or not id_vendor or not enc_vendor:
            return None
        identifier_string = id_model + id_vendor + enc_vendor
        return hashlib.sha224(identifier_string.encode("utf-8")).hexdigest()

    @overrides
    def run(self):
        """Start listening and keep listening until SIGTERM or SIGINT"""
        context = pyudev.Context()
        for device in context.list_devices(subsystem="tty"):
            self.usb_device_event("add", device)
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by("tty")
        usb_stick_observer = pyudev.MonitorObserver(monitor, self.usb_device_event)
        usb_stick_observer.start()
        super().run()

    def is_valid_device(self, device):
        """Check whether there is a physical device connected to the logical interface."""
        device_hash = self.__get_device_hash(device)
        if device_hash is not None:
            logger.debug("Device hash: %s", device_hash)
            return True
        return False

    def usb_device_event(self, action, device):
        """Handler that will be carried out, when a new serial device is detected"""
        if not self.is_valid_device(device):
            return
        port = device.get("DEVNAME")
        logger.debug("%s device %s", action, port)
        if action == "add":
            try:
                instrument = self._cluster.update_connected_instruments([port])[0]
                self._create_actor(instrument)
            except IndexError:
                logger.debug("No SARAD instrument at %s", port)
        elif action == "remove":
            for active_port in self._actors:
                if active_port == port:
                    self._remove_actor(active_port)
        else:
            logger.error("USB device event with action %s", action)


if __name__ == "__main__":
    logger.debug("Start Test")
    _ = UsbListener()
