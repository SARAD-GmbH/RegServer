"""This module implements the BaseActor all other actors inherit from.

Actors created in the actor system

- have to know the actor address of the *Registrar*
- have to subscribe at the *Registrar* on startup
- can read the *Actor Dictionary* from the *Registrar*
- have to unsubscribe at the *Registrar* on their ActorExitRequest() handler
- have to keep a list of the actor addresses of their child actors
- have to respond to the *Registrar* after receiving a *keep alive* message

:Created:
    2021-12-22

:Author:
    | Michael Strey <strey@sarad.de>

"""
from typing import Dict

from overrides import overrides  # type: ignore
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem, PoisonMessage

from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.shutdown import system_shutdown


class BaseActor(Actor):
    """Basic class for all actors created in the actor system of the Registration
    Server"""

    ACCEPTED_COMMANDS = {
        "SETUP": "_setup",
        "KEEP_ALIVE": "_keep_alive",
    }

    ACCEPTED_RETURNS: Dict[str, str] = {}

    @overrides
    def __init__(self):
        super().__init__()
        self.registrar = None
        self.my_parent = None
        self.my_id = None
        self.child_actors = {}  # {actor_id: <actor address>}

    def _setup(self, msg, sender):
        """Handler for SETUP message to set essential attributs after initialization"""
        try:
            self.registrar = ActorSystem().createActor(Actor, globalName="registrar")
            self.my_parent = sender
            self.my_id = msg["ID"]
        except KeyError:
            logger.critical("Malformed SETUP message")
            raise
        self.send(
            self.registrar,
            {"CMD": "SUBSCRIBE", "ID": self.my_id, "PARENT": self.my_parent},
        )

    def _keep_alive(self, msg, _sender):
        """Handler for KEEP_ALIVE message from the Registrar"""
        for _child_id, child_actor in self.child_actors.items():
            self.send(child_actor, msg)
        self.send(self.registrar, {"RETURN": "KEEP_ALIVE", "ID": self.my_id})

    def _valid_cmd_function(self, cmd_key, cmd_function):
        cmd_function = self.ACCEPTED_COMMANDS.get(cmd_key, None)
        if cmd_function is None:
            logger.critical("Command for key %s does not exist here.", cmd_key)
            return False
        if getattr(self, cmd_function, None) is None:
            logger.critical("No function implemented for %s", cmd_function)
            return False
        return True

    @overrides
    def receiveMessage(self, msg, sender):  # pylint: disable=invalid-name
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
                if self._valid_cmd_function(cmd_key, cmd_function):
                    getattr(self, cmd_function)(msg, sender)
                else:
                    return
            elif return_key is not None:
                return_function = self.ACCEPTED_RETURNS.get(return_key, None)
                if self._valid_cmd_function(return_key, return_function):
                    getattr(self, return_function)(msg, sender)
                else:
                    return
        else:
            if isinstance(msg, PoisonMessage):
                logger.critical("PoisonMessage --> Emergency shutdown.")
                system_shutdown()
                return
            if isinstance(msg, ActorExitRequest):
                self.send(self.registrar, {"CMD": "UNSUBSCRIBE", "ID": self.my_id})
                return
            logger.critical(
                (
                    "Msg is neither a command nor PoisonMessage nor ActorExitRequest",
                    " -> Emergency shutdown",
                )
            )
            system_shutdown()
            return
