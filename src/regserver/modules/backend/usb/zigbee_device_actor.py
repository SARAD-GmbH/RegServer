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
from serial import SerialException  # type: ignore


class ZigBeeDeviceActor(UsbActor):
    """Device Actor for an instrument connected via NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.zigbee_address = 0
        self.forwarded_reserve_pending = False
        self.forwarded_free_pending = False

    @overrides
    def _setup(self, family_id=None, route=None):
        super()._setup(family_id, route)
        self.zigbee_address = self.instrument.route.zigbee_address
        self.instrument.release_instrument()
        self.send(self.parent.parent_address, FinishSetupUsbActorMsg())

    @overrides
    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        if sender != self.parent.parent_address:
            logger.info("Forward %s to NetUsbActor", msg)
            self.send(self.parent.parent_address, msg)
            self.forwarded_reserve_pending = True
            has_reservation_section = self.device_status.get("Reservation", False)
            if has_reservation_section:
                is_reserved = self.device_status["Reservation"].get("Active", False)
            else:
                is_reserved = False
            if self.zigbee_address and not is_reserved:
                logger.info("Regular reservation of %s", self.my_id)
                self.instrument.select_channel(self.zigbee_address)
                super().receiveMsg_ReserveDeviceMsg(msg, sender)
            elif is_reserved:
                logger.info("%s occupied", self.my_id)
                self.reserve_lock = datetime.now()
                if self.sender_api is None:
                    self.sender_api = sender
                self.return_message = ReservationStatusMsg(
                    instr_id=self.instr_id, status=Status.OCCUPIED
                )
                self._update_reservation_status(self.device_status["Reservation"])
                self._send_reservation_status_msg()
                self.sender_api = None
        elif self.forwarded_reserve_pending:
            logger.info(
                "The ReserveDeviceMsg for %s is comming from NetUsbActor", self.my_id
            )
            self.forwarded_reserve_pending = False
        else:
            logger.info("Another ZigBee instrument is blocking %s", self.my_id)
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
            self._publish_status_change()
            self.sender_api = None

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        if sender != self.parent.parent_address:
            logger.info("Forward %s to NetUsbActor", msg)
            self.send(self.parent.parent_address, msg)
            self.forwarded_free_pending = True
            if self.zigbee_address:
                try:
                    self.instrument.close_channel()
                except SerialException as exception:
                    logger.warning("Freeing %s caused %s", self.my_id, exception)
            super().receiveMsg_FreeDeviceMsg(msg, sender)
        elif self.forwarded_free_pending:
            self.forwarded_free_pending = False
        else:
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
