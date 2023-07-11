"""Base actor for all actors accessing the MQTT broker

:Created:
    2022-02-04

:Authors:
    | Michael Strey <strey@sarad.de>

"""
import os
import socket
import ssl
import time
from datetime import datetime, timedelta
from threading import Thread

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import Frontend
from registrationserver.base_actor import BaseActor
from registrationserver.config import (frontend_config, mqtt_config,
                                       mqtt_frontend_config)
from registrationserver.logger import logger
from registrationserver.shutdown import is_flag_set, system_shutdown


class MqttBaseActor(BaseActor):
    # pylint: disable=too-many-instance-attributes
    """Actor interacting with a new device"""

    @overrides
    def __init__(self):
        super().__init__()
        self.mqttc = None
        self.ungr_disconn = 2
        self.is_connected = False
        self.msg_id = {
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }  # store the current message ID to check
        self._subscriptions = {}
        self.group = None
        self.connect_thread = Thread(
            target=self._connect,
            daemon=True,
        )
        self.next_method = None
        self.qos = mqtt_config["QOS"]
        self.last_pingresp = datetime.now()

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if self.ungr_disconn == 2:
            logger.debug("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn in (1, 0):
            self.ungr_disconn = 2
            logger.debug("Already disconnected")
        logger.debug("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.info("%s: Client loop stopped", self.my_id)
        super()._kill_myself(register=register, resurrect=resurrect)

    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for PrepareMqttActorMsg from MQTT Listener"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.mqttc = MQTT.Client(client_id=msg.client_id, clean_session=False)
        self.group = msg.group
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        self.mqttc.on_log = self.on_log

    def receiveMsg_MqttConnectMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Connect the MQTT client"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.wakeupAfter(timedelta(seconds=0.5), payload="connect")
        self.connect_thread.start()
        self.wakeupAfter(timedelta(seconds=50), payload="watchdog")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        logger.debug("Wakeup %s, payload = %s", self.my_id, msg.payload)
        if msg.payload == "connect":
            if self.next_method is None:
                self.wakeupAfter(timedelta(seconds=0.5), payload=msg.payload)
            else:
                self.next_method()
                self.next_method = None
        if msg.payload == "watchdog":
            if mqtt_frontend_config["REBOOT_AFTER"]:
                if (datetime.now() - self.last_pingresp) > (
                    timedelta(minutes=mqtt_frontend_config["REBOOT_AFTER"])
                ):
                    logger.critical(
                        "%s: No PINGRESP. MQTT client or MQTT broker stopped working."
                        + "Reboot!",
                        self.my_id,
                    )
                    if mqtt_frontend_config["RESTART_INSTEAD_OF_REBOOT"]:
                        system_shutdown()
                    else:
                        os.system("reboot")
            self.wakeupAfter(timedelta(seconds=50), payload="watchdog")

    def _connect(self):
        """Try to connect the MQTT broker

        Retry forever with RETRY_INTERVAL,
        if there is a chance that the connection can be established.
        Give up, if TLS files are not available.
        """
        retry_interval = mqtt_config["RETRY_INTERVAL"]
        while self.ungr_disconn > 0 and is_flag_set()[0]:
            mqtt_broker = mqtt_config["MQTT_BROKER"]
            port = mqtt_config["PORT"]
            try:
                logger.debug(
                    "%s attempting to connect to broker %s: %s",
                    self.my_id,
                    mqtt_broker,
                    port,
                )
                if mqtt_config["TLS_USE_TLS"] and self.mqttc._ssl_context is None:
                    ca_certs = os.path.expanduser(mqtt_config["TLS_CA_FILE"])
                    certfile = os.path.expanduser(mqtt_config["TLS_CERT_FILE"])
                    keyfile = os.path.expanduser(mqtt_config["TLS_KEY_FILE"])
                    logger.debug(
                        "%s setting up TLS: %s | %s | %s",
                        self.my_id,
                        ca_certs,
                        certfile,
                        keyfile,
                    )
                    self.mqttc.tls_set(
                        ca_certs=ca_certs,
                        certfile=certfile,
                        keyfile=keyfile,
                        cert_reqs=ssl.CERT_REQUIRED,
                    )
                self.mqttc.connect(
                    mqtt_broker, port=port, keepalive=mqtt_config["KEEPALIVE"]
                )
                self.next_method = self._connected
                return
            except FileNotFoundError:
                logger.critical(
                    "%s cannot find files expected in %s, %s, %s",
                    self.my_id,
                    mqtt_config["TLS_CA_FILE"],
                    mqtt_config["TLS_CERT_FILE"],
                    mqtt_config["TLS_KEY_FILE"],
                )
                if Frontend.MQTT in frontend_config:
                    logger.critical(
                        "%s cannot live without MQTT broker. -> Emergency shutdown",
                        self.my_id,
                    )
                    system_shutdown()
                else:
                    logger.warning("%s proceeding without MQTT.", self.my_id)
                    self.next_method = self._kill_myself
                self.is_connected = False
                return
            except socket.gaierror as exception:
                logger.error(
                    "%s is offline and can handle only local instruments.",
                    self.my_id,
                )
                logger.info(
                    "Check your network connection and IP address in config_<os>.toml!"
                )
                connect_exception = exception
            except OSError as exception:  # pylint: disable=broad-except
                logger.error(
                    "%s on %s. Check port in config_<os>.toml!", exception, self.my_id
                )
                connect_exception = exception
            if is_flag_set()[0]:
                logger.error(
                    "%s will be retrying after %d seconds: %s",
                    self.my_id,
                    retry_interval,
                    connect_exception,
                )
                time.sleep(retry_interval)
            else:
                logger.info("%s giving up on connecting to MQTT broker.", self.my_id)

    def _connected(self):
        """Do everything that can only be done if the MQTT client is connected."""
        self.mqttc.loop_start()

    def on_connect(self, client, userdata, flags, reason_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT broker."""
        if reason_code:
            self.is_connected = False
            logger.critical(
                "Connection of %s to MQTT broker failed with %s",
                self.my_id,
                reason_code,
            )
            return
        self.is_connected = True
        for topic, qos in self._subscriptions.items():
            logger.debug("Restore subscription to %s", topic)
            self.mqttc.subscribe(topic, qos)
        logger.info("%s connected to MQTT broker", self.my_id)

    def on_disconnect(self, client, userdata, reason_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client disconnected from the MQTT broker."""
        logger.info("%s disconnected from MQTT broker", self.my_id)
        if reason_code >= 1:
            self.ungr_disconn = 1
            logger.warning(
                "%s ungracefully disconnected from MQTT broker (%s). Trying to reconnect.",
                self.my_id,
                reason_code,
            )
            # There is no need to do anything.
            # With loop_start() in place, re-connections will be handled automatically.
        else:
            self.ungr_disconn = 0
            logger.debug("Gracefully disconnected from MQTT broker.")
        self.is_connected = False

    def on_subscribe(self, client, userdata, msg_id, grant_qos):
        # pylint: disable=unused-argument
        """MQTT handler for confirmation of subscription."""
        logger.debug(
            "[on_subscribe] msg_id: %d, stored msg_id: %d",
            msg_id,
            self.msg_id["SUBSCRIBE"],
        )
        if msg_id == self.msg_id["SUBSCRIBE"]:
            logger.debug("Subscribed to the topic successfully")

    def on_unsubscribe(self, client, userdata, msg_id):
        # pylint: disable=unused-argument
        """MQTT handler for confirmation of unsubscribe."""
        logger.debug(
            "[on_unsubscribe] msg_id: %d, stored msg_id: %d",
            msg_id,
            self.msg_id["UNSUBSCRIBE"],
        )
        if msg_id == self.msg_id["UNSUBSCRIBE"]:
            logger.debug("Unsubscribed from topic")

    def on_message(self, _client, _userdata, message):
        """Handler for all MQTT messages that cannot be handled by special handlers."""
        logger.debug("message received: %s", message.payload)
        logger.debug("message topic: %s", message.topic)
        logger.debug("message qos: %s", message.qos)
        logger.debug("message retain flag: %s", message.retain)
        if message.payload is None:
            logger.warning("%s: The payload is none", self.my_id)
        else:
            logger.warning("%s: Unknown MQTT message", self.my_id)

    def on_log(self, _client, _userdata, level, buf):
        """Handler for MQTT logging information."""
        if level in [
            MQTT.MQTT_LOG_INFO,
            MQTT.MQTT_LOG_NOTICE,
            MQTT.MQTT_LOG_DEBUG,
        ]:
            logger.debug("%s: %s", self.my_id, buf)
        if level in [MQTT.MQTT_LOG_WARNING]:
            logger.warning("%s: %s", self.my_id, buf)
        if level in [MQTT.MQTT_LOG_ERR]:
            logger.error("%s: %s", self.my_id, buf)
        if "Received PINGRES" in buf:
            self.last_pingresp = datetime.now()

    def _publish(self, msg) -> bool:
        if not self.is_connected:
            logger.warning(
                "%s failed to publish the message because of disconnection", self.my_id
            )
            return False
        mqtt_topic = msg["topic"]
        mqtt_payload = msg["payload"]
        mqtt_qos = msg["qos"]
        retain = msg.get("retain", False)
        logger.debug("Publish %s to %s", mqtt_payload, mqtt_topic)
        return_code, self.msg_id["PUBLISH"] = self.mqttc.publish(
            mqtt_topic,
            payload=mqtt_payload,
            qos=mqtt_qos,
            retain=retain,
        )
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning(
                "%s: Publish failed; result code is: %s", self.my_id, return_code
            )
            return False
        return True

    def _subscribe_topic(self, sub_info: list) -> bool:
        """Subscribe to all topics listed in sub_info

        Args:
            sub_info (List[Tuple[str, int]]): List of tupels of (topic, qos)
            to subscribe to

        Returns:
            bool: True if subscription was successful

        """
        logger.debug("Work state: subscribe")
        if not self.is_connected:
            logger.error("%s: Subscribe failed, not connected to broker", self.my_id)
            return False
        return_code, self.msg_id["SUBSCRIBE"] = self.mqttc.subscribe(sub_info)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.error(
                "%s: Subscribe failed; result code is: %s", self.my_id, return_code
            )
            return False
        logger.debug("%s: Subscribe to %s successful", self.my_id, sub_info)
        for topic, qos in sub_info:
            self._subscriptions[topic] = qos
        return True

    def _unsubscribe_topic(self, topics: list) -> bool:
        logger.debug("Unsubscribe topics %s", topics)
        if not self.is_connected:
            logger.error("%s: Unsubscribe failed, not connected to broker", self.my_id)
            return False
        return_code, self.msg_id["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topics)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning(
                "Unsubscribing %s failed; result code is: %s", self.my_id, return_code
            )
            return False
        logger.debug("Unsubscribing %s from %s successful", self.my_id, topics)
        for topic in topics:
            logger.debug("Pop %s from %s", topic, self._subscriptions)
            try:
                self._subscriptions.pop(topic)
            except KeyError:
                logger.warning(
                    "%s: %s not in list of subscribed topics", self.my_id, topic
                )
        return True
