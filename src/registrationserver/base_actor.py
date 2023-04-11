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
from thespian.actors import ActorTypeDispatcher

from registrationserver.actor_messages import (DeadChildMsg, KeepAliveMsg,
                                               KillMsg, Parent,
                                               RescanFinishedMsg,
                                               ReservationStatusMsg,
                                               RxBinaryMsg, SetDeviceStatusMsg,
                                               SetupMdnsActorMsg, SetupMsg,
                                               SubscribeMsg,
                                               SubscribeToActorDictMsg,
                                               SubscribeToDeviceStatusMsg,
                                               UnSubscribeFromActorDictMsg,
                                               UnSubscribeFromDeviceStatusMsg,
                                               UnsubscribeMsg,
                                               UpdateActorDictMsg)
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown


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
        self.registrar = None
        self.parent = None
        self.my_id = None
        self.is_device_actor = False
        self.get_updates = False
        self.child_actors = {}  # {actor_id: {"actor_address": <actor address>}}
        self.actor_dict = {}
        self.on_kill = False

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
        if self.is_device_actor:
            logger.info(
                "Device actor %s created at %s.", self.my_id, self.parent.parent_id
            )

    def _subscribe(self, keep_alive):
        """Subscribe at Registrar actor."""
        self.send(
            self.registrar,
            SubscribeMsg(
                actor_id=self.my_id,
                parent=self.parent.parent_address,
                is_device_actor=self.is_device_actor,
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
        self.on_kill = True
        if self.get_updates:
            self._unsubscribe_from_actor_dict_msg()
        if self.child_actors:
            self._forward_to_children(msg)
            self._forward_to_children(ActorExitRequest())
        else:
            if msg.register:
                self.send(self.registrar, UnsubscribeMsg(actor_id=self.my_id))
            self.send(self.myAddress, ActorExitRequest())
            if self.is_device_actor:
                logger.info(
                    "Device actor %s exited at %s.", self.my_id, self.parent.parent_id
                )

    def receiveMsg_KeepAliveMsg(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for KeepAliveMsg from the Registrar"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.on_kill:
            logger.debug("I'm dying. Don't disturb me!")
            return
        if self.child_actors:
            for child_id, child_actor in self.child_actors.items():
                keep_alive_msg = KeepAliveMsg(
                    parent=Parent(self.my_id, self.myAddress),
                    child=child_id,
                    report=msg.report,
                )
                logger.debug("Forward %s to %s", keep_alive_msg, child_id)
                self.send(child_actor["actor_address"], keep_alive_msg)
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
        logger.critical("-> Emergency shutdown.")
        system_shutdown()

    def receiveMsg_ChildActorExited(self, msg, sender):
        # pylint: disable=invalid-name, unused-argument
        """Handler for ChildActorExited"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        actor_id = self._get_actor_id(msg.childAddress, self.child_actors)
        self.send(self.registrar, UnsubscribeMsg(actor_id))
        self.child_actors.pop(actor_id, None)
        logger.debug(
            "List of child actors after removal of %s: %s", actor_id, self.child_actors
        )
        logger.debug("self.on_kill is %s", self.on_kill)
        if (not self.child_actors) and self.on_kill:
            logger.debug("Unsubscribe and send ActorExitRequest to myself")
            self.send(self.registrar, UnsubscribeMsg(actor_id=self.my_id))
            self.send(self.myAddress, ActorExitRequest())

    def receiveMsg_ActorExitRequest(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ActorExitRequest"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        # self.send(self.registrar, UnsubscribeMsg(actor_id=self.my_id))

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
        logger.warning("%s for %s from %s", msg, self.my_id, sender)
        if isinstance(
            msg.deadMessage,
            (
                ActorExitRequest,
                KillMsg,
                SubscribeToDeviceStatusMsg,
                UnSubscribeFromDeviceStatusMsg,
                UpdateActorDictMsg,
                SetDeviceStatusMsg,
                SetupMdnsActorMsg,
                ReservationStatusMsg,
                RxBinaryMsg,
                RescanFinishedMsg,
            ),
        ):
            actor_dict = self.actor_dict.copy()
            for actor in actor_dict:
                if actor_dict[actor]["address"] == msg.deadAddress:
                    self.actor_dict.pop(actor, None)
                    logger.warning(
                        "Remove not existing actor %s from self.actor_dict", actor
                    )
            logger.info("The above warning can safely be ignored.")
        elif isinstance(msg.deadMessage, KeepAliveMsg):
            self.send(
                msg.deadMessage.parent.parent_address,
                DeadChildMsg(msg.deadMessage.child),
            )
        else:
            logger.critical("-> Emergency shutdown")
            system_shutdown()

    def receiveMsg_DeadChildMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for the message indicating that a child Actor has caused a
        DeadEnvelope."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.child in self.child_actors:
            logger.critical(
                "%s doesn't exist but is still in %s", msg.child, self.child_actors
            )
            logger.debug("-> Emergency shutdown")
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
