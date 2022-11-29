"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

.. uml :: uml-usb_actor.puml
"""

from datetime import datetime
from typing import Union

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (Gps, KillMsg, RecentValueMsg,
                                               RxBinaryMsg, Status)
from registrationserver.config import usb_backend_config
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from sarad.dacm import DacmInst  # type: ignore
from sarad.doseman import DosemanInst  # type: ignore
from sarad.radonscout import RscInst  # type: ignore
from sarad.sari import SaradInst  # type: ignore
from serial import SerialException  # type: ignore

# logger.debug("%s -> %s", __package__, __file__)


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        super().__init__()
        self.mqtt_scheduler = None
        self.instrument: Union[SaradInst, None] = None

    def receiveMsg_SetupUsbActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the SaradInst object for serial communication."""
        logger.debug(
            "SetUsbActorMsg(route=%s, family=%d) for %s from %s",
            msg.route,
            msg.family["family_id"],
            self.my_id,
            sender,
        )
        family_id = msg.family["family_id"]
        if family_id == 1:
            family_class = DosemanInst
        elif family_id == 2:
            family_class = RscInst
        elif family_id == 5:
            family_class = DacmInst
        else:
            logger.error("Family %s not supported", family_id)
            return None
        self.instrument = family_class()
        self.instrument.route = msg.route
        self.instrument.release_instrument()
        logger.info("Instrument with Id %s detected.", self.my_id)
        native_ports = set(usb_backend_config["NATIVE_SERIAL_PORTS"])
        if self.instrument.route.port in native_ports:
            self.wakeupAfter(usb_backend_config["LOCAL_RETRY_INTERVAL"])
        return None

    def receiveMsg_WakeupMessage(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        logger.debug("Wakeup %s", self.my_id)
        try:
            is_reserved = self.device_status["Reservation"]["Active"]
        except KeyError:
            is_reserved = False
        if (not self.on_kill) and (not is_reserved):
            logger.info("Check if %s is still connected", self.my_id)
            if not self.instrument.get_description():
                logger.info("Killing myself")
                self.send(self.myAddress, KillMsg())
        self.wakeupAfter(usb_backend_config["LOCAL_RETRY_INTERVAL"])

    def dummy_reply(self, data, sender) -> bool:
        """Filter TX message and give a dummy reply.

        This function was invented in order to prevent messages destined for
        the WLAN module to be sent to the instrument.
        """
        tx_rx = {b"B\x80\x7f\xe6\xe6\x00E": b"B\x80\x7f\xe7\xe7\x00E"}
        if data in tx_rx:
            logger.debug("Reply %s with %s", data, tx_rx[data])
            self.send(sender, RxBinaryMsg(tx_rx[data]))
            return True
        return False

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for binary message from App to Instrument."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        if self.dummy_reply(msg.data, sender):
            return
        emergency = False
        try:
            reply = self.instrument.get_message_payload(msg.data, timeout=1)
        except (SerialException, OSError):
            logger.error("Connection to %s lost", self.instrument)
            reply = {"is_valid": False, "is_last_frame": True}
            emergency = True
        logger.debug("Instrument replied %s", reply)
        if reply["is_valid"]:
            self.send(sender, RxBinaryMsg(reply["standard_frame"]))
            while not reply["is_last_frame"]:
                try:
                    reply = self.instrument.get_next_payload(timeout=1)
                    self.send(sender, RxBinaryMsg(reply["standard_frame"]))
                except (SerialException, OSError):
                    logger.error("Connection to %s lost", self.my_id)
                    reply = {"is_valid": False, "is_last_frame": True}
                    emergency = True
        if emergency:
            logger.info("Killing myself")
            self.send(self.myAddress, KillMsg())
        elif not reply["is_valid"]:
            logger.warning("Invalid binary message from instrument.")
            self.send(sender, RxBinaryMsg(reply["raw"]))

    @overrides
    def _request_reserve_at_is(self):
        # pylint: disable=unused-argument
        """Reserve the requested instrument.
        In this dummy we suppose, that the instrument is always available for us.
        """
        self._handle_reserve_reply_from_is(Status.OK)

    def receiveMsg_GetRecentValueMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Get a value from a DACM instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        try:
            reply = self.instrument.get_recent_value(
                msg.component, msg.sensor, msg.measurand
            )
        except IndexError:
            answer = RecentValueMsg(status=Status.INDEX_ERROR)
            self.send(sender, answer)
            return
        logger.debug(
            "get_recent_value(%d, %d, %d) came back with %s",
            msg.component,
            msg.sensor,
            msg.measurand,
            reply,
        )
        if reply:
            if reply.get("gps") is None:
                gps = Gps(valid=False)
            else:
                gps = Gps(
                    valid=reply["gps"]["valid"],
                    latitude=reply["gps"]["latitude"],
                    longitude=reply["gps"]["longitude"],
                    altitude=reply["gps"]["altitude"],
                    deviation=reply["gps"]["deviation"],
                )
            if msg.measurand:
                timestamp = reply["datetime"]
            else:
                timestamp = datetime.utcnow()
            answer = RecentValueMsg(
                component_name=reply["component_name"],
                sensor_name=reply["sensor_name"],
                measurand_name=reply["measurand_name"],
                measurand=reply["measurand"],
                operator=reply["measurand_operator"],
                value=reply["value"],
                unit=reply["measurand_unit"],
                timestamp=timestamp,
                gps=gps,
                status=Status.OK,
            )
        else:
            answer = RecentValueMsg(status=Status.INDEX_ERROR)
        self.send(sender, answer)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        self.instrument.release_instrument()
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        self.instrument.release_instrument()
        super().receiveMsg_KillMsg(msg, sender)


if __name__ == "__main__":
    pass
