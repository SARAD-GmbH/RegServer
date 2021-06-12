"""Listening for new SARAD instruments appearing on USB or RS-232
(Linux implementation)

Created
    2021-06-08

Authors
    Michael Strey <strey@sarad.de>

.. uml :: uml-linux_usb_listener.puml
"""
import hashlib
import json
import signal
import sys

import pyudev  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.modules.usb.usb_actor import UsbActor
from sarad.cluster import SaradCluster
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore

logger.info("%s -> %s", __package__, __file__)


class LinuxUsbListener:
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

    def __init__(self):
        logger.info("Linux USB listener started")
        self._cluster: SaradCluster = SaradCluster()
        self.connected_instruments = []

    def run(self):
        """Start listening and keep listening until SIGTERM or SIGINT"""
        context = pyudev.Context()
        for device in context.list_devices(subsystem="tty"):
            self.usb_device_event("add", device)
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by("tty")
        usb_stick_observer = pyudev.MonitorObserver(monitor, self.usb_device_event)
        usb_stick_observer.start()

    def is_valid_device(self, device):
        """Check whether there is a physical device connected to the logical interface."""
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
                instrument = self._cluster.update_connected_instruments([port])[0]
                family = instrument.family["family_id"]
                device_id = instrument.device_id
                if family == 5:
                    sarad_type = "sarad-dacm"
                elif family in [1, 2]:
                    sarad_type = "sarad-1688"
                else:
                    logger.error(
                        "[Add Instrument]: unknown instrument family (index: %s)",
                        family,
                    )
                    sarad_type = "unknown"
                global_name = f"{device_id}.{sarad_type}.local"
                logger.debug("Create actor %s", global_name)
                self.connected_instruments.append(
                    {"global_name": global_name, "port": port}
                )
                this_actor = ActorSystem().createActor(UsbActor, globalName=global_name)
                data = json.dumps(
                    {
                        "Identification": {
                            "Name": instrument.type_name,
                            "Family": family,
                            "Type": instrument.type_id,
                            "Serial number": instrument.serial_number,
                            "Host": "127.0.0.1",
                            "Protocol": sarad_type,
                        }
                    }
                )
                msg = {"CMD": "SETUP", "PAR": data}
                logger.debug("Ask to setup the device actor with %s...", msg)
                setup_return = ActorSystem().ask(this_actor, msg)
                if not setup_return["ERROR_CODE"] in (
                    RETURN_MESSAGES["OK"]["ERROR_CODE"],
                    RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
                ):
                    logger.critical("Adding a new service failed. Kill device actor.")
                    ActorSystem().tell(this_actor, ActorExitRequest())
            except IndexError:
                logger.degug("No SARAD instrument at %s", port)
        elif action == "remove":
            for instrument in self.connected_instruments:
                if instrument["port"] == port:
                    logger.debug("Kill actor %s", instrument["global_name"])
                    self.connected_instruments.remove(
                        {"global_name": instrument["global_name"], "port": port}
                    )
                    this_actor = ActorSystem().createActor(
                        UsbActor, globalName=instrument["global_name"]
                    )
                    logger.debug("Ask to kill the device actor...")
                    kill_return = ActorSystem().ask(this_actor, ActorExitRequest())
                    if (
                        not kill_return["ERROR_CODE"]
                        == RETURN_MESSAGES["OK"]["ERROR_CODE"]
                    ):
                        logger.critical("Killing the device actor failed.")
        else:
            logger.error("USB device event with action %s", action)


if __name__ == "__main__":
    logger.info("Start Test")
    _ = LinuxUsbListener()
