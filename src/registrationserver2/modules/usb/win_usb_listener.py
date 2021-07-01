"""Process listening for new connected SARAD instruments -- Windows implementation.

Created
    2021-05-17

Author
    Riccardo Foerster <rfoerster@sarad.de>

"""
import json
from typing import List

import win32api  # pylint: disable=import-error
import win32con  # pylint: disable=import-error
import win32gui  # pylint: disable=import-error
from registrationserver2.logger import logger
from registrationserver2.modules.usb.usb_actor import UsbActor
from sarad.cluster import SaradCluster
from serial import Serial
from serial.serialutil import SerialException
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore


class UsbListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments -- Windows implementation."""

    WM_DEVICECHANGE_EVENTS = {
        0x0019: (
            "DBT_CONFIGCHANGECANCELED",
            "A request to change the current configuration (dock or undock) has been canceled.",
        ),
        0x0018: (
            "DBT_CONFIGCHANGED",
            "The current configuration has changed, due to a dock or undock.",
        ),
        0x8006: ("DBT_CUSTOMEVENT", "A custom event has occurred."),
        0x8000: (
            "DBT_DEVICEARRIVAL",
            "A device or piece of media has been inserted and is now available.",
        ),
        0x8001: (
            "DBT_DEVICEQUERYREMOVE",
            (
                "Permission is requested to remove a device or piece of media."
                "Any application can deny this request and cancel the removal."
            ),
        ),
        0x8002: (
            "DBT_DEVICEQUERYREMOVEFAILED",
            "A request to remove a device or piece of media has been canceled.",
        ),
        0x8004: (
            "DBT_DEVICEREMOVECOMPLETE",
            "A device or piece of media has been removed.",
        ),
        0x8003: (
            "DBT_DEVICEREMOVEPENDING",
            "A device or piece of media is about to be removed. Cannot be denied.",
        ),
        0x8005: ("DBT_DEVICETYPESPECIFIC", "A device-specific event has occurred."),
        0x0007: (
            "DBT_DEVNODES_CHANGED",
            "A device has been added to or removed from the system.",
        ),
        0x0017: (
            "DBT_QUERYCHANGECONFIG",
            "Permission is requested to change the current configuration (dock or undock).",
        ),
        0xFFFF: ("DBT_USERDEFINED", "The meaning of this message is user-defined."),
    }

    def __init__(self):
        self._actors = {}
        self._cluster = SaradCluster()

    def _create_listener(self):
        win_class = win32gui.WNDCLASS()
        win_class.lpfnWndProc = self._on_message
        win_class.lpszClassName = self.__class__.__name__
        win_class.hInstance = win32api.GetModuleHandle(None)
        class_atom = win32gui.RegisterClass(win_class)
        return win32gui.CreateWindow(
            class_atom,
            self.__class__.__name__,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            win_class.hInstance,
            None,
        )

    def _process_list(self):
        logger.info("[LIST] Process updated device list")
        logger.info("[LIST] Remove all device actors %s", self._actors)
        for actor in self._actors.values():
            _ = ActorSystem().ask(actor, ActorExitRequest())
        self._actors = {}
        logger.info("[LIST] Creat new device actors")
        for instrument in self._cluster.connected_instruments:
            self._create_actor(instrument)

    def run(self):
        """Start listening for new devices"""
        logger.info("[Start] Windows USB Listener")
        self._cluster.update_connected_instruments()
        self._process_list()
        hwnd = self._create_listener()
        logger.debug("Created listener window with hwnd=%s", hwnd)
        logger.debug("Listening to messages")
        win32gui.PumpMessages()

    def _on_message(self, _hwnd: int, msg: int, wparam: int, _lparam: int):
        if msg == win32con.WM_DEVICECHANGE:
            event, description = self.WM_DEVICECHANGE_EVENTS[wparam]
            logger.info("Received message: %s = %s", event, description)
            if event in ("DBT_DEVICEARRIVAL", "DBT_DEVICEREMOVECOMPLETE"):
                self._cluster.update_connected_instruments()
                self._process_list()

    def _create_actor(self, instrument):
        serial_device = instrument.port
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
        self._actors[serial_device] = ActorSystem().createActor(
            UsbActor, globalName=global_name
        )
        data = json.dumps(
            {
                "Identification": {
                    "Name": instrument.type_name,
                    "Family": family,
                    "Type": instrument.type_id,
                    "Serial number": instrument.serial_number,
                    "Host": "127.0.0.1",
                    "Protocol": sarad_type,
                },
                "Serial": serial_device,
            }
        )
        msg = {"CMD": "SETUP", "PAR": data}
        logger.info("Ask to setup device actor %s with msg %s", global_name, msg)
        _ = ActorSystem().ask(self._actors[serial_device], msg)


if __name__ == "__main__":
    logger.info("Start Test")
    _ = UsbListener()
