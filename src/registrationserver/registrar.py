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

from datetime import timedelta

from overrides import overrides  # type: ignore

from registrationserver.actor_messages import (ActorCreatedMsg, AppType,
                                               KeepAliveMsg,
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

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for WakeupMessage to send the KeepAliveMsg to all children."""
        logger.debug("%s received WakeupMessage", self.my_id)
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

    def receiveMsg_DeadEnvelope(self, msg, _sender):
        # pylint: disable=invalid-name, no-self-use
        """Handler for all DeadEnvelope messages in the actor system."""
        logger.debug("%s received DeadEnvelope", self.my_id)
        logger.critical(
            "DeadMessage: %s to deadAddress: %s. -> Emergency shutdown",
            msg.deadMessage,
            msg.deadAddress,
        )
        system_shutdown()

    def receiveMsg_SubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SubscribeMsg from any actor."""
        logger.debug("%s received SubscribeMsg", self.my_id)
        self.actor_dict[msg.actor_id] = {
            "address": sender,
            "parent": msg.parent,
            "is_device_actor": msg.is_device_actor,
            "get_updates": msg.get_updates,
            "is_alive": True,
        }
        logger.debug("Updated actor list: %s", self.actor_dict)
        self._send_updates()

    def receiveMsg_UnsubscribeMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for UnsubscribeMsg from any actor."""
        logger.debug("%s received UnsubscribeMsg", self.my_id)
        self.actor_dict.pop(msg.actor_id)
        self._send_updates()

    def _send_updates(self):
        """Send the updated Actor Dictionary to all subscribers."""
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["get_updates"]:
                self.send(
                    self.actor_dict[actor_id]["address"],
                    UpdateActorDictMsg(self.actor_dict),
                )

    def receiveMsg_GetActorDictMsg(self, _msg, sender):
        # pylint: disable=invalid-name
        """Handler for requests to get the Actor Dictionary once."""
        logger.debug("%s received GetActorDictMsg", self.my_id)
        self.send(sender, UpdateActorDictMsg(self.actor_dict))

    @overrides
    def receiveMsg_ActorExitRequest(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handler for ActorExitRequest"""
        self.send(self.parent.parent_address, True)

    def receiveMsg_CreateActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for CreateActorMsg. Create a new actor."""
        actor_id = msg.actor_id
        if actor_id not in self.actor_dict:
            actor_address = self._create_actor(msg.actor_type, actor_id)
        else:
            actor_address = self.actor_dict[actor_id]["address"]
        self.send(sender, ActorCreatedMsg(actor_address))
