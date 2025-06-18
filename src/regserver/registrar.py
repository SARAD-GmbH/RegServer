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

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from overrides import overrides  # type: ignore
from sarad.global_helpers import decode_instr_id

from regserver.actor_messages import (ActorType, BaudRateAckMsg, BaudRateMsg,
                                      Frontend, GetHostInfoMsg, HostInfoMsg,
                                      KeepAliveMsg, KillMsg, MqttConnectMsg,
                                      PrepareMqttActorMsg, RescanAckMsg,
                                      RescanMsg, ReturnDeviceActorMsg,
                                      SetRtcAckMsg, SetRtcMsg, ShutdownAckMsg,
                                      ShutdownMsg, StartMonitoringAckMsg,
                                      StartMonitoringMsg, Status,
                                      StopMonitoringAckMsg, StopMonitoringMsg,
                                      TransportTechnology, UpdateActorDictMsg,
                                      UpdateDeviceStatusesMsg)
from regserver.base_actor import BaseActor
from regserver.config import (actor_config, backend_config, config,
                              frontend_config, mqtt_config, unique_id)
from regserver.helpers import short_id, transport_technology
from regserver.logger import logger
from regserver.modules.backend.is1.is1_listener import Is1Listener
from regserver.modules.backend.mdns.lan_host_creator import HostCreatorActor
from regserver.modules.backend.mqtt.mqtt_client_actor import MqttClientActor
from regserver.modules.backend.usb.cluster_actor import ClusterActor
from regserver.modules.frontend.mdns.mdns_scheduler import MdnsSchedulerActor
from regserver.modules.frontend.mqtt.mqtt_scheduler import MqttSchedulerActor
from regserver.shutdown import system_shutdown

ACTOR_DICT = {
    "mqtt_scheduler": MqttSchedulerActor,
    "mdns_scheduler": MdnsSchedulerActor,
    "host_creator": HostCreatorActor,
    "cluster": ClusterActor,
    "mqtt_client_actor": MqttClientActor,
    "is1_listener": Is1Listener,
}


