"""
Created on 17.05.2021

@author: rfoerster
"""
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Callable, List

# import registrationserver2.modules.usb.usb_actor

import win32api
import win32con
import win32gui
from keyboard._nixkeyboard import device

from thespian.actors import ActorSystem

from registrationserver2.modules.usb.win_usb_manager import WinUsbManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class USBSerial:
    deviceid: str
    path: str


class USBListener:
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
            "Permission is requested to remove a device or piece of media. Any application can deny this request and cancel the removal.",
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
        self._actor = ActorSystem().createActor(WinUsbManager, globalName="USBListener")
        ActorSystem().tell(
            self._actor, {"CMD": "PROCESS_LIST", "DATA": {"list": list()}}
        )

    def _create_listener(self):
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._on_message
        wc.lpszClassName = self.__class__.__name__
        wc.hInstance = win32api.GetModuleHandle(None)
        class_atom = win32gui.RegisterClass(wc)
        return win32gui.CreateWindow(
            class_atom, self.__class__.__name__, 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

    def start(self):
        logger.info(f"Listening to drive changes")
        hwnd = self._create_listener()
        logger.debug(f"Created listener window with hwnd={hwnd:x}")
        logger.debug(f"Listening to messages")
        win32gui.PumpMessages()

    def on_change(self, devices: List[USBSerial]):
        for device in devices:
            logger.info(f"Connected usb device {vars(device)}")

    def _on_message(self, hwnd: int, msg: int, wparam: int, lparam: int):
        # logger.info(f'_on_message(hwnd={hwnd}: int, msg={hex(msg)}: int, wparam={wparam}: int, lparam={lparam}: int)')
        if msg != win32con.WM_DEVICECHANGE:
            return 0

        event, description = self.WM_DEVICECHANGE_EVENTS[wparam]
        logger.debug(f"Received message: {event} = {description}")
        ActorSystem().tell(
            self._actor, {"CMD": "PROCESS_LIST", "DATA": {"list": list()}}
        )

    @staticmethod
    def list() -> List[USBSerial]:
        proc = subprocess.run(
            args=[
                "powershell",
                "-noprofile",
                "-command",
                "Get-WmiObject -Class win32_serialport | Select-Object deviceid | ConvertTo-Json",
            ],
            text=True,
            stdout=subprocess.PIPE,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            logger.error("Failed to enumerate drives")
            return []
        devices = json.loads(proc.stdout)

        return [
            USBSerial(deviceid=d["deviceid"], path=fr'\\.\{d["deviceid"]}')
            for d in devices
        ]

    # creating actors here if needed


if __name__ == "__main__":
    listener = USBListener()
    listener.start()
