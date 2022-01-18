"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

.. uml :: uml-usb_actor.puml
"""

from overrides import overrides  # type: ignore
from registrationserver.config import AppType, config
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.shutdown import system_shutdown
from thespian.actors import Actor

logger.debug("%s -> %s", __package__, __file__)


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        self.ACCEPTED_RETURNS.update(
            {
                "SEND": "_on_send_return",
            }
        )
        super().__init__()
        self.instrument = None
        self._cluster = None
        logger.info("USB actor created.")

    @overrides
    def _on_setup_cmd(self, msg, sender) -> None:
        super()._on_setup_cmd(msg, sender)
        self._cluster = self.createActor(Actor, globalName="cluster")
        self.instrument = self.my_id.split(".")[0]
        try:
            data = msg["PAR"]
            serial_port = data["Serial"]
            logger.debug(serial_port)
        except Exception as this_exception:  # pylint: disable=broad-except
            logger.critical(
                "Error during setup of USB device actor %s -- system shutdown",
                this_exception,
            )
            system_shutdown()

    def _on_send_cmd(self, msg, _sender) -> None:
        cmd = msg["PAR"]["DATA"]
        logger.debug("Actor received: %s", cmd)
        self.send(
            self._cluster,
            {"CMD": "SEND", "PAR": {"DATA": cmd, "Instrument": self.instrument}},
        )

    def _on_send_return(self, msg, _sender):
        reply = msg["RESULT"]["DATA"]
        logger.debug("and got reply from instrument: %s", reply)
        return_message = {
            "RETURN": "SEND",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": reply},
        }
        if config["APP_TYPE"] == AppType.ISMQTT:
            self.send(self.mqtt_scheduler, return_message)
        elif config["APP_TYPE"] == AppType.RS:
            self.send(self.my_redirector, return_message)
        else:
            # TODO: Actually there is no else yet.
            self.send(self.my_redirector, return_message)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument.
        In this dummy we suppose, that the instrument is always available for us.
        """
        self._forward_reservation(True)

    @overrides
    def _on_kill_return(self, msg, sender):
        super()._on_kill_return(msg, sender)
        free_cmd = {"CMD": "FREE", "PAR": {"Instrument": self.instrument}}
        logger.debug("Send %s to %s", free_cmd, self._cluster)
        self.send(self._cluster, free_cmd)


if __name__ == "__main__":
    pass
