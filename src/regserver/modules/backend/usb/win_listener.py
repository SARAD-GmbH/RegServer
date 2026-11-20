"""Process listening for new connected SARAD instruments -- Windows implementation.

:Created:
    2021-05-17

:Author:
    | Riccardo Foerster <rfoerster@sarad.de>
    | Michael Strey <strey@sarad.de>

"""

try:
    import win32api  # type: ignore
    import win32con  # type: ignore
    import win32gui  # type: ignore
except ImportError:
    print("Wrong operating system.")
    raise
from time import sleep
from typing import override

from regserver.actor_messages import InstrAddedMsg, InstrRemovedMsg
from regserver.logger import logger
from regserver.modules.backend.usb.base_listener import BaseListener
from thespian.actors import ActorSystem  # type: ignore


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

    @override
    def __init__(self, registrar_actor):
        super().__init__(registrar_actor)
        self.hwnd = None
        self.class_atom = None
        self.hinstance = win32api.GetModuleHandle(None)

    def _create_listener(self):
        win_class = win32gui.WNDCLASS()
        win_class.lpfnWndProc = self._on_message
        win_class.lpszClassName = self.__class__.__name__
        win_class.hInstance = self.hinstance
        self.class_atom = win32gui.RegisterClass(win_class)
        return win32gui.CreateWindow(
            self.class_atom,
            self.__class__.__name__,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            self.hinstance,
            None,
        )

    def run(self, stop_event):
        """Start listening for new devices"""
        self.hwnd = self._create_listener()
        logger.debug("Created listener window with self.hwnd=%s", self.hwnd)
        logger.info("[Start] Windows USB Listener")
        while not stop_event.is_set():
            try:
                win32gui.PumpWaitingMessages()
            except win32gui.error as exception:
                if exception.winerror == 1450:
                    logger.warning(
                        "Windows system resources temporarily exhausted in message loop: %s",
                        exception,
                    )
                    sleep(1.0)
                else:
                    raise
            sleep(0.1)
        self.stop()

    def stop(self):
        """Stop listening."""
        if self.hwnd:
            try:
                win32gui.DestroyWindow(self.hwnd)
            except win32gui.error as exception:
                logger.warning("Error destrying window: %s", exception)
            self.hwnd = None
        if self.class_atom:
            try:
                win32gui.UnregisterClass(self.class_atom, self.hinstance)
            except win32gui.error as exception:
                logger.warning("Error unregistering class: %s", exception)
            self.class_atom = None
        logger.info("Stop listening for USB devices.")

    def _on_message(self, _hwnd: int, msg: int, wparam: int, _lparam: int):
        if msg == win32con.WM_DEVICECHANGE:
            event, description = self.WM_DEVICECHANGE_EVENTS[wparam]
            logger.debug("Received message: %s = %s", event, description)
            if event in ("DBT_DEVICEARRIVAL", "DBT_DEVICEREMOVECOMPLETE"):
                if event in "DBT_DEVICEARRIVAL":
                    ActorSystem().tell(self.cluster_actor, InstrAddedMsg())
                    return 0
                if event in "DBT_DEVICEREMOVECOMPLETE":
                    ActorSystem().tell(self.cluster_actor, InstrRemovedMsg())
            return 0
        return 0
