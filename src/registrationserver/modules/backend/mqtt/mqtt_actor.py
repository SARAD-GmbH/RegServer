"""Main actor of the Registration Server -- implementation for MQTT

:Created:
    2021-02-16

:Authors:
    | Yang, Yixiang
    | Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_actor.puml
"""
import datetime
import json

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import KillMsg, RxBinaryMsg, Status
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.backend.mqtt.mqtt_base_actor import \
    MqttBaseActor
from registrationserver.modules.device_actor import DeviceBaseActor

logger.debug("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor, MqttBaseActor):
    """Actor interacting with a new device"""

    @overrides
    def __init__(self):
        super().__init__()
        self.allowed_sys_topics = {
            "CTRL": "/control",
            "RESERVE": "/reservation",
            "CMD": "/cmd",
            "MSG": "/msg",
            # "META": "/meta",
        }
        self.allowed_sys_options = {
            "CTRL": "/control",
            "RESERVE": "/reservation",
            "CMD": "/cmd",
            "MSG": "/msg",
            # "META": "/meta",
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
        self.msg_id["UNSUBSCRIBE"] = None
        self.msg_id["PUBLISH"] = None

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
        _msg = {
            "topic": self.allowed_sys_topics["CMD"],
            "payload": bytes([self.cmd_id]) + data,
            "qos": 0,
        }
        _re = self._publish(_msg)
        if self.cmd_id == 255:
            self.cmd_id = 0
        else:
            self.cmd_id = self.cmd_id + 1
        if not _re:
            logger.error(
                "Failed to publish message with ID %s in topic %s",
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
            )
            self.state["SEND"]["Pending"] = False
            self.state["SEND"]["CMD_ID"] = None
            return
        logger.debug("[SEND] send status is %s", self.state["SEND"]["Pending"])

    @overrides
    def _reserve_at_is(self):
        """Request the reservation of an instrument at the Instrument Server.

        Args:
            self.app: String identifying the requesting app.
            self.host: String identifying the host running the app.
            self.user: String identifying the user of the app.
        """
        if not self.state["RESERVE"]["Pending"]:
            _msg = {
                "topic": self.allowed_sys_topics["CTRL"],
                "payload": json.dumps(
                    {
                        "Req": "reserve",
                        "App": self.app,
                        "Host": self.host,
                        "User": self.user,
                    }
                ),
                "qos": 0,
                "retain": True,
            }
            self.state["RESERVE"]["Pending"] = True
            if not self._publish(_msg):
                self.state["RESERVE"]["Pending"] = False
                return
            logger.debug("[Reserve at IS]: Waiting for reply to reservation request")

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        """Handle the return message confirming that the redirector actor was killed.

        Args:
            msg: ChildActorExited message
            sender: usually the redirector actor
        """
        logger.debug("Redirector actor exited")
        _msg = {
            "topic": self.allowed_sys_topics["CTRL"],
            "payload": json.dumps({"Req": "free"}),
            "qos": 0,
            "retain": True,
        }
        _re = self._publish(_msg)
        logger.info("Unsubscribe MQTT actor from 'msg' topic")
        self._unsubscribe_topic([self.allowed_sys_topics["MSG"]])
        DeviceBaseActor.receiveMsg_ChildActorExited(self, msg, sender)
        MqttBaseActor.receiveMsg_ChildActorExited(self, msg, sender)

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.on_publish = self.on_publish
        for k in self.allowed_sys_topics:
            self.allowed_sys_topics[k] = (
                msg.is_id + "/" + short_id(self.my_id) + self.allowed_sys_options[k]
            )
            logger.debug("allowed topic: %s", self.allowed_sys_topics[k])
        self.mqttc.message_callback_add(
            self.allowed_sys_topics["RESERVE"], self.on_reserve
        )
        self.mqttc.message_callback_add(self.allowed_sys_topics["MSG"], self.on_msg)
        logger.debug(
            "When I die, the instrument shall be given free. This is my last will."
        )
        self.mqttc.will_set(
            self.allowed_sys_topics["CTRL"],
            payload=json.dumps({"Req": "free"}),
            qos=0,
            retain=True,
        )
        if self._connect(self.mqtt_broker, self.port):
            self.mqttc.loop_start()

    def on_reserve(self, _client, _userdata, message):
        """Handler for MQTT messages regarding reservation of instruments"""
        reservation_status = Status.ERROR
        reservation = json.loads(message.payload)
        logger.debug("Update reservation state of %s: %s", self.my_id, reservation)
        self.device_status["Reservation"] = reservation
        if self.state["RESERVE"]["Pending"]:
            instr_status = reservation.get("Active")
            app = reservation.get("App")
            host = reservation.get("Host")
            user = reservation.get("User")
            timestamp = reservation.get("Timestamp")
            if (
                (instr_status)
                and (app == self.app)
                and (host == self.host)
                and (user == self.user)
            ):
                logger.debug(
                    "MQTT actor receives permission for reservation on instrument %s",
                    self.my_id,
                )
                if timestamp is None:
                    timestamp = (
                        datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    )
                if not self._subscribe_topic([(self.allowed_sys_topics["MSG"], 0)]):
                    logger.error(
                        "Subscription to %s went wrong", self.allowed_sys_topics["MSG"]
                    )
                    return
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
            self._forward_reservation(reservation_status)  # create redirector actor
            self.state["RESERVE"]["Pending"] = False
            return
        logger.warning(
            "MQTT actor received a reply to a non-requested reservation on instrument %s",
            self.my_id,
        )

    def on_msg(self, _client, _userdata, message):
        """Handler for MQTT messages regarding binary messages from instrument"""
        payload = message.payload
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
    def on_connect(self, client, userdata, flags, result_code):
        super().on_connect(client, userdata, flags, result_code)
        logger.debug("Subscribe MQTT actor to the 'reservation' topic")
        reserve_topic = self.allowed_sys_topics["RESERVE"]
        return_code, self.msg_id["SUBSCRIBE"] = self.mqttc.subscribe(reserve_topic, 0)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.critical("Subscription to %s went wrong", reserve_topic)
            self.send(self.registrar, KillMsg())

    def on_publish(self, _client, _userdata, msg_id):
        """Here should be a docstring."""
        # self.rc_pub = 0
        logger.debug("[on_publish] Message-ID %d was published to the broker", msg_id)
        if msg_id == self.msg_id["PUBLISH"]:
            logger.debug("Publish: msg_id is matched")
