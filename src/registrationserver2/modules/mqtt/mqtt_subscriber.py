"""
Created on 2021-03-10

@author: Yixiang
"""

import ipaddress
import json
import logging
import os
import socket
import threading
import traceback

import paho.mqtt.client as mqtt  # type: ignore
import registrationserver2
import thespian
from registrationserver2 import actor_system, theLogger
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
from thespian.actors import Actor, ActorAddress, ActorExitRequest

# from registrationserver2.modules.mqtt import MQTT_ACTOR_ADRs

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


class SaradMqttSubscriber(Actor):
    """
    classdocs
    """

    def __init__(self):
        """
        Constructor
        """


# [???] Causing runtime errors -- MS, 2021-03-16
SARAD_MQTT_SUBSCRIBER: ActorAddress = actor_system.createActor(
    SaradMqttSubscriber, type(SaradMqttSubscriber).__name__
)
