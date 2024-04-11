"""Device Actor for an instrument connected via NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from overrides import overrides
from regserver.modules.backend.usb.usb_actor import UsbActor


class ZigBeeDeviceActor(UsbActor):
    """Device Actor for an instrument connected via NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.zigbee_address = 0

    @overrides
    def _setup(self, family_id=None, route=None):
        super()._setup(family_id, route)
        self.zigbee_address = self.instrument.route.zigbee_address

    @overrides
    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        if self.zigbee_address:
            self.instrument.select_channel(self.zigbee_address)
        return super().receiveMsg_ReserveDeviceMsg(msg, sender)

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        if self.zigbee_address:
            self.instrument.close_channel()
        return super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if self.zigbee_address:
            self.instrument.close_channel()
        return super()._kill_myself(register, resurrect)
