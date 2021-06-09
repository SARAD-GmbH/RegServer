"""
Created on 09.06.2021

@author: rfoerster
"""
import os
import registrationserver2.modules.usb

if os.name == "nt":
    registrationserver2.modules.usb.UsbListener = (
        registrationserver2.modules.usb.win_usb_listener.WinUsbListener
    )
else:
    registrationserver2.modules.usb.UsbListener = (
        registrationserver2.modules.usb.linux_usb_listener.LinuxUsbListener
    )
