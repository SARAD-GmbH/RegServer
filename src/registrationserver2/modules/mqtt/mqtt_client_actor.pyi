from typing import Any

from appdirs import AppDirs as AppDirs
from registrationserver2 import actor_system as actor_system
from registrationserver2 import theLogger as theLogger
from registrationserver2.modules.mqtt import MQTT_ACTOR_ADRs as MQTT_ACTOR_ADRs
from registrationserver2.modules.mqtt import \
    MQTT_CLIENT_RESULTs as MQTT_CLIENT_RESULTs
from registrationserver2.modules.mqtt.message import \
    RETURN_MESSAGES as RETURN_MESSAGES
from registrationserver2.modules.mqtt.mqtt_subscriber import \
    SARAD_MQTT_SUBSCRIBER as SARAD_MQTT_SUBSCRIBER
from thespian.actors import Actor
from thespian.actors import ActorAddress as ActorAddress
from thespian.actors import ActorExitRequest as ActorExitRequest


class SaradMqttClient(Actor):
    ACCEPTED_COMMANDS: Any = ...
    mqtt_topic: str
    mqtt_payload: str
    mqtt_qos: int = ...
    mqtt_broker: str
    mqtt_cid: str
    rc_conn: Any = ...
    def on_connect(
        self, client: Any, userdata: Any, flags: Any, result_code: Any
    ) -> None: ...
    rc_disc: Any = ...
    def on_disconnect(self, client: Any, userdata: Any, result_code: Any) -> None: ...
    rc_pub: int = ...
    def on_publish(self, client: Any, userdata: Any, mid: Any) -> None: ...
    rc_sub: int = ...
    def on_subscribe(
        self, client: Any, userdata: Any, mid: Any, grant_qos: Any
    ) -> None: ...
    rc_uns: int = ...
    def on_unsubscribe(self, client: Any, userdata: Any, mid: Any) -> None: ...
    topic_parts: Any = ...
    len: Any = ...
    def on_message(self, client: Any, userdata: Any, message: Any) -> None: ...
    def receiveMessage(self, msg: Any, sender: Any) -> None: ...
    mqttc: Any = ...
    wait_cnt: int = ...
    def _connect(self, msg: dict) -> dict: ...
    def _disconnect(self, msg: dict) -> dict: ...
    def _kill(self, msg: Any) -> None: ...
    def _publish(self, msg: dict) -> dict: ...
    def _subscribe(self, msg: dict) -> dict: ...
    def _unsubscribe(self, msg: dict) -> dict: ...
    def signal_handler(self, sig: Any, frame: Any) -> None: ...
    def __init__(self) -> None: ...

SARAD_MQTT_CLIENT: ActorAddress