"""
Created on 09.06.2021

@author: rfoerster
"""
import os

from registrationserver2 import logger

UsbListener = None

if os.name == "nt":
    import registrationserver2.modules.usb.win_usb_listener

    registrationserver2.modules.usb.usb_actor.UsbListener = (
        registrationserver2.modules.usb.win_usb_listener.WinUsbListener
    )

    logger.debug("Detected Windows")

else:
    logger.debug("Assuming Linux")
    import registrationserver2.modules.usb.linux_usb_listener

    registrationserver2.modules.usb.usb_actor.UsbListener = (
        registrationserver2.modules.usb.linux_usb_listener.LinuxUsbListener
    )
