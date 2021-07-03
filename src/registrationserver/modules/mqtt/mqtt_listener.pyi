"""Stub file for type checking with Mypy"""
from thespian.actors import Actor, ActorAddress  # type: ignore


class SaradMqttSubscriber(Actor):
    def __init__(self) -> None: ...

SARAD_MQTT_SUBSCRIBER: ActorAddress
