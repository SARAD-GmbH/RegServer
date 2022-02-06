"""Stub file for type checking with Mypy"""
from registrationserver.modules.mqtt.mqtt_base_actor import MqttBaseActor


class MqttListener(MqttBaseActor):
    def __init__(self) -> None: ...
