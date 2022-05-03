"""Listening for new SARAD instruments appearing on USB or RS-232
(Linux implementation)

:Created:
    2021-06-08

:Author:
    | Michael Strey <strey@sarad.de>

.. uml :: uml-unix_listener.puml
"""
import hashlib

import pyudev  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import InstrAddedMsg, InstrRemovedMsg
from registrationserver.logger import logger
from registrationserver.modules.usb.base_listener import BaseListener
from thespian.actors import ActorSystem  # type: ignore

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
    def __init__(self, registrar_actor):
        super().__init__(registrar_actor)
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by("tty")
        self._usb_stick_observer = pyudev.MonitorObserver(
            monitor, self.usb_device_event
        )

    def run(self):
        """Start listening and keep listening until SIGTERM or SIGINT or stop()"""
        self._usb_stick_observer.start()
        logger.debug("Start listening for USB devices.")

    def stop(self):
        """Stop listening."""
        self._usb_stick_observer.stop()
        logger.debug("Stop listening for USB devices.")

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
            ActorSystem().tell(
                self.cluster_actor,
                InstrAddedMsg(),
            )
        elif action == "remove":
            ActorSystem().tell(
                self.cluster_actor,
                InstrRemovedMsg(),
            )
        else:
            logger.error("USB device event with action %s", action)
