"""Main actor of the Registration Server -- implementation for MQTT

:Created:
    2021-02-16

:Authors:
    | Yang, Yixiang
    | Michael Strey <strey@sarad.de>

"""
import json
from datetime import datetime, timezone

from overrides import overrides  # type: ignore
from regserver.actor_messages import (MqttPublishMsg, MqttSubscribeMsg,
                                      MqttUnsubscribeMsg, ResurrectMsg,
                                      RxBinaryMsg, Status)
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.modules.device_actor import DeviceBaseActor


class MqttDeviceActor(DeviceBaseActor):
    """Actor interacting with a new device"""

    @overrides
    def __init__(self):
        super().__init__()
        self.qos = 2
        self.allowed_sys_topics = {
            "CTRL": "",
            "RESERVE": "",
            "CMD": "",
            "MSG": "",
            "META": "",
        }
        self.allowed_sys_options = {
            "CTRL": "control",
            "RESERVE": "reservation",
            "CMD": "cmd",
            "MSG": "msg",
            "META": "meta",
        }
        self.state = {
            "RESERVE": {
                "Pending": False,
                # if there be a reply to wait for, then it should be true
                "Active": None,
                # store the reservation status
            },
            "SEND": {
                "Pending": False,
                # if there be a reply to wait for, then it should be true
                "CMD_ID": None,
                # store the CMD ID
                "Reply": None,
                "Sender": None,
                # store the address of the sender
            },
        }
        self.cmd_id = 0
        self.last_message = ""

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
        self.state["SEND"]["CMD_ID"] = bytes([self.cmd_id])
        logger.debug("CMD ID is: %s", self.state["SEND"]["CMD_ID"])
        self.state["SEND"]["Sender"] = sender
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
        for k in self.allowed_sys_topics:
            self.allowed_sys_topics[k] = (
                f"{msg.group}/{msg.client_id}/"
                + f"{short_id(self.my_id)}/{self.allowed_sys_options[k]}"
            )
            logger.debug("allowed topic: %s", self.allowed_sys_topics[k])
        logger.debug("Subscribe MQTT actor to the 'reservation' topic")
        reserve_topic = self.allowed_sys_topics["RESERVE"]
        self.send(self.parent.parent_address, MqttSubscribeMsg([(reserve_topic, 2)]))

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
        if msg.topic == self.allowed_sys_topics["MSG"]:
            self.on_msg(msg.payload)

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
                    self.parent.parent_address, MqttSubscribeMsg([(msg_topic, 2)])
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
            st_cmd_id = int.from_bytes(self.state["SEND"]["CMD_ID"], "big")
            logger.debug("Received CMD ID is %s", re_cmd_id)
            logger.debug("Stored CMD ID is %s", self.state["SEND"]["CMD_ID"])
            if re_cmd_id == st_cmd_id:
                self.state["SEND"]["Pending"] = False
                logger.debug(
                    "MQTT actor receives a binary reply %s from instrument %s",
                    payload[1:],
                    self.my_id,
                )
                self.state["SEND"]["Reply"] = payload[1:]
                self.send(
                    self.redirector_actor,
                    RxBinaryMsg(self.state["SEND"]["Reply"]),
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
            # TODO Think about resurrection!
            self.send(
                self.parent.parent_address,
                ResurrectMsg(
                    instr_id=self.instr_id,
                    device_status=self.device_status,
                ),
            )
        try:
            super()._kill_myself(register=register, resurrect=resurrect)
        except TypeError:
            pass
