"""Process listening for new connected SARAD instruments -- Windows implementation.

Created
    2021-05-17

Author
    Riccardo Foerster <rfoerster@sarad.de>

"""
import json

from registrationserver.logger import logger
from registrationserver.modules.usb.usb_actor import UsbActor
from thespian.actors import (Actor, ActorExitRequest,  # type: ignore
                             ActorSystem)


class BaseListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments
    -- base for OS specific implementations."""

    def __init__(self):

        self._actors = {}
        self._system = ActorSystem()
        self._cluster = self._system.createActor(Actor, globalName="cluster")

    def run(self):
        """Start listening for new devices"""
        self._system.tell(self._cluster, {"CMD": "DO_LOOP"})

    def _create_actor(self, instrument):
        serial_device = instrument["Serial Device"]
        family = instrument["Family"]
        device_id = instrument["Device ID"]
        if family == 5:
            sarad_type = "sarad-dacm"
        elif family in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "[Add Instrument]: unknown instrument family (index: %s)",
                family,
            )
            sarad_type = "unknown"
        global_name = f"{device_id}.{sarad_type}.local"
        logger.debug("Create actor %s", global_name)
        self._actors[serial_device] = self._system.createActor(
            UsbActor, globalName=global_name
        )
        data = json.dumps(
            {
                "Identification": {
                    "Name": instrument["Name"],
                    "Family": family,
                    "Type": instrument["Type"],
                    "Serial number": instrument["Serial number"],
                    "Host": "127.0.0.1",
                    "Protocol": sarad_type,
                },
                "Serial": serial_device,
            }
        )
        msg = {"CMD": "SETUP", "PAR": data}
        logger.info("Ask to setup device actor %s with msg %s", global_name, msg)
        ActorSystem().ask(self._actors[serial_device], msg)

    def _remove_actor(self, gone_port):
        if gone_port in self._actors:
            try:
                self._system.ask(self._actors[gone_port], ActorExitRequest())
                self._actors.pop(gone_port, None)
            except KeyError:
                logger.error("%s removed, that never was added properly", gone_port)
        else:
            logger.error(
                "Tried to remove %s, that never was added properly.", gone_port
            )
