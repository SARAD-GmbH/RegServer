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
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, DeadEnvelope, PoisonMessage

from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.shutdown import system_shutdown


class Registrar(Actor):
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
        self._devices = {}
        super().__init__()

    def _setup(self, _msg, _sender):
        self.handleDeadLetters(startHandling=True)

    @overrides
    def receiveMessage(self, msg, sender):
        """Handles received Actor messages / verification of the message format"""
        if isinstance(msg, dict):
            logger.debug("Msg: %s, Sender: %s", msg, sender)
            return_key = msg.get("RETURN", None)
            cmd_key = msg.get("CMD", None)
            if ((return_key is None) and (cmd_key is None)) or (
                (return_key is not None) and (cmd_key is not None)
            ):
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_MESSAGE"])
                return
            if cmd_key is not None:
                cmd_function = self.ACCEPTED_COMMANDS.get(cmd_key, None)
                if cmd_function is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.",
                        msg,
                        sender,
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]["ERROR_MESSAGE"]
                    )
                    return
                if getattr(self, cmd_function, None) is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.",
                        msg,
                        sender,
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]["ERROR_MESSAGE"]
                    )
                    return
                getattr(self, cmd_function)(msg, sender)
            elif return_key is not None:
                return_function = self.ACCEPTED_RETURNS.get(return_key, None)
                if return_function is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                if getattr(self, return_function, None) is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                getattr(self, return_function)(msg, sender)
        else:
            if isinstance(msg, PoisonMessage):
                logger.critical("PoisonMessage --> System shutdown.")
                system_shutdown()
                return
            if isinstance(msg, ActorExitRequest):
                return
            if isinstance(msg, DeadEnvelope):
                logger.critical(
                    "DeadMessage: %s to deadAddress: %s",
                    msg.deadMessage,
                    msg.deadAddress,
                )
                system_shutdown()
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
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

    def _unsubscribe(self, msg, sender):
        """Handler for UNSUBSCRIBE messages"""
        try:
            self._devices.pop(msg["ID"])
        except KeyError:
            logger.error("Message is not suited to remove a dict entry.")

    def _return_from_keep_alive(self, msg, sender):
        """Handler for messages returned from other actors that have received a
        KEEP_ALIVE message."""
