"""Device Actor for an instrument connected via NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

# from overrides import overrides
from regserver.modules.backend.usb.usb_actor import UsbActor


class ZigBeeDeviceActor(UsbActor):
    """Device Actor for an instrument connected via NetMonitors Coordinator"""
