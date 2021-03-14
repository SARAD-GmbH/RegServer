'''
Created on 2021-03-10

@author: Yixiang
'''

import os
import ipaddress
import socket
import json
import traceback
import threading
import logging

import paho.mqtt.client as mqtt# type: ignore
from thespian.actors import Actor, ActorExitRequest, ActorAddress
import thespian

from registrationserver2 import theLogger
import registrationserver2
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
from registrationserver2 import actor_system

from registrationserver2.modules.mqtt import MQTT_ACTOR_ADRs

logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')


class SaradMqttSubscriber(Actor):
    '''
    classdocs
    '''
    def __init__(self, params):
        '''
        Constructor
        '''

SARAD_MQTT_SUBSCRIBER : ActorAddress =  actor_system.createActor(SaradMqttSubscriber,type(SaradMqttSubscriber).__name__)