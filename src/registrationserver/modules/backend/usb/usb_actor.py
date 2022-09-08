"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

.. uml :: uml-usb_actor.puml
"""

from typing import Union

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import KillMsg, RxBinaryMsg, Status
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from sarad.sari import SaradInst  # type: ignore
from serial import SerialException  # type: ignore

logger.debug("%s -> %s", __package__, __file__)


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
            "SetUsbActorMsg(port=%s, family=%d) for %s from %s",
            msg.port,
            msg.family["family_id"],
            self.my_id,
            sender,
        )
        self.instrument = SaradInst(msg.family)
        self.instrument.port = msg.port
        self.instrument.release_instrument()
        logger.info("Instrument with Id %s detected.", self.my_id)

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
            self.send(sender, RxBinaryMsg(reply["raw"]))
            while not reply["is_last_frame"]:
                try:
                    reply = self.instrument.get_next_payload(timeout=1)
                    self.send(sender, RxBinaryMsg(reply["raw"]))
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
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument.
        In this dummy we suppose, that the instrument is always available for us.
        """
        self._forward_reservation(Status.OK)

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
