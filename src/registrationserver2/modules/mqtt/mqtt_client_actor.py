import socket
import yaml
import os
from appdirs import AppDirs     # type: ignore
import signal
import sys

import queue
import json

import time
import logging

import paho.mqtt.client as mqtt# type: ignore
from thespian.actors import Actor, ActorExitRequest, ActorAddress
import thespian

from registrationserver2 import theLogger
import registrationserver2
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
from registrationserver2 import actor_system

#logger = logging.getLogger()
logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')

class SaradMqttClient(Actor):
    
    ACCEPTED_MESSAGES = {
            "KILL"        :        "__kill__",
            "CONNECT"     :     "__connect__",
            "PUBLISH"     :     "__publish__",
            "SUBSCRIBE"   :   "__subscribe__",
            "DISCONNECT"  :  "__disconnect__",
            "UNSUBSCRIBE" : "__unsubscribe__",
    }
    
    config : dict = {}   
    
    mqtt_ctrl : str
    
    mqtt_topic : str
    
    mqtt_payload : str
    
    mqtt_qos = 0 
    
    mqtt_broker : str # MQTT Broker, here: localhost
    
    mqtt_cid : str # MQTT Client ID
    
    mqtt_msg_rx = queue.Queue(4)      #define a FIFO-queue (size is 4) for storing received messages, used as a buffer
    
    '''count_rx = 0 # count of received messages, maximal equal to 3
    
    msg_head = 0 # head index of the list mqtt_msg_rx, increasing when receiving a new message, maximal equal to 3
    
    msg_tail = 0 # tail index of the list mqtt_msg_rx, maximal equal to 3
    '''
    topic_buf_rx : str 
    
    py_buf_rx : str
    
    def on_connect(self, client, userdata, flags, result_code): # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        self.rc_conn = result_code
        if self.rc_conn == 1:
            theLogger.info('Connection to MQTT self.mqtt_broker failed. result_code=%s', result_code)
        else:
            theLogger.info('Connected with MQTT self.mqtt_broker.')
        #return self.result_code

    def on_disconnect(self, client, userdata, result_code): # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        self.rc_disc = result_code
        if self.rc_disc == 1:
            theLogger.info('Disconnection from MQTT-broker failed. result_code=%s', result_code)
        else:
            theLogger.info('Gracefully disconnected from MQTT-broker.')
    
    def on_publish(self, client, userdata, mid):
        self.rc_pub = 0
        theLogger.info('The message with Message-ID %d is published to the broker!\n', mid)
    
    def on_subscribe(self, client, userdata, mid, grant_qos):
        self.rc_sub = 0
        theLogger.info('Subscribed to the topic successfully!\n')
    
    def on_unsubscribe(self, client, userdata, mid):
        self.rc_uns = 0
        theLogger.info('Unsubscribed to the topic successfully!\n')
    
    def on_message(self, client, userdata, message):
        self.topic_parts = []
        
        self.topic_parts = message.split('/')
        
        self.len = len(self.topic_parts)
        
        if self.len == 2:
            self.send()
        else:
            pass
        '''if self.count_rx < 3:
            if self.msg_head < 3:
                print('recieved message = %s with the index = %d', str(message.payload.decode("utf-8")), self.msg_head)
                self.mqtt_msg_rx[self.msg_head] = message
                self.msg_head = self.msg_head + 1
            else:
                self.msg_head = 0           
            self.count_rx = self.count_rx + 1
        #if self.count_rx == 3:
        '''
            
    
    def receiveMessage(self, msg, sender):
        
        '''
            Handles received Actor messages / verification of the message format
        '''
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return

        if not isinstance(msg,dict):
            self.send(sender, RETURN_MESSAGES.get('ILLEGAL_WRONGTYPE'))
            return

        cmd_string= msg.get("CMD", None)

        if not cmd_string:
            self.send(sender, RETURN_MESSAGES.get('ILLEGAL_WRONGFORMAT'))
            return

        cmd = self.ACCEPTED_MESSAGES.get(cmd_string,None)

        if not cmd:
            self.send(sender, RETURN_MESSAGES.get('ILLEGAL_UNKNOWN_COMMAND'))
            return

        if not getattr(self,cmd,None):
            self.send(sender, RETURN_MESSAGES.get('ILLEGAL_NOTIMPLEMENTED'))
            return

        self.send(sender,getattr(self,cmd)(msg))
        
    def __connect__(self, msg:dict)->dict:
        self.mqtt_cid = msg.get('client_id', None)
        
        if self.mqtt_cid is None:
            return RETURN_MESSAGES.get('ILLEGAL_STATE')
        
        self.mqtt_broker = msg.get('mqtt_broker', None)
        
        if self.mqtt_broker is None:
            return RETURN_MESSAGES.get('ILLEGAL_STATE')
    
        self.mqttc = self.mqtt.Client(self.mqtt_cid)
        
        self.mqttc.reinitialise() 
        
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        
        self.mqttc.connect(self.mqtt_broker)
        
        self.wait_cnt = 3
        
        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_conn == 0:
                self.rc_conn = 2
                break
            elif self.rc_conn == 1:
                self.rc_conn = 2
                return RETURN_MESSAGES.get('CONNECTION_FAILURE')
            else:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1
        else:
            return RETURN_MESSAGES.get('CONNECTION_NO_RESPONSE')
        
        self.mqttc.loop_start()
        return RETURN_MESSAGES.get('OK_SKIPPED')
    
    def __disconnect__(self, msg:dict)->dict:
        theLogger.info('To disconnect from the MQTT-broker!\n')
        self.mqttc.disconnect()
        theLogger.info('To stop the MQTT thread!\n')
        self.mqttc.loop_stop()
        return RETURN_MESSAGES.get('OK_SKIPPED')
    
    def __kill__(self, msg):
        registrationserver2.theLogger.info(f'Shutting down actor {self.globalName}, Message : {msg}')
        theLogger.info( registrationserver2.actor_system.ask(self.myAddress, thespian.actors.ActorExitRequest() ))
        self.__disconnect__()
        #TODO: clear the used memory 
    
    def __publish__(self, msg:dict)->dict:
        self.mqtt_topic = msg.get('topic', None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get('ILLEGAL_WRONGFORMAT')
        self.mqtt_payload = msg.get('payload', None)
        self.mqtt_qos = msg.get('qos', None)
        self.mqttc.publish(self.mqtt_topic, self.mqtt_payload, self.mqtt_qos)
        self.wait_cnt = 3
        
        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_pub == 1:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1   
            else:
                self.rc_pub = 1
                break
        else:
            return RETURN_MESSAGES.get('PUBLISH_FAILURE')
        
        self.mqttc.loop_start()
        return RETURN_MESSAGES.get('OK_SKIPPED')
    
    def __subscribe__(self, msg : dict)->dict:
        self.mqtt_topic = msg.get('topic', None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get('ILLEGAL_WRONGFORMAT')
        self.mqtt_qos = msg.get('qos', None)
        if self.mqtt_qos is None:
            self.mqtt_qos = 0
        self.mqttc.subscribe(self.mqtt_topic, self.mqtt_qos)
        self.wait_cnt = 3
        
        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_sub == 1:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1   
            else:
                self.rc_sub = 1
                break
        else:
            return RETURN_MESSAGES.get('SUBSCRIBE_FAILURE')
        
        self.mqttc.loop_start()
        return RETURN_MESSAGES.get('OK_SKIPPED')
    
    def __unsubscribe__(self, msg : dict)->dict:
        self.mqtt_topic = msg.get('topic', None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get('ILLEGAL_WRONGFORMAT')
        self.mqttc.unsubscribe(self.mqtt_topic)
        self.wait_cnt = 3
        
        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_uns == 1:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1   
            else:
                self.rc_uns = 1
                break
        else:
            return RETURN_MESSAGES.get('UNSUBSCRIBE_FAILURE')
        
        self.mqttc.loop_start()
        return RETURN_MESSAGES.get('OK_SKIPPED')
    
    def __init__(self):
        super().__init__()
        self.rc_conn = 2
        self.rc_disc = 2
        self.rc_pub = 1
        self.rc_sub = 1
        self.rc_uns = 1
        
SARAD_MQTT_CLEINT : ActorAddress =  actor_system.createActor(SaradMqttClient,type(SaradMqttClient).__name__)