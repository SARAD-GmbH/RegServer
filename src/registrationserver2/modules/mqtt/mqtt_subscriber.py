'''
Created on 2021Äê2ÔÂ24ÈÕ

@author: Yixiang
'''

import os
import ipaddress
import socket
import json
import traceback
import threading
import logging

import hashids
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

import registrationserver2
from registrationserver2.config import config
from registrationserver2 import theLogger
from registrationserver2.modules.rfc2217.rfc2217_actor import Rfc2217Actor

from registrationserver2.modules.device_base_actor import RETURN_MESSAGES

logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')


class SaradMqttSubscriber(object):
    '''
    classdocs
    '''


    def __init__(self, params):
        '''
        Constructor
        '''
        