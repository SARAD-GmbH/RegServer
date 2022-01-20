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

from overrides import overrides  # type: ignore

from registrationserver.base_actor import BaseActor
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown


class Registrar(BaseActor):
    """Actor providing a dictionary of devices"""

    @overrides
    def __init__(self):
        self.ACCEPTED_COMMANDS.update(
            {
                "READ": "_on_read_cmd",
                "SUBSCRIBE": "_on_subscribe_cmd",
                "UNSUBSCRIBE": "_on_unsubscribe_cmd",
            }
        )
        self.ACCEPTED_RETURNS.update(
            {
                "KEEP_ALIVE": "_on_keep_alive_return",
            }
        )
        super().__init__()
        self._devices = {}

    @overrides
    def _on_setup_cmd(self, msg, sender):
        self.handleDeadLetters(startHandling=True)
        try:
            self.my_parent = sender
            self.my_id = msg["ID"]
        except KeyError:
            logger.critical("Malformed SETUP message")
            raise

    def receiveMsg_DeadEnvelope(self, msg, _sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for all DeadEnvelope messages in the actor system"""
        logger.critical(
            "DeadMessage: %s to deadAddress: %s. -> Emergency shutdown",
            msg.deadMessage,
            msg.deadAddress,
        )
        system_shutdown()

    def _on_read_cmd(self, _msg, sender):
        """Handler for READ message"""
        self.send(sender, {"RETURN": "READ", "RESULT": self._devices})

    def _on_subscribe_cmd(self, msg, sender):
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

    def _on_unsubscribe_cmd(self, msg, _sender):
        """Handler for UNSUBSCRIBE messages"""
        try:
            self._devices.pop(msg["ID"])
        except KeyError:
            logger.error("Message is not suited to remove a dict entry.")

    def _on_keep_alive_return(self, msg, sender):
        """Handler for messages returned from other actors that have received a
        KEEP_ALIVE message."""
