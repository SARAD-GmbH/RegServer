"""Device Actor for an instrument connected via NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from datetime import datetime, timezone

from overrides import overrides
from regserver.actor_messages import (FinishSetupUsbActorMsg,
                                      ReservationStatusMsg, Status)
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor
from serial import SerialException


class ZigBeeDeviceActor(UsbActor):
    """Device Actor for an instrument connected via NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.zigbee_address = 0
        self.setup_msg = None
        self.setup_sender = None

    @overrides
    def _setup(self, family_id=None, route=None):
        super()._setup(family_id, route)
        self.zigbee_address = self.instrument.route.zigbee_address
        self.instrument.release_instrument()
        self.send(self.parent.parent_address, FinishSetupUsbActorMsg())

    @overrides
    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        if sender == self:
            return
        if sender != self.parent.parent_address:
            logger.info("Forward %s to NetUsbActor", msg)
            self.send(self.parent.parent_address, msg)
            if self.zigbee_address:
                self.instrument.select_channel(self.zigbee_address)
            super().receiveMsg_ReserveDeviceMsg(msg, sender)
        else:
            if self.sender_api is None:
                self.sender_api = sender
            self.reserve_device_msg = msg
            self.return_message = ReservationStatusMsg(
                instr_id=self.instr_id, status=Status.OCCUPIED
            )
            reservation = {
                "Active": True,
                "App": self.reserve_device_msg.app,
                "Host": self.reserve_device_msg.host,
                "User": self.reserve_device_msg.user,
                "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._update_reservation_status(reservation)
            self._send_reservation_status_msg()

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        if sender == self:
            return
        if self.zigbee_address:
            self.instrument.close_channel()
        if sender != self.parent.parent_address:
            logger.info("Forward %s to NetUsbActor", msg)
            self.send(self.parent.parent_address, msg)
        super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if self.zigbee_address:
            try:
                self.instrument.close_channel()
            except SerialException:
                pass
        return super()._kill_myself(register, resurrect)

    @overrides
    def receiveMsg_SetupUsbActorMsg(self, msg, sender):
        logger.info("Setup ZigBeeDeviceActor %s", self.my_id)
        super().receiveMsg_SetupUsbActorMsg(msg, sender)
