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

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore

from registrationserver.actor_messages import (Backend, Frontend, KillMsg,
                                               PrepareMqttActorMsg,
                                               ReturnDeviceActorMsg,
                                               UpdateActorDictMsg,
                                               UpdateDeviceStatusesMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import (actor_config, backend_config, config,
                                       frontend_config, mqtt_config)
from registrationserver.helpers import short_id, transport_technology
from registrationserver.logger import logger
from registrationserver.modules.backend.is1.is1_listener import Is1Listener
from registrationserver.modules.backend.mqtt.mqtt_listener import MqttListener
from registrationserver.modules.backend.usb.cluster_actor import ClusterActor
from registrationserver.modules.frontend.mdns.mdns_scheduler import \
    MdnsSchedulerActor
from registrationserver.modules.frontend.mqtt.mqtt_scheduler import \
    MqttSchedulerActor
from registrationserver.shutdown import system_shutdown


class Registrar(BaseActor):
    """Actor providing a dictionary of devices"""

    @overrides
    def __init__(self):
        super().__init__()
        self.device_statuses = {}  # {device_id: {status_dict}}
        # a list of actors that are already created but not yet subscribed
        self.pending = []

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.handleDeadLetters(startHandling=True)
        if Frontend.MQTT in frontend_config:
            mqtt_scheduler = self._create_actor(
                MqttSchedulerActor, "mqtt_scheduler", None
            )
            self.send(
                mqtt_scheduler,
                PrepareMqttActorMsg(
                    is_id=None,
                    client_id=config["IS_ID"],
                    group=mqtt_config["GROUP"],
                ),
            )
        if Frontend.MDNS in frontend_config:
            _mdns_scheduler = self._create_actor(
                MdnsSchedulerActor, "mdns_scheduler", None
            )
        if Backend.USB in backend_config:
            self._create_actor(ClusterActor, "cluster", None)
        if Backend.MQTT in backend_config:
            mqtt_listener = self._create_actor(MqttListener, "mqtt_listener", None)
            self.send(
                mqtt_listener,
                PrepareMqttActorMsg(
                    is_id=None,
                    client_id=mqtt_config["MQTT_CLIENT_ID"],
                    group=mqtt_config["GROUP"],
                ),
            )
        if Backend.IS1 in backend_config:
            _is1_listener = self._create_actor(Is1Listener, "is1_listener", None)
        keepalive_interval = actor_config["KEEPALIVE_INTERVAL"]
        if keepalive_interval:
            logger.debug(
                "Inner watchdog will be activated every %d s.", keepalive_interval
            )
            self.wakeupAfter(
                timedelta(seconds=keepalive_interval), payload="keep alive"
            )

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage to send the KeepAliveMsg to all children."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        CHECK = actor_config["CHECK"]
        if msg.payload == "keep alive":
            logger.debug("Watchdog: start health check")
            if CHECK:
                for actor_id in self.actor_dict:
                    self.actor_dict[actor_id]["is_alive"] = False
                self.wakeupAfter(
                    timedelta(seconds=actor_config["WAIT_BEFORE_CHECK"]),
                    payload="check",
                )
            else:
                self.wakeupAfter(
                    timedelta(seconds=actor_config["KEEPALIVE_INTERVAL"]),
                    payload="keep alive",
                )
            self._keep_alive_handler(CHECK)
        elif msg.payload == "check":
            success = True
            for actor_id in self.actor_dict:
                if not self.actor_dict[actor_id]["is_alive"]:
                    logger.critical(
                        "Actor %s did not respond to KeepAliveMsg.", actor_id
                    )
                    success = False
            if success:
                logger.debug("Watchdog: health check finished successfully")
                self.wakeupAfter(
                    timedelta(seconds=actor_config["KEEPALIVE_INTERVAL"]),
                    payload="keep alive",
                )
            else:
                logger.critical(
                    "Watchdog: health check finished with failure -> Emergency shutdown"
                )
                system_shutdown()

    def _is_alive(self, actor_id):
        """Confirm that the actor is still alive."""
        try:
            self.actor_dict[actor_id]["is_alive"] = True
        except KeyError:
            logger.error(
                "Great confusion. %s passed away during handling of KeepAliveMsg.",
                actor_id,
            )

    def _handle_existing_actor(self, sender, actor_id, is_device_actor):
        """Do whatever is required if the SubscribeMsg handler finds an actor
        that is already existing.

        Args:
            sender: Actor address of the Actor sending the SubscribeMsg
            actor_id: Id of the actor that shall be subscribed
            is_device_actor (bool): indicates a device actor
        """
        logger.error("The actor %s already exists in the system.", actor_id)
        self.send(sender, KillMsg(register=False))
        if is_device_actor:
            hid = Hashids()
            serial_number = hid.decode(short_id(actor_id))[2]
            if serial_number == 65535:
                logger.info(
                    "Someone has attached a virgin SARAD instrument. Ignore it!"
                )
            elif transport_technology(actor_id) == "mdns":
                logger.debug(
                    "%s is availabel from different hosts. First come, first served.",
                    actor_id,
                )
            else:
                logger.critical("SN %d != 65535 -> Emergency shutdown", serial_number)
                system_shutdown()
        else:
            logger.critical("-> Emergency shutdown")
            system_shutdown()

    def _handle_device_actor(self, sender, actor_id):
        """Do whatever is required if the SubscribeMsg handler finds an Device
        Actor to be subscribed.

        Args:
            sender: Actor address of the Actor sending the SubscribeMsg
            actor_id: Id of the actor that shall be subscribed
        """
        keep_new_actor = True
        new_device_id = actor_id
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
                        "Keep new %s and kill the old %s",
                        new_device_id,
                        old_device_id,
                    )
                    keep_new_actor = True
                    self.send(self.actor_dict[old_device_id]["address"], KillMsg())
                elif (new_tt == "mdns") and (old_tt == "is1"):
                    logger.debug(
                        "A WLAN instrument might have been connected to another PC via USB."
                    )
                    # TODO Check whether old_device_id is still active
                    logger.warning(
                        "A WLAN instrument connected via USB to a remote host will be ignored."
                    )
                    keep_new_actor = False
                    self.send(sender, KillMsg())
                    return
                else:
                    logger.debug("Keep device actor %s in place.", old_device_id)
                    keep_new_actor = False
                    self.send(sender, KillMsg())
                    return
        if (not self.on_kill) and keep_new_actor:
            self.device_statuses[actor_id] = self.device_statuses.get(actor_id, {})
            logger.debug("Subscribe %s to device statuses dict", actor_id)
            self._subscribe_to_device_status_msg(sender)

    def receiveMsg_SubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.actor_id in self.pending:
            self.pending.remove(msg.actor_id)
        if msg.keep_alive:
            self._is_alive(msg.actor_id)
            return
        if msg.actor_id in self.actor_dict:
            self._handle_existing_actor(sender, msg.actor_id, msg.is_device_actor)
            return
        self.actor_dict[msg.actor_id] = {
            "address": sender,
            "parent": msg.parent,
            "is_device_actor": msg.is_device_actor,
            "get_updates": msg.get_updates,
            "is_alive": True,
        }
        if msg.is_device_actor:
            self._handle_device_actor(sender, msg.actor_id)
        self._send_updates(self.actor_dict)
        return

    def receiveMsg_UnsubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UnsubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        actor_id = msg.actor_id
        self.device_statuses.pop(actor_id, None)
        removed_actor = self.actor_dict.pop(actor_id, None)
        if removed_actor is not None:
            self._send_updates(self.actor_dict)

    def _send_updates(self, actor_dict):
        """Send the updated Actor Dictionary to all subscribers."""
        for actor_id in actor_dict:
            if actor_dict[actor_id]["get_updates"] and not self.on_kill:
                logger.debug("Send updated actor_dict to %s", actor_id)
                self.send(
                    actor_dict[actor_id]["address"],
                    UpdateActorDictMsg(actor_dict),
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
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(self.parent.parent_address, True)

    def receiveMsg_CreateActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for CreateActorMsg. Create a new actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        logger.debug("Pending actors: %s", self.pending)
        if (msg.actor_id not in self.actor_dict) and (msg.actor_id not in self.pending):
            _actor_address = self._create_actor(msg.actor_type, msg.actor_id, sender)
            self.pending.append(msg.actor_id)

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

    def receiveMsg_UnSubscribeFromActorDictMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Unset the 'get_updates' flag for the requesting sender
        to not send updated actor dictionaries to it."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.actor_id in self.actor_dict:
            logger.debug("Unset 'get_updates' for %s", msg.actor_id)
            self.actor_dict[msg.actor_id]["get_updates"] = False
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
        self.check_integrity()
        self.send(sender, UpdateDeviceStatusesMsg(self.device_statuses))

    def check_integrity(self) -> bool:
        """Check integrity between self.actor_dict and self.device_statuses"""
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["is_device_actor"]:
                if actor_id not in self.device_statuses:
                    logger.critical(
                        "self.actor_dict contains %s that is not in %s",
                        actor_id,
                        self.device_statuses,
                    )
                    logger.critical("Emergency shutdown")
                    system_shutdown(with_error=True)
                    return False
        for actor_id in self.device_statuses:
            if actor_id not in self.actor_dict:
                logger.critical(
                    "self.device_statuses contains %s an actor that is not in %s",
                    actor_id,
                    self.actor_dict,
                )
                logger.critical("Emergency shutdown")
                system_shutdown(with_error=True)
                return False
        return True
