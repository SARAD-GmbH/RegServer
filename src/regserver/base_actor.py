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

from overrides import overrides  # type: ignore
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import ActorAddress, ActorTypeDispatcher, ChildActorExited

from regserver.actor_messages import (ActorType, DeadChildMsg,
                                      GetDeviceStatusMsg, KeepAliveMsg,
                                      KillMsg, MqttReceiveMsg, Parent,
                                      PrepareMqttActorMsg, RescanAckMsg,
                                      ReservationStatusMsg, RxBinaryMsg,
                                      SetDeviceStatusMsg, SetupMdnsActorMsg,
                                      SetupMsg, SetupUsbActorMsg, SubscribeMsg,
                                      SubscribeToActorDictMsg,
                                      SubscribeToDeviceStatusMsg,
                                      UnSubscribeFromActorDictMsg,
                                      UnSubscribeFromDeviceStatusMsg,
                                      UnsubscribeMsg, UpdateActorDictMsg)
from regserver.logger import logger
from regserver.shutdown import is_flag_set, system_shutdown


class BaseActor(ActorTypeDispatcher):
    # pylint: disable=too-many-instance-attributes
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
        self.registrar: ActorAddress = ActorAddress(None)
        self.parent: Parent = Parent(parent_id="", parent_address=ActorAddress(None))
        self.my_id: str = ""
        self.actor_type = ActorType.NONE
        self.get_updates = False
        self.child_actors: dict = {}  # {actor_id: {"actor_address": <actor address>}}
        self.actor_dict: dict = {}
        self.on_kill: bool = False

    def receiveMsg_SetupMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupMsg to set essential attributs after initialization"""
        self.my_id = msg.actor_id
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.parent = Parent(parent_id=msg.parent_id, parent_address=sender)
        self.registrar = msg.registrar
        if self.registrar is None:
            self.registrar = self.myAddress
        self._subscribe(False)

    def _subscribe(self, keep_alive):
        """Subscribe at Registrar actor."""
        if self.my_id is not None:
            self.send(
                self.registrar,
                SubscribeMsg(
                    actor_id=self.my_id,
                    parent=self.parent.parent_address,
                    actor_type=self.actor_type,
                    get_updates=self.get_updates,
                    keep_alive=keep_alive,
                ),
            )

    def _forward_to_children(self, msg):
        for child_id, child_actor in self.child_actors.items():
            logger.debug("Forward %s to %s", msg, child_id)
            self.send(child_actor["actor_address"], msg)

    def receiveMsg_KillMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handle the KillMsg for this actor"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._kill_myself(register=msg.register)

    def _kill_myself(self, register=True, resurrect=False):
        if resurrect:
            logger.warning("%s will be killed but resurrect", self.my_id)
        if not self.on_kill:
            self.on_kill = True
            if self.get_updates:
                self._unsubscribe_from_actor_dict_msg()
            if self.child_actors:
                self._forward_to_children(KillMsg(register=register))
            else:
                if register:
                    self.send(
                        self.registrar, UnsubscribeMsg(actor_address=self.myAddress)
                    )
                self.send(self.parent.parent_address, ChildActorExited(self.myAddress))
                self.send(self.myAddress, ActorExitRequest())

    def receiveMsg_KeepAliveMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for KeepAliveMsg from the Registrar"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.report:
            self._subscribe(True)

    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for UpdateActorDictMsg from Registrar"""
        # logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.actor_dict = msg.actor_dict

    def receiveMsg_PoisonMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for PoisonMessage"""
        logger.critical("%s for %s from %s", msg, self.my_id, sender)
        system_shutdown()

    def receiveMsg_ChildActorExited(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for ChildActorExited"""
        actor_id = self._get_actor_id(msg.childAddress, self.child_actors)
        if actor_id is None:
            return
        if self.my_id in ("registrar"):
            logger.info("%s for %s from %s (%s)", msg, self.my_id, actor_id, sender)
        else:
            logger.debug("%s for %s from %s (%s)", msg, self.my_id, actor_id, sender)
        child_actor = self.child_actors.pop(actor_id, None)
        if child_actor is not None:
            logger.debug(
                "List of child actors after removal of %s: %s",
                actor_id,
                self.child_actors,
            )
        logger.debug("self.on_kill is %s", self.on_kill)
        if (not self.child_actors) and self.on_kill:
            if self.my_id in ("registrar"):
                logger.info("Last man (%s) standing!", self.my_id)
            else:
                logger.debug(
                    "Unsubscribe from Registrar and send ActorExitRequest to myself"
                )
                self.send(self.registrar, UnsubscribeMsg(actor_address=self.myAddress))
            self.send(self.parent.parent_address, ChildActorExited(self.myAddress))
            self.send(self.myAddress, ActorExitRequest())

    def receiveMsg_ActorExitRequest(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ActorExitRequest"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        # self.send(self.registrar, UnsubscribeMsg(actor_address=self.myAddress))

    def receiveMsg_DeadEnvelope(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for all DeadEnvelope messages in the actor system.

        Placing this handler here is a workaround for an error in dead letter
        handling in the multiprocQueueBase implementation of Thespian Actor
        System. Actually it belongs to the Registrar Actor that was ordained
        for dead letter handling. This did work well with multiprocUDPBase and
        multiprocTCPBase but didn't with multiprocQueueBase. In the last case
        the Cluster actor received a DeadEnvelope message causing a failure.
        See #210.

        """
        if not is_flag_set()[0]:
            return
        if isinstance(
            msg.deadMessage,
            (
                ActorExitRequest,
                GetDeviceStatusMsg,
                KillMsg,
                SubscribeToDeviceStatusMsg,
                UnSubscribeFromDeviceStatusMsg,
                UpdateActorDictMsg,
                SetDeviceStatusMsg,
                SetupMdnsActorMsg,
                SetupUsbActorMsg,
                ReservationStatusMsg,
                RxBinaryMsg,
                RescanAckMsg,
                MqttReceiveMsg,
                PrepareMqttActorMsg,
            ),
        ):
            self.send(self.registrar, UnsubscribeMsg(msg.deadAddress))
        elif isinstance(msg.deadMessage, (KeepAliveMsg)):
            self.send(
                msg.deadMessage.parent.parent_address,
                DeadChildMsg(msg.deadMessage.child),
            )
            logger.warning("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.critical("%s for %s from %s", msg, self.my_id, sender)
            logger.critical("%s -> Emergency shutdown", self.my_id)
            system_shutdown()

    def receiveMsg_DeadChildMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for the message indicating that a child Actor has caused a
        DeadEnvelope."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.child in self.child_actors:
            logger.critical(
                "%s doesn't exist as child of %s but is still in %s",
                msg.child,
                self.my_id,
                self.child_actors,
            )
            system_shutdown()
        else:
            logger.debug("Don't worry about the Dead Letter caused by %s!", msg.child)

    def receiveUnrecognizedMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for messages that do not fit the spec."""
        logger.critical(
            "Unrecognized %s for %s from %s -> Emergency shutdown",
            msg,
            self.my_id,
            sender,
        )
        system_shutdown()

    def _subscribe_to_actor_dict_msg(self):
        """Subscribe to receive updates of the Actor Dictionary from Registrar."""
        self.get_updates = True
        self.send(self.registrar, SubscribeToActorDictMsg(actor_id=self.my_id))

    def _unsubscribe_from_actor_dict_msg(self):
        """Unsubscribe from updates of the Actor Dictionary from Registrar."""
        self.get_updates = False
        self.send(self.registrar, UnSubscribeFromActorDictMsg(actor_id=self.my_id))

    def _subscribe_to_device_status_msg(self, device_actor_address):
        """Subscribe to receive updates of the device status from device actor."""
        self.send(device_actor_address, SubscribeToDeviceStatusMsg(actor_id=self.my_id))

    def _unsubscribe_from_device_status_msg(self, device_actor_address):
        """Unsubscribe from receiving updates of the device status from device actor."""
        self.send(
            device_actor_address, UnSubscribeFromDeviceStatusMsg(actor_id=self.my_id)
        )

    def _create_actor(self, actor_type, actor_id, asys_address):
        logger.debug("Create %s with parent %s", actor_id, self.my_id)
        new_actor_address = self.createActor(actor_type)
        self.send(
            new_actor_address,
            SetupMsg(actor_id, self.my_id, self.registrar, asys_address),
        )
        self.child_actors[actor_id] = {"actor_address": new_actor_address}
        return new_actor_address
