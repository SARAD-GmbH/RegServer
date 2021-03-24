from registrationserver2 import actor_system as actor_system, theLogger as theLogger
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES as RETURN_MESSAGES
from thespian.actors import Actor, ActorAddress as ActorAddress, ActorExitRequest as ActorExitRequest

class SaradMqttSubscriber(Actor):
    def __init__(self) -> None: ...

SARAD_MQTT_SUBSCRIBER: ActorAddress
