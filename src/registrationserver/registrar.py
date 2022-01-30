"""Module providing an actor to keep a list of device actors. The list is
provided as dictionary of form {actor_id: actor_address}. The actor is a
singleton in the actor system.

All status information about present instruments can be obtained from the
device actors referenced in the dictionary.

:Created:
    2021-12-15

:Author:
    | Michael Strey <strey@sarad.de>

"""

from datetime import timedelta

from overrides import overrides  # type: ignore

from registrationserver.actor_messages import (ActorCreatedMsg, AppType,
                                               KeepAliveMsg,
                                               ReturnDeviceActorMsg,
                                               UpdateActorDictMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.logger import logger
from registrationserver.modules.mqtt_scheduler import MqttSchedulerActor
from registrationserver.modules.usb.cluster_actor import ClusterActor
from registrationserver.shutdown import system_shutdown


class Registrar(BaseActor):
    """Actor providing a dictionary of devices"""

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.handleDeadLetters(startHandling=True)
        self._create_actor(ClusterActor, "cluster")
        if self.app_type == AppType.ISMQTT:
            self._create_actor(MqttSchedulerActor, "mqtt_scheduler")
        self.wakeupAfter(timedelta(minutes=10), payload="keep alive")

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for WakeupMessage to send the KeepAliveMsg to all children."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.payload == "keep alive":
            for actor_id in self.actor_dict:
                if not self.actor_dict[actor_id]["is_alive"]:
                    logger.critical(
                        "Actor %s did not respond to KeepAliveMsg.", actor_id
                    )
                    logger.critical("-> Emergency shutdown")
                    system_shutdown()
                self.actor_dict[actor_id]["is_alive"] = False
            self.send(self.myAddress, KeepAliveMsg())
        self.wakeupAfter(timedelta(minutes=10), payload="keep alive")

    def receiveMsg_DeadEnvelope(self, msg, sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for all DeadEnvelope messages in the actor system."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        logger.critical("-> Emergency shutdown")
        system_shutdown()

    def receiveMsg_SubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.actor_dict[msg.actor_id] = {
            "address": sender,
            "parent": msg.parent,
            "is_device_actor": msg.is_device_actor,
            "get_updates": msg.get_updates,
            "is_alive": True,
        }
        self._send_updates()

    def receiveMsg_UnsubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UnsubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.actor_dict.pop(msg.actor_id)
        self._send_updates()

    def _send_updates(self):
        """Send the updated Actor Dictionary to all subscribers."""
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["get_updates"]:
                logger.debug("Send updated actor_dict to %s", actor_id)
                self.send(
                    self.actor_dict[actor_id]["address"],
                    UpdateActorDictMsg(self.actor_dict),
                )

    def receiveMsg_GetActorDictMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for requests to get the Actor Dictionary once."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(sender, UpdateActorDictMsg(self.actor_dict))

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ActorExitRequest"""
        self.send(self.parent.parent_address, True)

    def receiveMsg_CreateActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for CreateActorMsg. Create a new actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        actor_id = msg.actor_id
        if actor_id not in self.actor_dict:
            actor_address = self._create_actor(msg.actor_type, actor_id)
        else:
            actor_address = self.actor_dict[actor_id]["address"]
        self.send(sender, ActorCreatedMsg(actor_address))

    def receiveMsg_GetDeviceActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle request to deliver the actor address of a given device id."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        device_actor_dict = {
            id: dict["address"]
            for id, dict in self.actor_dict.items()
            if dict["is_device_actor"]
        }
        for actor_id, actor_address in device_actor_dict.items():
            if actor_id == msg.device_id:
                self.send(sender, ReturnDeviceActorMsg(actor_address))

    def receiveMsg_SubscribeToActorDictMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the 'get_updates' flag for the requesting sender
        to send updated actor dictionaries to it."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.actor_id in self.actor_dict:
            logger.debug("Set 'get_updates' for %s", msg.actor_id)
            self.actor_dict[msg.actor_id]["get_updates"] = True
            self._send_updates()
        else:
            logger.warning("%s not in %s", msg.actor_id, self.actor_dict)
