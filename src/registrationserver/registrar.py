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
from thespian.actors import ActorExitRequest  # type: ignore

from registrationserver.actor_messages import (ActorCreatedMsg, Backend,
                                               Frontend, KeepAliveMsg, KillMsg,
                                               PrepareMqttActorMsg,
                                               ReturnDeviceActorMsg,
                                               UpdateActorDictMsg,
                                               UpdateDeviceStatusesMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import (actor_config, backend_config, config,
                                       frontend_config, mqtt_config)
from registrationserver.helpers import (is_device_actor, short_id,
                                        transport_technology)
from registrationserver.logger import logger
from registrationserver.modules.backend.is1.is1_listener import Is1Listener
from registrationserver.modules.backend.mqtt.mqtt_listener import MqttListener
from registrationserver.modules.backend.usb.cluster_actor import ClusterActor
from registrationserver.modules.frontend.mdns.mdns_scheduler import \
    MdnsSchedulerActor
from registrationserver.modules.frontend.mqtt.mqtt_scheduler import \
    MqttSchedulerActor


class Registrar(BaseActor):
    """Actor providing a dictionary of devices"""

    @overrides
    def __init__(self):
        super().__init__()
        self.device_statuses = {}  # {device_id: {status_dict}}

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.handleDeadLetters(startHandling=True)
        if Frontend.MQTT in frontend_config:
            mqtt_scheduler = self._create_actor(MqttSchedulerActor, "mqtt_scheduler")
            self.send(
                mqtt_scheduler,
                PrepareMqttActorMsg(
                    is_id=None,
                    client_id=config["IS_ID"],
                    group=mqtt_config["GROUP"],
                ),
            )
        if Frontend.MDNS in frontend_config:
            _mdns_scheduler = self._create_actor(MdnsSchedulerActor, "mdns_scheduler")
        if Backend.USB in backend_config:
            self._create_actor(ClusterActor, "cluster")
        if Backend.MQTT in backend_config:
            mqtt_listener = self._create_actor(MqttListener, "mqtt_listener")
            self.send(
                mqtt_listener,
                PrepareMqttActorMsg(
                    is_id=None,
                    client_id=mqtt_config["MQTT_CLIENT_ID"],
                    group=mqtt_config["GROUP"],
                ),
            )
        if Backend.IS1 in backend_config:
            _is1_listener = self._create_actor(Is1Listener, "is1_listener")
        self.wakeupAfter(timedelta(minutes=1), payload="keep alive")

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage to send the KeepAliveMsg to all children."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        logger.info("Watchdog: start health check")
        if msg.payload == "keep alive":
            for actor_id in self.actor_dict:
                if not self.actor_dict[actor_id]["is_alive"]:
                    logger.critical(
                        "Actor %s did not respond to KeepAliveMsg.", actor_id
                    )
                    logger.critical("-> Emergency shutdown")
                    self.send(self.registrar, KillMsg())
                self.actor_dict[actor_id]["is_alive"] = False
            self.send(self.myAddress, KeepAliveMsg())
        logger.info("Watchdog: health check finished")
        self.wakeupAfter(
            timedelta(minutes=actor_config["KEEPALIVE_INTERVAL"]), payload="keep alive"
        )

    def receiveMsg_DeadEnvelope(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for all DeadEnvelope messages in the actor system."""
        logger.error("%s for %s from %s", msg, self.my_id, sender)
        if isinstance(msg.deadMessage, (ActorExitRequest, KillMsg)):
            logger.info("The above error can safely be ignored.")
        else:
            logger.critical("-> Emergency shutdown")
            self.send(self.registrar, KillMsg())

    def receiveMsg_SubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.keep_alive:
            self.actor_dict[msg.actor_id]["is_alive"] = True
            self._send_updates(self.actor_dict)
            return
        if msg.actor_id in self.actor_dict:
            logger.critical(
                "The actor already exists in the system -> emergency shutdown"
            )
            self.send(sender, KillMsg())
            self.send(self.registrar, KillMsg())
            return
        self.actor_dict[msg.actor_id] = {
            "address": sender,
            "parent": msg.parent,
            "is_device_actor": msg.is_device_actor,
            "get_updates": msg.get_updates,
            "is_alive": True,
        }
        if msg.is_device_actor:
            new_device_id = msg.actor_id
            for old_device_id in self.actor_dict:
                if (
                    (short_id(old_device_id) == short_id(new_device_id))
                    and (new_device_id != old_device_id)
                    and (
                        transport_technology(old_device_id)
                        in ["local", "mdns", "mqtt", "is1"]
                    )
                ):
                    old_tt = transport_technology(old_device_id)
                    new_tt = transport_technology(new_device_id)
                    logger.debug("New device_id: %s", new_device_id)
                    logger.debug("Old device_id: %s", old_device_id)
                    if new_tt == "local":
                        logger.debug(
                            "Keep new %s and set the old %s inactive",
                            new_device_id,
                            old_device_id,
                        )
                        self.actor_dict[old_device_id]["is_device_actor"] = False
                    elif (new_tt in ["mdns", "mqtt"]) and (old_tt == "is1"):
                        logger.debug(
                            "Keep old %s and set the new %s inactive",
                            old_device_id,
                            new_device_id,
                        )
                        self.actor_dict[new_device_id]["is_device_actor"] = False
                    else:
                        logger.debug("Keep device actor %s in place.", old_device_id)
                        self.send(sender, KillMsg())
        self._send_updates(self.actor_dict)
        return

    def receiveMsg_UnsubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UnsubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        try:
            is_device_act = self.actor_dict[msg.actor_id]["is_device_actor"]
        except KeyError:
            logger.error("%s requested to be unsubscribed doesn't exist", msg.actor_id)
            is_device_act = False
        if is_device_act:
            instr_id = short_id(msg.actor_id)
            logger.debug("Look for inactive device actor for %s", instr_id)
            for actor_id, description in self.actor_dict.items():
                if (not description["is_device_actor"]) and (
                    short_id(actor_id) == instr_id
                ):
                    description["is_device_actor"] = True
                    logger.debug("Found and activated %s", actor_id)
        try:
            self.actor_dict.pop(msg.actor_id)
        except KeyError as exception:
            logger.error(
                "%s. The actor to unsubscribe was not subscribed properly.", exception
            )
        self._send_updates(self.actor_dict)

    def _send_updates(self, actor_dict):
        """Send the updated Actor Dictionary to all subscribers."""
        for actor_id in actor_dict:
            if actor_dict[actor_id]["get_updates"]:
                logger.debug("Send updated actor_dict to %s", actor_id)
                self.send(
                    actor_dict[actor_id]["address"],
                    UpdateActorDictMsg(actor_dict),
                )
            if actor_dict[actor_id]["is_device_actor"]:
                self._subscribe_to_device_status_msg(actor_dict[actor_id]["address"])

    def receiveMsg_GetActorDictMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for requests to get the Actor Dictionary once."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(sender, UpdateActorDictMsg(self.actor_dict))

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ActorExitRequest"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(self.parent.parent_address, True)

    def receiveMsg_CreateActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for CreateActorMsg. Create a new actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        actor_id = msg.actor_id
        actor_address = None
        if actor_id in self.actor_dict:
            logger.debug("%s already exists", actor_id)
            actor_address = self.actor_dict[actor_id]["address"]
        else:
            create_new_actor = True
            if is_device_actor(actor_id):
                logger.debug(
                    "Check for existing device actor with same instr_id=%s",
                    short_id(actor_id),
                )
                new_device_id = msg.actor_id
                new_instr_id = short_id(new_device_id)
                instr_id_list = [
                    short_id(actor_id)
                    for actor_id in self.actor_dict
                    if is_device_actor(actor_id)
                ]
                if new_instr_id in instr_id_list:
                    logger.debug("Found an actor with the same instr_id")
                    new_tt = transport_technology(new_device_id)
                    if new_tt in ["local", "is1"]:
                        logger.debug(
                            "Old device_actor might disapear when handling SetupMsg"
                        )
                        create_new_actor = True
                    else:
                        logger.info("Creation of %s skipped", actor_id)
                        create_new_actor = False
        if create_new_actor:
            logger.debug("Create new device_actor %s", actor_id)
            actor_address = self._create_actor(msg.actor_type, actor_id)
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
            self._send_updates(self.actor_dict)
        else:
            logger.warning("%s not in %s", msg.actor_id, self.actor_dict)

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusMsg from Device Actor.

        Adds a new instrument to the list of available instruments."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        device_id = msg.device_id
        device_status = msg.device_status
        self.device_statuses[device_id] = device_status

    def receiveMsg_GetDeviceStatusesMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle request to deliver the device statuses of all instruments."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(sender, UpdateDeviceStatusesMsg(self.device_statuses))
