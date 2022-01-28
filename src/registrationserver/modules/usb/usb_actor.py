"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

.. uml :: uml-usb_actor.puml
"""

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (AppType, FreeInstrMsg,
                                               TxBinaryMsg)
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor

logger.debug("%s -> %s", __package__, __file__)


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        super().__init__()
        self.instrument = None
        logger.info("USB actor created.")

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.instrument = self.my_id.split(".")[0]

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward binary message from App to cluster actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        cluster_actor = self.parent.parent_address
        self.send(cluster_actor, TxBinaryMsg(msg.data, msg.host, self.instrument))

    def receiveMsg_RxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward binary message from cluster actor to App."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.app_type == AppType.ISMQTT:
            self.send(self.mqtt_scheduler, msg)
        elif self.app_type == AppType.RS:
            self.send(self.redirector_actor(), msg)
        else:
            # reserved for future use
            self.send(self.redirector_actor(), msg)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument.
        In this dummy we suppose, that the instrument is always available for us.
        """
        self._forward_reservation(True)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        cluster_actor = self.parent.parent_address
        self.send(cluster_actor, FreeInstrMsg(self.instrument))
        super().receiveMsg_ChildActorExited(msg, sender)


if __name__ == "__main__":
    pass