class Registrar(BaseActor):
    """Actor providing a dictionary of devices"""

    @overrides
    def __init__(self):
        super().__init__()
        self.device_statuses = {}  # {device_id: {status_dict}}
        # a list of actors that are already created but not yet subscribed
        self.pending = []
        self.hosts = []  # List of Host objects seen since start
        self.rest_api = None  # Address of the Actor System

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.handleDeadLetters(startHandling=True)
        if Frontend.MQTT in frontend_config:
            self._create_actor(MqttSchedulerActor, "mqtt_scheduler", None)
        if Frontend.LAN in frontend_config:
            self._create_actor(MdnsSchedulerActor, "mdns_scheduler", None)
        if TransportTechnology.LAN in backend_config:
            self._create_actor(HostCreatorActor, "host_creator", None)
        if TransportTechnology.LOCAL in backend_config:
            self._create_actor(ClusterActor, "cluster", None)
        if TransportTechnology.MQTT in backend_config:
            self._create_actor(MqttClientActor, "mqtt_client_actor", None)
        if TransportTechnology.IS1 in backend_config:
            self._create_actor(Is1Listener, "is1_listener", None)
        keepalive_interval: float = actor_config["KEEPALIVE_INTERVAL"]
        if keepalive_interval:
            logger.debug(
                "Inner watchdog will be activated every %d s.", keepalive_interval
            )
            self.wakeupAfter(
                timedelta(seconds=keepalive_interval), payload="keep alive"
            )

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        actor_id = self._get_actor_id(msg.childAddress, self.child_actors)
        self.check_persistency(actor_id)
        super().receiveMsg_ChildActorExited(msg, sender)

    def receiveMsg_ControlFunctionalityMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for a message to switch frontends of backends on or off."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.actor_id in ACTOR_DICT:
            if msg.on:
                if msg.actor_id not in self.actor_dict:
                    self._create_actor(ACTOR_DICT[msg.actor_id], msg.actor_id, None)
            else:  # msg.on = False
                if msg.actor_id in self.actor_dict:
                    self.send(
                        self.actor_dict[msg.actor_id]["address"],
                        KillMsg(register=True),
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
            for actor_id in self.actor_dict:
                self.send(
                    self.actor_dict[actor_id]["address"], KeepAliveMsg(report=CHECK)
                )
        elif msg.payload == "check":
            success = True
            for actor_id in self.actor_dict:
                if not self.actor_dict[actor_id]["is_alive"]:
                    if (
                        self.actor_dict[actor_id].get("actor_type", ActorType.NONE)
                        == ActorType.DEVICE
                        and transport_technology(actor_id) == TransportTechnology.IS1
                    ):
                        logger.error(
                            "Actor %s did not respond to KeepAliveMsg.", actor_id
                        )
                    else:
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
        except (KeyError, TypeError):
            logger.error(
                "Great confusion. %s passed away during handling of KeepAliveMsg.",
                actor_id,
            )

    def _handle_existing_actor(self, sender, actor_id, actor_type):
        """Do whatever is required if the SubscribeMsg handler finds an actor
        that is already existing.

        Args:
            sender: Actor address of the Actor sending the SubscribeMsg
            actor_id: Id of the actor that shall be subscribed
            actor_type (ActorType): indicates a device actor

        Return:
            True: go on and register the new Actor
            False: don't register the new Actor
        """
        logger.error("The actor %s already exists in the system.", actor_id)
        if actor_type in (ActorType.DEVICE, ActorType.NODE):
            serial_number = decode_instr_id(short_id(actor_id))[2]
            if serial_number == 65535:
                logger.info(
                    "%s is a virgin SARAD instrument. We are using the last attached device.",
                    serial_number,
                )
                self.send(self.actor_dict[actor_id]["address"], KillMsg(register=True))
            elif transport_technology(actor_id) == TransportTechnology.LAN:
                logger.debug(
                    "%s is availabel from different hosts. First come, first served.",
                    actor_id,
                )
                self.send(sender, KillMsg(register=False))
                return False
            else:
                logger.info(
                    "We will use the last attached instrument and kill the old Actor."
                )
                self.send(self.actor_dict[actor_id]["address"], KillMsg(register=True))
        else:
            logger.critical("-> Emergency shutdown")
            system_shutdown()
            return False
        return True

    def _handle_device_actor(self, sender, actor_id):
        """Do whatever is required if the SubscribeMsg handler finds a Device
        Actor to be subscribed.

        Args:
            sender: Actor address of the Actor sending the SubscribeMsg
            actor_id: Id of the actor that shall be subscribed
        """
        keep_new_actor = True
        new_device_id = actor_id
        for old_device_id in self.device_statuses:
            old_tt = transport_technology(old_device_id)
            new_tt = transport_technology(new_device_id)
            if (
                (short_id(old_device_id) == short_id(new_device_id))
                and (new_device_id != old_device_id)
                and (
                    old_tt
                    in [
                        TransportTechnology.LOCAL,
                        TransportTechnology.LAN,
                        TransportTechnology.MQTT,
                        TransportTechnology.IS1,
                    ]
                )
            ):
                logger.debug("New device_id: %s", new_device_id)
                logger.debug("Old device_id: %s", old_device_id)
                if new_tt == TransportTechnology.LOCAL:
                    logger.debug(
                        "Keep new %s and kill the old %s",
                        new_device_id,
                        old_device_id,
                    )
                    keep_new_actor = True
                    self.send(self.actor_dict[old_device_id]["address"], KillMsg())
                elif (new_tt == TransportTechnology.LAN) and (
                    old_tt == TransportTechnology.IS1
                ):
                    logger.debug(
                        "A WLAN instrument might have been connected to another PC via USB."
                    )
                    # TODO Check whether old_device_id is still active (refer to SARAD/RegServer#79)
                    logger.warning(
                        "A WLAN instrument connected via USB to a remote host will be ignored."
                    )
                    keep_new_actor = False
                    self.send(sender, KillMsg())
                elif (new_tt == TransportTechnology.IS1) and (
                    old_tt == TransportTechnology.MQTT
                ):
                    logger.error(
                        "Ignore retained MQTT message in favour of new IS1 Device Actor."
                    )
                    # Since there is no retained MQTT message, this should never happen.
                    keep_new_actor = True
                    self.send(self.actor_dict[old_device_id]["address"], KillMsg())
                else:
                    logger.debug("Keep device actor %s in place.", old_device_id)
                    keep_new_actor = False
                    self.send(sender, KillMsg())
        self.device_statuses[actor_id] = self.device_statuses.get(actor_id, {})
        if keep_new_actor:
            logger.debug("Subscribe %s to device statuses dict", actor_id)
            self._subscribe_to_device_status_msg(sender)
            if transport_technology(actor_id) in [
                TransportTechnology.LOCAL,
                TransportTechnology.IS1,
            ]:
                for idx, host in enumerate(self.hosts):
                    if host.host == "127.0.0.1":
                        para = {"state": 2}
                        host = replace(host, **para)
                        self.hosts[idx] = host
                        break

    def receiveMsg_SubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SubscribeMsg from any actor."""
        if self.on_kill:
            return
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.actor_id in self.pending:
            self.pending.remove(msg.actor_id)
        if msg.keep_alive:
            self._is_alive(msg.actor_id)
            return
        if msg.actor_id in self.actor_dict:
            if not self._handle_existing_actor(sender, msg.actor_id, msg.actor_type):
                return
        self.actor_dict[msg.actor_id] = {
            "address": sender,
            "parent": msg.parent,
            "actor_type": msg.actor_type,
            "get_updates": msg.get_updates,
            "is_alive": True,
        }
        logger.info("%s added to actor_dict", msg.actor_id)
        if msg.actor_id == "mqtt_scheduler":
            self.send(
                sender,
                PrepareMqttActorMsg(
                    client_id=unique_id(config["IS_ID"]),
                    group=mqtt_config["GROUP"],
                ),
            )
            self.send(sender, MqttConnectMsg())
        elif msg.actor_id == "mqtt_client_actor":
            self.send(
                sender,
                PrepareMqttActorMsg(
                    client_id=mqtt_config["MQTT_CLIENT_ID"],
                    group=mqtt_config["GROUP"],
                ),
            )
            self.send(sender, MqttConnectMsg())
        logger.debug("MQTT group of %s = %s", msg.actor_id, mqtt_config["GROUP"])
        if msg.actor_type in (ActorType.DEVICE, ActorType.NODE):
            self._handle_device_actor(sender, msg.actor_id)
        elif msg.actor_type == ActorType.HOST:
            self.send(sender, GetHostInfoMsg())
        self._send_updates(self.actor_dict)
        return

    def receiveMsg_UnsubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UnsubscribeMsg from any actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        actor_id = None
        for this_actor_id in self.actor_dict:
            if self.actor_dict[this_actor_id]["address"] == msg.actor_address:
                actor_id = this_actor_id
                break
        if actor_id is None:
            return
        status_dict = self.device_statuses.pop(actor_id, None)
        if (status_dict is not None) and (
            transport_technology(actor_id)
            in [TransportTechnology.LOCAL, TransportTechnology.IS1]
        ):
            local_device_connected = False
            for device_id in self.device_statuses:
                if transport_technology(device_id) in [
                    TransportTechnology.LOCAL,
                    TransportTechnology.IS1,
                ]:
                    local_device_connected = True
                    break
            if not local_device_connected:
                for idx, host in enumerate(self.hosts):
                    if host.host == "127.0.0.1":
                        para = {"state": 1}
                        host = replace(host, **para)
                        self.hosts[idx] = host
                        break
        if self.actor_dict[actor_id].get("actor_type") == ActorType.HOST:
            index = None
            for host in self.hosts:
                if host.host == actor_id:
                    index = self.hosts.index(host)
                    break
            if index is not None:
                self.hosts[index].state = 0
        removed_actor = self.actor_dict.pop(actor_id, None)
        logger.info("%s removed from actor_dict", actor_id)
        if removed_actor is not None:
            self.check_persistency(actor_id)
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
            if (dict["actor_type"] in (ActorType.DEVICE, ActorType.NODE))
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
        if device_id in self.device_statuses:
            self.device_statuses[device_id] = device_status
        else:
            logger.warning(
                "Received %s from %s, but the actor is not registered.", msg, device_id
            )

    def receiveMsg_GetDeviceStatusesMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle request to deliver the device statuses of all instruments."""
        sending_actor = "REST API"
        for sender_id, actor_dict in self.actor_dict.items():
            if actor_dict["address"] == sender:
                sending_actor = sender_id
        if sending_actor != "REST API":
            logger.debug("%s for %s from %s", msg, self.my_id, sending_actor)
        self.check_integrity()
        device_statuses = {}
        for device, status in self.device_statuses.items():
            if status:
                device_statuses[device] = status
        self.send(sender, UpdateDeviceStatusesMsg(device_statuses))

    def receiveMsg_RescanMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the RescanMsg to all Host Actors."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] == ActorType.HOST:
                logger.debug(
                    "Forward RescanMsg(%s) to %s", msg.host, self.actor_dict[actor_id]
                )
                self.send(
                    self.actor_dict[actor_id]["address"], RescanMsg(host=msg.host)
                )
        self.send(sender, RescanAckMsg(Status.OK))

    def receiveMsg_ShutdownMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the ShutdownMsg to all Host Actors."""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] == ActorType.HOST:
                self.send(
                    self.actor_dict[actor_id]["address"],
                    ShutdownMsg(password=msg.password, host=msg.host),
                )
        self.send(sender, ShutdownAckMsg(Status.OK))
        if (msg.host is None) or (msg.host == "127.0.0.1"):
            system_shutdown()

    def receiveMsg_StartMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the StartMonitoringMsg to Device Actors."""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        success = False
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] == ActorType.DEVICE:
                if (msg.instr_id is None) or (short_id(actor_id) == msg.instr_id):
                    self.send(
                        self.actor_dict[actor_id]["address"],
                        StartMonitoringMsg(
                            start_time=msg.start_time, instr_id=msg.instr_id
                        ),
                    )
                    success = True
                    self.rest_api = sender
                    break
        if not success:
            self.send(
                sender,
                StartMonitoringAckMsg(
                    msg.instr_id,
                    Status.NOT_FOUND,
                    msg.start_time - datetime.now(timezone.utc),
                ),
            )

    def receiveMsg_StartMonitoringAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the StartMonitoringAckMsg to REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(self.rest_api, msg)

    def receiveMsg_StopMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the StopMonitoringMsg to Device Actors."""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        success = False
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] == ActorType.DEVICE:
                if (msg.instr_id is None) or (short_id(actor_id) == msg.instr_id):
                    self.send(
                        self.actor_dict[actor_id]["address"],
                        StopMonitoringMsg(instr_id=msg.instr_id),
                    )
                    success = True
                    self.rest_api = sender
                    break
        if not success:
            self.send(
                sender,
                StopMonitoringAckMsg(msg.instr_id, Status.NOT_FOUND),
            )

    def receiveMsg_StopMonitoringAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the StopMonitoringAckMsg to REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(self.rest_api, msg)

    def receiveMsg_BaudRateMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the BaudRateMsg to Device Actors."""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] == ActorType.DEVICE:
                if (msg.instr_id is None) or (short_id(actor_id) == msg.instr_id):
                    self.send(
                        self.actor_dict[actor_id]["address"],
                        BaudRateMsg(baud_rate=msg.baud_rate, instr_id=msg.instr_id),
                    )
        self.send(sender, BaudRateAckMsg(Status.OK))

    def receiveMsg_SetRtcMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the SetRtcMsg to Device Actors."""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        success = False
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] == ActorType.DEVICE:
                if (msg.instr_id is None) or (short_id(actor_id) == msg.instr_id):
                    self.send(
                        self.actor_dict[actor_id]["address"],
                        SetRtcMsg(instr_id=msg.instr_id),
                    )
                    success = True
                    self.rest_api = sender
                    break
        if not success:
            self.send(sender, SetRtcAckMsg(msg.instr_id, Status.NOT_FOUND))

    def receiveMsg_SetRtcAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward the SetRtcAckMsg to REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(self.rest_api, msg)

    def receiveMsg_HostInfoMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for HostInfoMsg indicating a change in the host information"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for new_host in msg.hosts:
            known = False
            for known_host in self.hosts:
                if new_host.host == known_host.host:
                    known = True
                    if new_host not in self.hosts:
                        # update host information
                        index = self.hosts.index(known_host)
                        self.hosts.pop(index)
                        self.hosts.insert(index, new_host)
                    break
            if not known:
                self.hosts.append(new_host)
        logger.debug("Known hosts: %s", self.hosts)

    def receiveMsg_GetHostInfoMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetHostInfoMsg asking to send the list of hosts"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(sender, HostInfoMsg(hosts=self.hosts))

    def check_integrity(self) -> bool:
        """Check integrity between self.actor_dict and self.device_statuses"""
        for actor_id in self.actor_dict:
            if self.actor_dict[actor_id]["actor_type"] in (
                ActorType.DEVICE,
                ActorType.NODE,
            ):
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

    def check_persistency(self, actor_id) -> bool:
        """Make sure that all Actors that shall run all the time stay alive."""
        if (
            actor_id
            in [
                "mqtt_scheduler",
                "mdns_scheduler",
                "host_creator",
                "cluster",
                "mqtt_client_actor",
                "is1_listener",
            ]
            and not self.on_kill
        ):
            logger.critical("%s was killed. This should never happen.", actor_id)
            system_shutdown(with_error=True)
            return False
        return True

    def receiveMsg_RecentValueMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for RecentValueMsg providing measuring values from a Device Actor"""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        # TODO Send values to a database
