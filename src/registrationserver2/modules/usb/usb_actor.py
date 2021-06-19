"""Main actor of the Registration Server -- implementation for local connection

Created
    2021-06-01

Authors
    Michael Strey <strey@sarad.de>
    Riccardo Förster <foerster@sarad.de>,

.. uml :: uml-usb_actor.puml
"""
import json

import sarad.cluster
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.messages import RETURN_MESSAGES

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
    def _setup(self, msg: dict, sender) -> None:
        instrument_id = self.globalName.split(".")[0]
        try:
            data = json.loads(msg["PAR"])
            serial_port = data["Serial"]
            logger.info(serial_port)
            mycluster: sarad.cluster.SaradCluster = sarad.cluster.SaradCluster()
            mycluster.update_connected_instruments([serial_port])
            self.instrument = mycluster.connected_instruments[0]
            assert instrument_id == self.instrument
        except Exception:  # pylint: disable=broad-except
            logger.critical(
                "Error during setup of USB device actor -- kill actor for a restart"
            )
            self._kill(msg, sender)
        return super()._setup(msg, sender)

    def _send(self, msg: dict, _sender) -> None:
        cmd = msg["PAR"]["DATA"]
        logger.debug("Actor %s received: %s", self.globalName, cmd)
        reply = self.instrument.get_transparent_reply(
            cmd, reply_length=134, timeout=0.1
        )
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
