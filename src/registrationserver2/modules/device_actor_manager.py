"""
Created on 08.12.2020

@author: rfoerster
"""
import logging

from registrationserver2 import actor_system
# from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.messages import RETURN_MESSAGES
from thespian.actors import Actor, ActorAddress, ActorExitRequest

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


class DeviceActorManager(Actor):
    """
    classdocs
    """

    ACCEPTED_MESSAGES = {
        "CREATE": "__create__",  # is being called when the end-user-application wants to reserve the directly or indirectly connected device for exclusive communication, should return if a reservation is currently possible
        "ECHO": "__echo__",  # should returns what is send, main use is for testing purpose at this point
        "SETUP": "__setup__",
        "KILL": "__kill__",
    }
    """
    Defines magic methods that are called when the specific message is received by the actor
    """

    actors: dict

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """

        if isinstance(msg, ActorExitRequest):
            return

        if not isinstance(msg, dict):
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGTYPE"))
            return

        cmd_string = msg.get("CMD", None)

        if not cmd_string:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return

        cmd = self.ACCEPTED_MESSAGES.get(cmd_string, None)

        if not cmd:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_UNKNOWN_COMMAND"))
            return

        if not getattr(self, cmd, None):
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_NOTIMPLEMENTED"))
            return

        self.send(sender, getattr(self, cmd)(msg))

    @staticmethod
    def __echo__(msg: dict) -> dict:
        msg.pop("CMD", None)
        msg.pop("RETURN", None)
        msg["RETURN"] = True
        return msg

    def __create__(self, msg: dict) -> dict:
        if not hasattr(self, "actors"):
            self.actors = {}
        _name = msg.get("Name", None)
        _class = msg.get("Class", None)
        if not _name or not _class:
            return RETURN_MESSAGES.get("ILLEGAL_MISSINGDATA")
        if not isinstance(_class(), DeviceBaseActor):
            return RETURN_MESSAGES.get("ILLEGAL_NOTACORRECTACTOR")
        if not self.actors.get(_name, None):
            self.actors[_name] = self.createActor(_class, globalName=_name)
            return RETURN_MESSAGES.get("OK")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __kill__(self, msg: dict) -> dict:
        if not hasattr(self, "actors"):
            self.actors = {}

        _name = msg.get("Name", None)

        if not _name:
            return RETURN_MESSAGES.get("ILLEGAL_MISSINGDATA")

        if _name == self.globalName:
            self.send(self.myAddress, ActorExitRequest())

        _actor = self.actors.pop(_name, None)

        if _actor:
            self.send(_actor, ActorExitRequest())
            return RETURN_MESSAGES.get("OK")

        return RETURN_MESSAGES.get("OK_SKIPPED")


DEVICE_ACTOR_MANAGER: ActorAddress = actor_system.createActor(
    DeviceActorManager, type(DeviceActorManager).__name__
)
