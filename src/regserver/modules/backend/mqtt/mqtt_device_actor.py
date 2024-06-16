"""Main actor of the Registration Server -- implementation for MQTT

:Created:
    2021-02-16

:Authors:
    | Yang, Yixiang
    | Michael Strey <strey@sarad.de>

"""

import json
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from overrides import overrides  # type: ignore
from regserver.actor_messages import (MqttPublishMsg, MqttSubscribeMsg,
                                      MqttUnsubscribeMsg, RecentValueMsg,
                                      ResurrectMsg, RxBinaryMsg, Status)
from regserver.config import mqtt_config
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.modules.device_actor import DeviceBaseActor
from sarad.instrument import Gps


class ReserveDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for RESERVE dict."""
    Pending: bool
    Active: bool


class SendDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for SEND dict."""
    Pending: bool
    CMD_ID: int


class ValueDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for VALUE dict."""
    Pending: bool


class AckDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for ACK dict."""
    Pending: bool
    req: str


class StateDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for MQTT Actor state."""
    RESERVE: ReserveDict
    SEND: SendDict
    VALUE: ValueDict
    WAIT_FOR_ACK: AckDict


class MqttDeviceActor(DeviceBaseActor):
    """Actor interacting with a new device"""

    @overrides
    def __init__(self):
        super().__init__()
        self.qos = 1
        self.allowed_sys_topics = {
            "CTRL": "",
            "RESERVE": "",
            "VALUE": "",
            "CMD": "",
            "MSG": "",
            "META": "",
            "ACK": "",
        }
        self.allowed_sys_options = {
            "CTRL": "control",
            "RESERVE": "reservation",
            "VALUE": "value",
            "CMD": "cmd",
            "MSG": "msg",
            "META": "meta",
            "ACK": "ack",
        }
        self.state: StateDict = {
            "RESERVE": {
                "Pending": False,
                # if there is a reply to wait for, then it should be true
                "Active": False,
                # store the reservation status
            },
            "SEND": {
                "Pending": False,
                # if there is a reply to wait for, then it should be true
                "CMD_ID": 0,
                # store the CMD ID
            },
            "VALUE": {
                "Pending": False,
                # if there is a reply to wait for, then it should be true
            },
            "WAIT_FOR_ACK": {
                "Pending": False,
                # if there is a reply to wait for, then it should be true
                "req": "",
                # the type of request as in the request message
            },
        }
        self.cmd_id = 0
        self.last_message = ""
        self.is_id = ""

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from Redirector Actor."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        data = msg.data
        if (data is None) or (not isinstance(data, bytes)):
            logger.error(
                "[SEND] no data to send or the data are not bytes",
            )
            return
        logger.debug("To send: %s", data)
        logger.debug("CMD ID is: %s", self.cmd_id)
        self.state["SEND"]["Pending"] = True
        self.state["SEND"]["CMD_ID"] = self.cmd_id
        self.send(
            self.parent.parent_address,
            MqttPublishMsg(
                topic=self.allowed_sys_topics["CMD"],
                payload=bytes([self.cmd_id]) + data,
                qos=self.qos,
                retain=False,
            ),
        )
        if self.cmd_id == 255:
            self.cmd_id = 0
        else:
            self.cmd_id = self.cmd_id + 1
        logger.debug("[SEND] send status is %s", self.state["SEND"]["Pending"])

    @overrides
    def _request_reserve_at_is(self):
        """Request the reservation of an instrument at the Instrument Server.

        Args:
            self.reserve_device_msg: Dataclass identifying the requesting app, host and user.
        """
        super()._request_reserve_at_is()
        if not self.state["RESERVE"]["Pending"]:
            self.state["RESERVE"]["Pending"] = True
            self.send(
                self.parent.parent_address,
                MqttPublishMsg(
                    topic=self.allowed_sys_topics["CTRL"],
                    payload=json.dumps(
                        {
                            "Req": "reserve",
                            "App": self.reserve_device_msg.app,
                            "Host": self.reserve_device_msg.host,
                            "User": self.reserve_device_msg.user,
                        }
                    ),
                    qos=self.qos,
                    retain=False,
                ),
            )

    @overrides
    def _handle_reserve_reply_from_is(self, success):
        if success is Status.NOT_FOUND:
            logger.warning("Reserve request to %s timed out", self.my_id)
        super()._handle_reserve_reply_from_is(success)

    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for PrepareMqttActorMsg from MQTT Listener"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.is_id = msg.client_id
        for k in self.allowed_sys_topics:
            self.allowed_sys_topics[k] = (
                f"{msg.group}/{msg.client_id}/"
                + f"{short_id(self.my_id)}/{self.allowed_sys_options[k]}"
            )
            logger.debug("allowed topic: %s", self.allowed_sys_topics[k])
        logger.debug("Subscribe MQTT actor to the 'reservation' topic")
        reserve_topic = self.allowed_sys_topics["RESERVE"]
        self.send(
            self.parent.parent_address, MqttSubscribeMsg([(reserve_topic, self.qos)])
        )

    @overrides
    def _request_free_at_is(self):
        """Forward the free request to the broker."""
        self.send(
            self.parent.parent_address,
            MqttPublishMsg(
                topic=self.allowed_sys_topics["CTRL"],
                payload=json.dumps({"Req": "free"}),
                qos=self.qos,
                retain=False,
            ),
        )
        self.send(
            self.parent.parent_address,
            MqttUnsubscribeMsg([self.allowed_sys_topics["MSG"]]),
        )
        super()._request_free_at_is()

    @overrides
    def _handle_free_reply_from_is(self, success):
        if success is Status.NOT_FOUND:
            logger.warning("Free request to %s timed out", self.my_id)
        super()._handle_free_reply_from_is(success)

    def receiveMsg_MqttReceiveMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle a message received from the MQTT broker"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.topic == self.allowed_sys_topics["RESERVE"]:
            self.on_reserve(msg.payload)
        elif msg.topic == self.allowed_sys_topics["MSG"]:
            self.on_msg(msg.payload)
        elif msg.topic == self.allowed_sys_topics["VALUE"]:
            self.on_value(msg.payload)
        elif msg.topic == self.allowed_sys_topics["ACK"]:
            self.on_ack(msg.payload)

    @overrides
    def _request_recent_value_at_is(self, msg, sender):
        super()._request_recent_value_at_is(msg, sender)
        self.send(
            self.parent.parent_address,
            MqttSubscribeMsg([(self.allowed_sys_topics["VALUE"], self.qos)]),
        )
        self.state["VALUE"]["Pending"] = True
        self.send(
            self.parent.parent_address,
            MqttPublishMsg(
                topic=self.allowed_sys_topics["CTRL"],
                payload=json.dumps(
                    {
                        "req": "value",
                        "client": mqtt_config["MQTT_CLIENT_ID"],
                        "component": msg.component,
                        "sensor": msg.sensor,
                        "measurand": msg.measurand,
                    }
                ),
                qos=self.qos,
                retain=False,
            ),
        )

    @overrides
    def _request_set_rtc_at_is(self, confirm=False):
        super()._request_set_rtc_at_is(confirm)
        self.send(
            self.parent.parent_address,
            MqttSubscribeMsg([(self.allowed_sys_topics["ACK"], self.qos)]),
        )
        self.state["WAIT_FOR_ACK"]["Pending"] = True
        self.state["WAIT_FOR_ACK"]["req"] = "set-rtc"
        self.send(
            self.parent.parent_address,
            MqttPublishMsg(
                topic=self.allowed_sys_topics["CTRL"],
                payload=json.dumps(
                    {
                        "req": "set-rtc",
                        "client": mqtt_config["MQTT_CLIENT_ID"],
                    }
                ),
                qos=self.qos,
                retain=False,
            ),
        )

    @overrides
    def _request_start_monitoring_at_is(
        self, start_time=datetime.now(timezone.utc), confirm=False
    ):
        super()._request_start_monitoring_at_is(confirm)
        self.send(
            self.parent.parent_address,
            MqttSubscribeMsg([(self.allowed_sys_topics["ACK"], self.qos)]),
        )
        self.state["WAIT_FOR_ACK"]["Pending"] = True
        self.state["WAIT_FOR_ACK"]["req"] = "monitor"
        self.send(
            self.parent.parent_address,
            MqttPublishMsg(
                topic=self.allowed_sys_topics["CTRL"],
                payload=json.dumps(
                    {
                        "req": "monitor",
                        "client": mqtt_config["MQTT_CLIENT_ID"],
                        "start_time": start_time,
                    },
                    default=str,
                ),
                qos=self.qos,
                retain=False,
            ),
        )

    def on_value(self, payload):
        """Handler for MQTT messages containing measuring values from instrument"""
        value_dict = json.loads(payload)
        state = self.state.get("VALUE", {})
        client_id = mqtt_config["MQTT_CLIENT_ID"]
        it_is_for_me = bool(
            state
            and state.get("Pending", False)
            and client_id == value_dict.get("client", "")
        )
        logger.debug("Is it for me? %s, %s", state, value_dict)
        if self.value_lock.value and it_is_for_me:
            self.send(
                self.parent.parent_address,
                MqttUnsubscribeMsg([self.allowed_sys_topics["VALUE"]]),
            )
            if value_dict.get("gps", False):
                gps = Gps(
                    valid=value_dict["gps"]["valid"],
                    latitude=value_dict["gps"]["lat"],
                    longitude=value_dict["gps"]["lon"],
                    altitude=value_dict["gps"]["alt"],
                    deviation=value_dict["gps"]["dev"],
                )
            else:
                gps = None
            self._handle_recent_value_reply_from_is(
                RecentValueMsg(
                    status=Status(value_dict.get("status", 0)),
                    instr_id=self.instr_id,
                    component_name=value_dict.get("c_name", ""),
                    sensor_name=value_dict.get("s_name", ""),
                    measurand_name=value_dict.get("m_name", ""),
                    measurand=value_dict.get("measurand", ""),
                    operator=value_dict.get("operator", ""),
                    value=value_dict.get("value", 0),
                    unit=value_dict.get("unit", ""),
                    timestamp=value_dict.get("time", 0),
                    utc_offset=value_dict.get("utc_offset", 0),
                    sample_interval=value_dict.get("interval", 0),
                    gps=gps,
                )
            )
            self.state["VALUE"]["Pending"] = False

    def on_ack(self, payload):
        """Handler for MQTT messages containing an acknowledgement"""
        ack_dict = json.loads(payload)
        state = self.state.get("WAIT_FOR_ACK", {})
        client_id = mqtt_config["MQTT_CLIENT_ID"]
        it_is_for_me = bool(
            state
            and state.get("Pending", False)
            and client_id == ack_dict.get("client", "")
        )
        logger.debug("Is it for me? %s, %s", state, ack_dict)
        if self.ack_lock.value and it_is_for_me:
            self.send(
                self.parent.parent_address,
                MqttUnsubscribeMsg([self.allowed_sys_topics["ACK"]]),
            )
            req = ack_dict.get("req", "")
            waiting_for = self.state["WAIT_FOR_ACK"].get("req", "")
            if (req == "set-rtc") and (waiting_for == "set-rtc"):
                self._handle_set_rtc_reply_from_is(
                    status=Status(ack_dict.get("status", 98)),
                    confirm=True,
                    utc_offset=ack_dict.get("utc_offset", -13),
                    wait=ack_dict.get("wait", 0),
                )
                self.state["WAIT_FOR_ACK"]["Pending"] = False
            elif (req == "monitor") and (waiting_for == "monitor"):
                self._handle_start_monitoring_reply_from_is(
                    status=Status(ack_dict.get("status", 98)),
                    confirm=True,
                    offset=timedelta(seconds=ack_dict.get("offset", 0)),
                )
                self.state["WAIT_FOR_ACK"]["Pending"] = False
            elif (req == "config") and (waiting_for == "config"):
                # TODO
                self.state["WAIT_FOR_ACK"]["Pending"] = False
            else:
                logger.error("Invalid ACK message: %s", ack_dict)

    def on_reserve(self, payload):
        """Handler for MQTT messages regarding reservation of instruments"""
        reservation_status = Status.ERROR
        try:
            reservation = json.loads(payload)
        except (TypeError, json.decoder.JSONDecodeError):
            if payload == b"":
                logger.debug("Retained reserve topic removed")
            else:
                logger.warning("Cannot decode %s", payload)
            return
        if reservation == self.last_message:
            logger.debug("We have already got message %s", reservation)
            return
        self.last_message = reservation
        logger.debug("%s received [on_reserve]: %s", self.my_id, reservation)
        instr_status = reservation.get("Active")
        app = reservation.get("App")
        host = reservation.get("Host")
        user = reservation.get("User")
        timestamp = reservation.get("Timestamp")
        if self.state["RESERVE"]["Pending"]:
            if (
                (instr_status)
                and (app == self.reserve_device_msg.app)
                and (host == self.reserve_device_msg.host)
                and (user == self.reserve_device_msg.user)
            ):
                logger.debug(
                    "MQTT actor receives permission for reservation on instrument %s",
                    self.my_id,
                )
                if timestamp is None:
                    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                msg_topic = self.allowed_sys_topics["MSG"]
                self.send(
                    self.parent.parent_address,
                    MqttSubscribeMsg([(msg_topic, self.qos)]),
                )
                reservation_status = Status.OK
            else:
                logger.debug(
                    "MQTT actor receives decline of reservation on instrument %s",
                    self.my_id,
                )
                reservation_status = Status.OCCUPIED
            reservation_active = bool(
                reservation_status in [Status.OK, Status.OK_SKIPPED, Status.OK_UPDATED]
            )
            self.state["RESERVE"]["Active"] = reservation_active
            logger.debug("Reservation status: %s", reservation_status)
            self._handle_reserve_reply_from_is(
                reservation_status
            )  # create redirector actor
            self.state["RESERVE"]["Pending"] = False
            return
        if not reservation.get("Active", False):
            logger.debug("Free status: %s", reservation_status)
            self._handle_free_reply_from_is(Status.OK)
            return
        logger.debug(
            "%s is now occupied by %s, %s @ %s",
            self.my_id,
            app,
            user,
            host,
        )
        reservation_status = Status.OCCUPIED
        if self.device_status.get("Reservation", False):
            if self.device_status["Reservation"].get("IP", False):
                reservation["IP"] = self.device_status["Reservation"]["IP"]
            if self.device_status["Reservation"].get("Port", False):
                reservation["Port"] = self.device_status["Reservation"]["Port"]
        self.device_status["Reservation"] = reservation
        self._handle_reserve_reply_from_is(reservation_status)

    def on_msg(self, payload):
        """Handler for MQTT messages regarding binary messages from instrument"""
        logger.debug("Send status is: %s", self.state["SEND"]["Pending"])
        if not isinstance(payload, bytes):
            logger.error(
                "Received a reply that should be bytes while not; the message is %s",
                payload,
            )
            return
        if len(payload) == 0:
            logger.error("Received an empty reply")
            return
        if self.state["SEND"]["Pending"]:
            re_cmd_id = payload[0]
            st_cmd_id = self.state["SEND"]["CMD_ID"]
            logger.debug("Received CMD ID is %s", re_cmd_id)
            logger.debug("Stored CMD ID is %s", self.state["SEND"]["CMD_ID"])
            if re_cmd_id == st_cmd_id:
                self.state["SEND"]["Pending"] = False
                logger.debug(
                    "MQTT actor receives a binary reply %s from instrument %s",
                    payload[1:],
                    self.my_id,
                )
                self.send(
                    self.redirector_actor,
                    RxBinaryMsg(payload[1:]),
                )
                return
            logger.warning(
                (
                    "MQTT actor receives a binary reply %s with an unexpected "
                    "CMD ID %s from instrument %s"
                ),
                payload,
                re_cmd_id,
                self.my_id,
            )
            return
        logger.warning(
            "MQTT actor receives an unknown binary reply %s from instrument %s",
            payload,
            self.my_id,
        )

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        try:
            _ip = self.device_status["Reservation"]["IP"]
            logger.debug(
                "%s is still reserved by my host -> sending Free request", self.my_id
            )
            self._request_free_at_is()
        except KeyError:
            pass
        try:
            self._send_reservation_status_msg()
        except AttributeError as exception:
            logger.error(exception)
        if not self.on_kill and resurrect:
            self.send(self.parent.parent_address, ResurrectMsg(is_id=self.is_id))
        try:
            super()._kill_myself(register=register, resurrect=resurrect)
        except TypeError:
            pass
