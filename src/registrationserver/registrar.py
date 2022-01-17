"""Module providing an actor to keep a list of device actors. The list is
provided as dictionary of form {global_name: actor_address}. The actor is a
singleton in the actor system and was introduced as a replacement for the
formerly used device files.

All status information about present instruments can be obtained from the
device actors referenced in the dictionary.

:Created:
    2021-12-15

:Author:
    | Michael Strey <strey@sarad.de>

"""

from typing import Dict

from overrides import overrides  # type: ignore
from thespian.actors import DeadEnvelope  # type: ignore

from registrationserver.base_actor import BaseActor
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown


class Registrar(BaseActor):
    """Actor providing a dictionary of devices"""

    ACCEPTED_COMMANDS = {
        "READ": "_read",
        "SETUP": "_setup",
        "SUBSCRIBE": "_subscribe",
        "UNSUBSCRIBE": "_unsubscribe",
    }

    ACCEPTED_RETURNS: Dict[str, str] = {
        "KEEP_ALIVE": "_return_from_keep_alive",
    }

    @overrides
    def __init__(self):
        super().__init__()
        self._devices = {}

    @overrides
    def _setup(self, msg, sender):
        self.handleDeadLetters(startHandling=True)
        try:
            self.my_parent = sender
            self.my_id = msg["ID"]
        except KeyError:
            logger.critical("Malformed SETUP message")
            raise

    @overrides
    def receiveMessage(self, msg, sender):  # pylint: disable=invalid-name
        if isinstance(msg, DeadEnvelope):
            logger.critical(
                "DeadMessage: %s to deadAddress: %s. -> Emergency shutdown",
                msg.deadMessage,
                msg.deadAddress,
            )
            system_shutdown()
            return

    def _read(self, _msg, sender):
        self.send(sender, {"RETURN": "READ", "RESULT": self._devices})

    def _subscribe(self, msg, sender):
        """Handler for SUBSCRIBE messages"""
        try:
            actor_id = msg["ID"]
            parent = msg["PARENT"]
            self._devices[actor_id] = {
                "address": sender,
                "parent": parent,
                "is_alive": True,
            }
        except KeyError:
            logger.error("Message is not suited to create a dict entry.")

    def _unsubscribe(self, msg, _sender):
        """Handler for UNSUBSCRIBE messages"""
        try:
            self._devices.pop(msg["ID"])
        except KeyError:
            logger.error("Message is not suited to remove a dict entry.")

    def _return_from_keep_alive(self, msg, sender):
        """Handler for messages returned from other actors that have received a
        KEEP_ALIVE message."""
