import os

if os.name == 'nt':
    import registrationserver2.modules.usb.win_usb_listener
else:
    import registrationserver2.modules.usb.linux_usb_listener
