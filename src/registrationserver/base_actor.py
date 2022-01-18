"""This module implements the BaseActor all other actors inherit from.

Actors created in the actor system

- have to know the actor address of the *Registrar*
- have to subscribe at the *Registrar* on startup
- can subscribe to updates of the *Actor Dictionary* from the *Registrar*
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
from thespian.actors import Actor, ActorSystem, ChildActorExited, PoisonMessage

from registrationserver.helpers import get_key
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.shutdown import system_shutdown


class BaseActor(Actor):
    """Basic class for all actors created in the actor system of the Registration
    Server"""

    ACCEPTED_COMMANDS = {
        "SETUP": "_on_setup_cmd",
        "KEEP_ALIVE": "_on_keep_alive_cmd",
        "UPDATE_DICT": "_on_update_dict_cmd",
        "KILL": "_on_kill_cmd",
    }

    ACCEPTED_RETURNS: Dict[str, str] = {}

    @overrides
    def __init__(self):
        super().__init__()
        self.registrar = None
        self.my_parent = None
        self.my_id = None
        self.child_actors = {}  # {actor_id: <actor address>}
        self.actor_dict = {}
        self.on_kill = False

    def _on_setup_cmd(self, msg, sender):
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

    def _on_kill_cmd(self, msg, sender):  # pylint: disable = unused-argument
        """Handle the KILL command for this actor"""
        for _child_id, child_actor in self.child_actors.items():
            self.send(child_actor, msg)
        self.on_kill = True

    def _on_keep_alive_cmd(self, msg, sender):  # pylint: disable = unused-argument
        """Handler for KEEP_ALIVE message from the Registrar"""
        for _child_id, child_actor in self.child_actors.items():
            self.send(child_actor, msg)
        self.send(self.registrar, {"RETURN": "KEEP_ALIVE", "ID": self.my_id})

    def _on_update_dict_cmd(self, msg, sender):  # pylint: disable = unused-argument
        """Handler for UPDATE_DICT message from any actor"""
        self.actor_dict = msg["PAR"]["ACTOR_DICT"]

    def _mark_as_device_actor(self):
        self.send(self.registrar, {"CMD": "IS_DEVICE", "ID": self.my_id})

    def _subcribe_to_actor_dict(self):
        """Subscribe to receive updates of the Actor Dictionary from Registrar."""
        self.send(self.registrar, {"CMD": "SUB_TO_DICT", "ID": self.my_id})

    def _valid_cmd_function(self, cmd_key, cmd_function):
        """Helper function for receiveMessage()"""
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
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, PoisonMessage):
            logger.critical("PoisonMessage --> Emergency shutdown.")
            system_shutdown()
            return
        if isinstance(msg, ActorExitRequest):
            self.send(self.registrar, {"CMD": "UNSUBSCRIBE", "ID": self.my_id})
            return
        if isinstance(msg, ChildActorExited):
            actor_id = get_key(msg.childAddress, self.child_actors)
            self.child_actors.pop(actor_id, None)
            if not self.child_actors and self.on_kill:
                self.send(self.myAddress, ActorExitRequest())
            return
        if isinstance(msg, dict):
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
            logger.critical(
                (
                    "Msg is neither a command nor PoisonMessage, DeadMessage or ActorExitRequest",
                    " -> Emergency shutdown",
                )
            )
            system_shutdown()
