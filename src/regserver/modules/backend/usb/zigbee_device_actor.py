"""Device Actor for an instrument connected via NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from copy import deepcopy
from datetime import datetime, timezone
from threading import Thread

from overrides import overrides
from regserver.actor_messages import (FinishSetupUsbActorMsg, FreeDeviceMsg,
                                      ReservationStatusMsg, SetDeviceStatusMsg,
                                      Status)
from regserver.config import config, local_backend_config
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor
from sarad.global_helpers import get_sarad_type  # type: ignore
from sarad.mapping import id_family_mapping  # type: ignore
from serial import SerialException  # type: ignore

SER_TIMEOUT = 10


class ZigBeeDeviceActor(UsbActor):
    """Device Actor for an instrument connected via NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.zigbee_address = 0
        self.forwarded_reserve_pending = False
        self.forwarded_free_pending = False
        self.select_channel_thread = Thread(
            target=self._select_channel,
            kwargs={"msg": None, "sender": None},
            daemon=True,
        )
        self.close_channel_thread = Thread(target=self._close_channel, daemon=True)

    @overrides
    def _setup(self, family_id=None, route=None):
        self.instrument = id_family_mapping.get(family_id)
        if family_id == 5:
            family_dict = dict(self.instrument.family)
            family_dict["serial"] = [
                d for d in family_dict["serial"] if d["baudrate"] == 9600
            ]
            self.instrument.family = family_dict
            logger.debug(
                "With ZigBee we are using only %s", self.instrument.family["serial"]
            )
        self.instrument._ser_timeout = SER_TIMEOUT  # pylint: disable=protected-access
        self.instrument.ext_ser_timeout = SER_TIMEOUT
        try:
            self.instrument.route = route
        except SerialException as exception:
            logger.error("Exception during setup of %s: %s", self.my_id, exception)
            self.instrument.type_id = 0
        if self.instrument.type_id == 0:
            logger.error("Setup of ZigBee Actor failed")
            self.send(self.parent.parent_address, FinishSetupUsbActorMsg(success=False))
        else:
            if local_backend_config["SET_RTC"]:
                self._request_set_rtc_at_is()
            device_status = {
                "Identification": {
                    "Name": self.instrument.type_name,
                    "Family": family_id,
                    "Type": self.instrument.type_id,
                    "Serial number": self.instrument.serial_number,
                    "Firmware version": self.instrument.software_version,
                    "Host": "127.0.0.1",
                    "Protocol": get_sarad_type(self.instr_id),
                    "IS Id": config["IS_ID"],
                },
                "Serial": self.instrument.route.port,
                "State": 2,
            }
            self.receiveMsg_SetDeviceStatusMsg(SetDeviceStatusMsg(device_status), self)
            logger.debug("Instrument with Id %s detected.", self.my_id)
            self.zigbee_address = self.instrument.route.zigbee_address
            self.instrument.release_instrument()
            self.send(self.parent.parent_address, FinishSetupUsbActorMsg(success=True))

    @overrides
    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if sender != self.parent.parent_address:
            logger.debug("Forward %s to NetUsbActor", msg)
            self.send(self.parent.parent_address, msg)
            self.forwarded_reserve_pending = True
            has_reservation_section = self.device_status.get("Reservation", False)
            if has_reservation_section:
                is_reserved = self.device_status["Reservation"].get("Active", False)
            else:
                is_reserved = False
            if self.zigbee_address and not is_reserved:
                logger.debug("Regular reservation of %s", self.my_id)
                if not self.select_channel_thread.is_alive():
                    self.select_channel_thread = Thread(
                        target=self._select_channel,
                        kwargs={"msg": msg, "sender": sender},
                        daemon=True,
                    )
                    self.select_channel_thread.start()
            elif is_reserved:
                logger.debug("%s occupied", self.my_id)
                self.request_locks["Reserve"].locked = True
                self.request_locks["Reserve"].time = datetime.now()
                self.request_locks["Reserve"].requester = sender
                self.return_message = ReservationStatusMsg(
                    instr_id=self.instr_id, status=Status.OCCUPIED
                )
                self._update_reservation_status(self.device_status["Reservation"])
                self._send_reservation_status_msg()
        elif self.forwarded_reserve_pending:
            logger.debug(
                "The ReserveDeviceMsg for %s is comming from NetUsbActor", self.my_id
            )
            self.forwarded_reserve_pending = False
        else:
            logger.debug("Another ZigBee instrument is blocking %s", self.my_id)
            self.request_locks["Reserve"].requester = sender
            self.reserve_device_msg = deepcopy(msg)
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

    def _select_channel(self, msg, sender):
        self.instrument.select_channel(self.zigbee_address)
        self.instrument.release_instrument()
        super().receiveMsg_ReserveDeviceMsg(msg, sender)

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        if sender != self.parent.parent_address:
            logger.debug("Forward %s to NetUsbActor", msg)
            self.send(self.parent.parent_address, msg)
            self.forwarded_free_pending = True
            if self.zigbee_address:
                if not self.close_channel_thread.is_alive():
                    self.close_channel_thread = Thread(
                        target=self._close_channel, daemon=True
                    )
                    self.close_channel_thread.start()
            super().receiveMsg_FreeDeviceMsg(msg, sender)
        elif self.forwarded_free_pending:
            self.forwarded_free_pending = False
        else:
            super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved or self.request_locks["Reserve"].locked:
            self.send(self.parent.parent_address, FreeDeviceMsg())
        if self.zigbee_address:
            if not self.close_channel_thread.is_alive():
                self.close_channel_thread = Thread(
                    target=self._close_channel, daemon=True
                )
                self.close_channel_thread.start()
        return super()._kill_myself(register, resurrect)

    def _close_channel(self):
        try:
            self.instrument.release_instrument()
            self.instrument.close_channel()
            self.instrument.release_instrument()
        except (SerialException, TypeError) as exception:
            logger.warning("%s during _close_channel from %s", exception, self.my_id)

    @overrides
    def receiveMsg_SetupUsbActorMsg(self, msg, sender):
        logger.debug("Setup ZigBeeDeviceActor %s", self.my_id)
        super().receiveMsg_SetupUsbActorMsg(msg, sender)
