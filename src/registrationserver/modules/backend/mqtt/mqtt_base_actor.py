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

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import Frontend
from registrationserver.base_actor import BaseActor
from registrationserver.config import frontend_config, mqtt_config
from registrationserver.logger import logger
from registrationserver.shutdown import is_flag_set, system_shutdown

# logger.debug("%s -> %s", __package__, __file__)


class MqttBaseActor(BaseActor):
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
        self.mqtt_broker = None
        self.port = None
        self.group = None

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        if self.ungr_disconn == 2:
            logger.debug("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn in (1, 0):
            self.ungr_disconn = 2
            logger.debug("Already disconnected")
        logger.debug("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.debug("Disconnected gracefully")
        super().receiveMsg_KillMsg(msg, sender)

    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for PrepareMqttActorMsg from MQTT Listener"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.mqtt_broker = mqtt_config["MQTT_BROKER"]
        self.port = mqtt_config["PORT"]
        self.mqttc = MQTT.Client(msg.client_id)
        self.group = msg.group
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe

    def _connect(self, mqtt_broker, port):
        """Try to connect the MQTT broker

        Retry forever with RETRY_INTERVAL,
        if there is a chance that the connection can be established.
        Give up, if TLS files are not available.
        """
        retry_interval = mqtt_config["RETRY_INTERVAL"]
        while self.ungr_disconn > 0 and is_flag_set()[0]:
            try:
                logger.info(
                    "Attempting to connect to broker %s: %s",
                    mqtt_broker,
                    port,
                )
                if mqtt_config["TLS_USE_TLS"] and self.mqttc._ssl_context is None:
                    ca_certs = os.path.expanduser(mqtt_config["TLS_CA_FILE"])
                    certfile = os.path.expanduser(mqtt_config["TLS_CERT_FILE"])
                    keyfile = os.path.expanduser(mqtt_config["TLS_KEY_FILE"])
                    logger.info(
                        "Setting up TLS: %s | %s | %s", ca_certs, certfile, keyfile
                    )
                    self.mqttc.tls_set(
                        ca_certs=ca_certs,
                        certfile=certfile,
                        keyfile=keyfile,
                        cert_reqs=ssl.CERT_REQUIRED,
                    )
                self.mqttc.connect(mqtt_broker, port=port)
                return True
            except FileNotFoundError:
                logger.critical(
                    "Cannot find files expected in %s, %s, %s",
                    mqtt_config["TLS_CA_FILE"],
                    mqtt_config["TLS_CERT_FILE"],
                    mqtt_config["TLS_KEY_FILE"],
                )
                if Frontend.MQTT in frontend_config:
                    logger.critical(
                        "I cannot live without MQTT broker. -> Emergency shutdown"
                    )
                    system_shutdown()
                else:
                    logger.warning("Proceed without MQTT.")
                return False
            except socket.gaierror as exception:
                logger.error("We are offline and can handle only local instruments.")
                logger.info(
                    "Check your network connection and IP address in config_<os>.toml!"
                )
                connect_exception = exception
            except OSError as exception:  # pylint: disable=broad-except
                logger.error("%s. Check port in config_<os>.toml!", exception)
                connect_exception = exception
            if is_flag_set()[0]:
                logger.error(
                    "I will be retrying after %d seconds: %s",
                    retry_interval,
                    connect_exception,
                )
                time.sleep(retry_interval)
            else:
                logger.info(
                    "Shutdown flag detected. Giving up on connecting to MQTT broker."
                )

    def on_connect(self, client, userdata, flags, result_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT broker."""
        if result_code:
            self.is_connected = False
            logger.critical(
                "[CONNECT] Connection to MQTT broker failed with %s",
                result_code,
            )
            return
        self.is_connected = True
        for topic, qos in self._subscriptions.items():
            logger.debug("Restore subscription to %s", topic)
            self.mqttc.subscribe(topic, qos)
        logger.info("[CONNECT] Connected to MQTT broker")

    def on_disconnect(self, client, userdata, result_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client disconnected from the MQTT broker."""
        logger.info("Disconnected from MQTT broker")
        if result_code >= 1:
            self.ungr_disconn = 1
            logger.warning(
                "Ungraceful disconnect from MQTT broker (%s). Trying to reconnect.",
                result_code,
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

    @staticmethod
    def on_message(_client, _userdata, message):
        """Handler for all MQTT messages that cannot be handled by special handlers."""
        logger.debug("message received: %s", message.payload)
        logger.debug("message topic: %s", message.topic)
        logger.debug("message qos: %s", message.qos)
        logger.debug("message retain flag: %s", message.retain)
        if message.payload is None:
            logger.warning("The payload is none")
        else:
            logger.warning("Unknown MQTT message")

    def _publish(self, msg) -> bool:
        if not self.is_connected:
            logger.warning("Failed to publish the message because of disconnection")
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
            logger.warning("Publish failed; result code is: %s", return_code)
            return False
        return True

    def _subscribe_topic(self, sub_info: list) -> bool:
        """Subscribe to all topics listed in sub_info

        Args:
            sub_info (List[Tupel[str, int]]): List of tupels of (topic, qos)
            to subscribe to

        Returns:
            bool: True if subscription was successful

        """
        logger.debug("Work state: subscribe")
        if not self.is_connected:
            logger.error("[Subscribe] failed, not connected to broker")
            return False
        return_code, self.msg_id["SUBSCRIBE"] = self.mqttc.subscribe(sub_info)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.error("Subscribe failed; result code is: %s", return_code)
            return False
        logger.info("[Subscribe] to %s successful", sub_info)
        for (topic, qos) in sub_info:
            self._subscriptions[topic] = qos
        return True

    def _unsubscribe_topic(self, topics: list) -> bool:
        logger.info("Unsubscribe topics %s", topics)
        if not self.is_connected:
            logger.error("[Unsubscribe] failed, not connected to broker")
            return False
        return_code, self.msg_id["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topics)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("[Unsubscribe] failed; result code is: %s", return_code)
            return False
        logger.info("[Unsubscribe] from %s successful", topics)
        for topic in topics:
            logger.debug("Pop %s from %s", topic, self._subscriptions)
            try:
                self._subscriptions.pop(topic)
            except KeyError:
                logger.warning("%s not in list of subscribed topics", topic)
        return True
