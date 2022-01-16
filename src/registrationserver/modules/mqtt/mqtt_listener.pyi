"""Stub file for type checking with Mypy"""
from registrationserver.base_actor import BaseActor
from thespian.actors import ActorAddress  # type: ignore


class SaradMqttSubscriber(BaseActor):
    def __init__(self) -> None: ...

SARAD_MQTT_SUBSCRIBER: ActorAddress
