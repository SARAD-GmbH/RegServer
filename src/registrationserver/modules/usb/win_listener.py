"""Process listening for new connected SARAD instruments -- Windows implementation.

Created
    2021-05-17

Author
    Riccardo Foerster <rfoerster@sarad.de>

"""

import win32api  # pylint: disable=import-error
import win32con  # pylint: disable=import-error
import win32gui  # pylint: disable=import-error
from overrides import overrides  # type: ignore
from registrationserver.logger import logger
from registrationserver.modules.usb.base_listener import BaseListener
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore


class UsbListener(BaseListener):
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

    @overrides
    def run(self):
        """Start listening for new devices"""
        logger.info("[Start] Windows USB Listener")
        self._cluster.update_connected_instruments()
        self._actors = {}
        logger.info("[LIST] Creat new device actors")
        for instrument in self._cluster.connected_instruments:
            self._create_actor(instrument)
        hwnd = self._create_listener()
        logger.debug("Created listener window with hwnd=%s", hwnd)
        logger.debug("Listening to messages")
        win32gui.PumpMessages()
        super().run()

    def _on_message(self, _hwnd: int, msg: int, wparam: int, _lparam: int):
        if msg == win32con.WM_DEVICECHANGE:
            event, description = self.WM_DEVICECHANGE_EVENTS[wparam]
            logger.debug("Received message: %s = %s", event, description)
            old_active_ports = set(self._actors.keys())
            if event in "DBT_DEVICEARRIVAL":
                logger.info("Old active ports: %s", old_active_ports)
                logger.info("New active ports: %s", set(self._cluster.active_ports))
                new_ports = set(self._cluster.active_ports).difference(old_active_ports)
                logger.info("%s plugged in", new_ports)
                new_instruments = self._cluster.update_connected_instruments(
                    list(new_ports)
                )
                for instrument in new_instruments:
                    self._create_actor(instrument)
                return
            if event in "DBT_DEVICEREMOVECOMPLETE":
                gone_ports = set(self._actors.keys()).difference(old_active_ports)
                logger.info("%s plugged out", gone_ports)
                self._cluster.update_connected_instruments(list(gone_ports))
                current_active_ports = set(
                    instr.port for instr in self._cluster.connected_instruments
                )
                for gone_port in gone_ports:
                    try:
                        ActorSystem().tell(self._actors[gone_port], ActorExitRequest())
                        self._actors.pop(gone_port, None)
                    except KeyError:
                        logger.error(
                            "%s removed, that never was added properly", gone_port
                        )
                try:
                    assert current_active_ports == set(self._actors.keys())
                except AssertionError:
                    logger.error(
                        "%s must be equal to %s",
                        current_active_ports,
                        set(self._actors.keys()),
                    )
            return


if __name__ == "__main__":
    logger.info("Start Test")
    _ = UsbListener()
