"""Main actor of the Registration Server -- implementation for local connection

Created
    2021-06-01

Authors
    Michael Strey <strey@sarad.de>
    Riccardo Förster <foerster@sarad.de>

.. uml :: uml-usb_actor.puml
"""
import json

from overrides import overrides  # type: ignore
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from registrationserver.modules.messages import RETURN_MESSAGES
from thespian.actors import Actor

logger.debug("%s -> %s", __package__, __file__)


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    ACCEPTED_RETURNS = {
        "SETUP": "_return_with_socket",
        "KILL": "_return_from_kill",
        "SEND": "_return_from_send",
    }

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        super().__init__()
        self.instrument = None
        self._cluster = None
        logger.info("USB actor created.")

    @overrides
    def _setup(self, msg, sender) -> None:
        self._cluster = self.createActor(Actor, globalName="cluster")
        self.instrument = self.globalName.split(".")[0]
        try:
            data = json.loads(msg["PAR"])
            serial_port = data["Serial"]
            logger.debug(serial_port)
        except Exception as this_exception:  # pylint: disable=broad-except
            logger.critical(
                "Error during setup of USB device actor %s -- kill actor for a restart",
                this_exception,
            )
            self._kill(msg, sender)
        return super()._setup(msg, sender)

    def _send(self, msg, _sender) -> None:
        cmd = msg["PAR"]["DATA"]
        logger.debug("Actor %s received: %s", self.globalName, cmd)
        self.send(
            self._cluster,
            {"CMD": "SEND", "PAR": {"DATA": cmd, "Instrument": self.instrument}},
        )

    def _return_from_send(self, msg, _sender):
        reply = msg["RESULT"]["DATA"]
        logger.debug("and got reply from instrument: %s", reply)
        return_message = {
            "RETURN": "SEND",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": reply},
        }
        self.send(self.my_redirector, return_message)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument.
        In this dummy we suppose, that the instrument is always available for us.
        """
        self._forward_reservation(True)


if __name__ == "__main__":
    pass
