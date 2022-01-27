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
from dataclasses import dataclass

from overrides import overrides  # type: ignore
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorAddress, ActorTypeDispatcher

from registrationserver.actor_messages import (AppType, SetupMsg, SubscribeMsg,
                                               SubscribeToActorDictMsg,
                                               SubscribeToDeviceStatusMsg,
                                               UnsubscribeMsg)
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown


@dataclass
class Parent:
    """Description of the parent actor."""

    parent_id: str
    parent_address: ActorAddress


class BaseActor(ActorTypeDispatcher):
    """Basic class for all actors created in the actor system of the Registration
    Server"""

    @staticmethod
    def _get_actor_id(actor_address, child_actors):
        """Function to return the actor_id from the child_actors dictionary
        for a given actor_address.

        Args:
            actor_address: the value
            child_actors (dict): dictionary to scan for val

        Returns:
            str: the first actor_id matching the given actor_address
        """
        for actor_id, value in child_actors.items():
            if actor_address == value["actor_address"]:
                return actor_id
        return None

    @overrides
    def __init__(self):
        super().__init__()
        self.registrar = None
        self.parent = None
        self.my_id = None
        self.child_actors = {}  # {actor_id: {"actor_address": <actor address>}}
        self.actor_dict = {}
        self.on_kill = False
        self.app_type = AppType.RS

    def receiveMsg_SetupMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupMsg to set essential attributs after initialization"""
        self.my_id = msg.actor_id
        logger.debug("%s received SetupMsg from %s", self.my_id, msg.parent_id)
        self.parent = Parent(parent_id=msg.parent_id, parent_address=sender)
        self.registrar = self.createActor(Actor, globalName="registrar")
        self.app_type = msg.app_type
        self._subscribe()

    def _subscribe(self):
        """Subscribe at Registrar actor."""
        self.send(
            self.registrar,
            SubscribeMsg(
                actor_id=self.my_id,
                parent=self.parent.parent_address,
                is_device_actor=False,
                get_updates=False,
            ),
        )

    def _forward_to_children(self, msg):
        for child_id, child_actor in self.child_actors.items():
            logger.debug("Forward %s to %s", msg, child_id)
            self.send(child_actor["actor_address"], msg)

    def receiveMsg_KillMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handle the KillMsg for this actor"""
        logger.debug("%s received KillMsg", self.my_id)
        self.on_kill = True
        if self.child_actors:
            self._forward_to_children(msg)
        else:
            self.send(self.myAddress, ActorExitRequest())

    def receiveMsg_KeepAliveMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for KeepAliveMsg from the Registrar"""
        logger.debug("%s received KeepAliveMsg", self.my_id)
        if self.child_actors:
            self._forward_to_children(msg)
        self._subscribe()

    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for UpdateActorDictMsg from Registrar"""
        logger.debug("%s received UpdateActorDictMsg", self.my_id)
        self.actor_dict = msg.actor_dict

    def receiveMsg_PoisonMessage(self, _msg, _sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for PoisonMessage"""
        logger.critical("%s received PoisonMessage -> Emergency shutdown.", self.my_id)
        system_shutdown()

    def receiveMsg_ChildActorExited(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for ChildActorExited"""
        logger.debug(
            "%s received ChildActorExited from %s", self.my_id, msg.childAddress
        )
        actor_id = self._get_actor_id(msg.childAddress, self.child_actors)
        self.child_actors.pop(actor_id, None)
        if not self.child_actors and self.on_kill:
            self.send(self.myAddress, ActorExitRequest())

    def receiveMsg_ActorExitRequest(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handler for ActorExitRequest"""
        logger.debug("%s received ActorExitRequest", self.my_id)
        self.send(self.registrar, UnsubscribeMsg(actor_id=self.my_id))

    def receiveUnrecognizedMessage(self, msg, _sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for messages that do not fit the spec."""
        logger.critical(
            "%s received unrecognizable message type: %s", self.my_id, type(msg)
        )
        system_shutdown()

    def _subscribe_to_actor_dict_msg(self):
        """Subscribe to receive updates of the Actor Dictionary from Registrar."""
        self.send(self.registrar, SubscribeToActorDictMsg(actor_id=self.my_id))

    def _subscribe_to_device_status_msg(self, device_actor_address):
        """Subscribe to receive updates of the device status from device actor."""
        self.send(device_actor_address, SubscribeToDeviceStatusMsg(actor_id=self.my_id))

    def _create_actor(self, actor_type, actor_id):
        logger.debug("Create %s with parent %s", actor_id, self.my_id)
        new_actor_address = self.createActor(actor_type)
        self.send(new_actor_address, SetupMsg(actor_id, self.my_id, self.app_type))
        self.child_actors[actor_id] = {"actor_address": new_actor_address}
        return new_actor_address
