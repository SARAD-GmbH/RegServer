'''
Created on 16.02.2021

@author: Yixiang
'''
import socket
import yaml
import os
from appdirs import AppDirs  # type: ignore
import signal
import sys

import queue
import json

import traceback
import time
import logging

import paho.mqtt.client  # type: ignore
import thespian

from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2 import theLogger

from registrationserver2.modules.device_base_actor import RETURN_MESSAGES
# from curses.textpad import str
from _testmultiphase import Str, str_const
# from pip._vendor.urllib3.contrib._securetransport.low_level import _is_identity
#logger = logging.getLogger()
logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')


class MqttActor(DeviceBaseActor):
    '''
    classdocs:
    Actor interacting with a new device
    '''
    #mqtt = paho.mqtt.client

    #mqttc = mqtt.Client()

    config: dict = {}

    mqtt_ctrl: str

    mqtt_topic: str

    mqtt_payload: str

    mqtt_qos = 0

    mqtt_broker: str  # MQTT Broker, here: localhost

    mqtt_cid: str  # MQTT Client ID

    mqtt_msg_rx = queue.Queue(
        4
    )  #define a FIFO-queue (size is 4) for storing received messages, used as a buffer
    '''count_rx = 0 # count of received messages, maximal equal to 3

    msg_head = 0 # head index of the list mqtt_msg_rx, increasing when receiving a new message, maximal equal to 3

    msg_tail = 0 # tail index of the list mqtt_msg_rx, maximal equal to 3
    '''
    topic_buf_rx: str

    py_buf_rx: str

    def on_connect(self, client, userdata, flags, result_code):  # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        self.result_code = result_code
        if self.result_code:
            theLogger.info(
                'Connection to MQTT self.mqtt_broker failed. result_code=%s',
                result_code)
        else:
            theLogger.info('Connected with MQTT self.mqtt_broker.')
        #return self.result_code

    def on_disconnect(self, client, userdata, result_code):  # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        self.result_code = result_code
        if self.result_code:
            theLogger.info(
                'Disconnection from MQTT-broker failed. result_code=%s',
                result_code)
        else:
            theLogger.info('Gracefully disconnected from MQTT-broker.')

    def sarad_prot_check(self, instr_reply):
        pass

    def msg_analyzer(self, msg_rx: str):
        # msg_rx is the mseesage received via MQTT
        self.topic_buf_rx = str(msg_rx.topic.decode("utf-8"))
        self.pl_buf_rx = str(msg_rx.payload.decode("utf-8"))
        if self.topic_buf_rx:
            if self.topic_buf_rx == self.sys_topic[
                    2]:  # meta data check, including reservation status
                if self.link_request == 1:
                    self.link_reply = 1
                    if self.pl_buf_rx:
                        self.link_accept = self.pl_buf_rx
                    else:
                        theLogger.info(
                            'Illegal reply \'None\' of reservation request!\n')
                        self.link_accept = 4
                else:
                    pass
            elif self.topic_buf_rx == self.sys_topic[3]:  # msg check
                pass
            else:
                theLogger.info('Illegal message under the topic ' +
                               self.topic_buf_rx + '!\n')

    def on_message(self, client, userdata, message):
        time.sleep(1)
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
        if not self.mqtt_msg_rx.full():
            print('recieved message = %s',
                  str(message.payload.decode("utf-8")))
            self.mqtt_msg_rx.put(message)

    def mqtt_connect(self):
        theLogger.info('To connect to the MQTT-broker!\n')
        self.mqttc.connect(self.mqtt_broker)

    def mqtt_disconnect(self):
        theLogger.info('To disconnect from the MQTT-broker!\n')
        self.mqttc.disconnect()
        theLogger.info('To stop the MQTT thread!\n')
        self.mqttc.loop_stop()

    def mqtt_publish(self):
        theLogger.info(
            'To publish the message (%s) under the topic (%s) with QoS=%s!\n',
            self.mqtt_payload, self.mqtt_topic, self.qos)
        self.mqttc.publish(self.mqtt_topic, self.mqtt_payload, self.mqtt_qos)

    def mqtt_subscribe(self):
        theLogger.info('To subscribe the topic (%s)!\n', self.mqtt_topic)
        self.mqttc.subscribe(self.mqtt_topic, self.mqtt_qos)

    def mqtt_unsubscribe(self):
        theLogger.info('To unsubscribe the topic (%s)!\n', self.mqtt_topic)
        self.mqttc.unsubscribe(self.mqtt_topic)

    switcher = {
        'connect': mqtt_connect,
        'disconnect': mqtt_disconnect,
        'publish': mqtt_publish,
        'subsribe': mqtt_subscribe,
        'unsubsribe': mqtt_unsubscribe
    }
    '''def mqtt_ctrl_switcher(self, ctrl):
        self.mqtt_ctrl = ctrl
        self.mqtt_func = self.switcher.get(self.mqtt_ctrl, None)
        return self.mqtt_func'''

    def mqtt_controller(self, ctrl, topic, pl, qos=None):
        if qos is None:
            qos = 0
        self.mqtt_ctrl = ctrl
        self.mqtt_topic = topic
        self.mqtt_payload = pl
        self.mqtt_qos = qos
        self.mqtt_func = self.switcher.get(self.mqtt_ctrl, None)
        self.mqtt_func()
        #self.mqtt_ctrl_switcher(ctrl)

    def link_check(self):
        while True:
            if self.link_request_cnt < 3:
                if self.link_reply:
                    self.link_reply = 0
                    if self.link_accept == 1:
                        self.link_accept = 0
                        self.link_request_cnt = 0
                        theLogger.info('Link accepted!\n')
                        return 1
                    elif self.link_accept == 2:
                        theLogger.info('The instrument with instrument ID ' +
                                       self.Instr_ID + ' is occupied!\n')
                        return 2
                    else:
                        self.link_request_cnt = 0
                        theLogger.info('Link refused!\n')
                        return 0
                else:
                    time.sleep(2)
                    self.link_request_cnt = self.link_request_cnt + 1
            else:
                self.link_request_cnt = 0
                self.link_request = 0
                theLogger.info('No reply for the link request\n')
                return 0

    def __send__(self, msg: dict):
        pass

    def __reserve__(self, msg):
        theLogger.info('Reserve-Request\n' + msg)
        #self.mqtt_controller('publish', self.sys_topic[1], json.dump(msg), 0)
        self.mqttc.publish(self.sys_topic[1], json.dump(msg))
        self.link_request = 1
        '''self.timeout1 = 10
        while True:
            time.sleep(1)
            if not self.mqtt_msg_rx.empty(): # if the msg_rx is not empty
                self.msg_analyzer(self.msg_rx.get())
            self.timeout1 = self.timeout1 - 1
        '''

    def __free__(self, msg):
        pass

    def __kill__(self, msg: dict):
        super().__kill__(msg)

    def pre_work(self):
        theLogger.info('Now, this actor would do some prepare work')
        for i in range(2, 4):
            theLogger.info('To subsribe this topic: %s\n', self.sys_topic[i])
            self.mqttc.subscribe(self.sys_topic[i])
            time.sleep(2)
        theLogger.info('The prepare work is done!')

    # * Handling of Ctrl+C:
    def signal_handler(self, sig, frame):  # pylint: disable=unused-argument
        """On Ctrl+C:
        - stop all cycles
        - disconnect from MQTT self.mqtt_broker"""
        theLogger.info('You pressed Ctrl+C!\n')
        self.mqttc.disconnect()
        self.mqttc.loop_stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,
                  signal_handler)  # SIGINT: By default, interrupt is Ctrl+C

    def __init__(self, is_id=str, instr_id=str, mqtt_actor_id=str):
        '''
        Constructor
        Description of parameters:
          is_id : Instrument Server ID, namely the MQTT client ID of the Instrument Server.
          intr_id : ID of the SARAD Instrument to communicate with
          mqtt_actor_id : ID of this MQTT Actor, namely its MQTT client ID
        '''
        #MqttActor._config()
        # * Configuration file:
        '''config = {
             'mqtt'   : {'self.mqtt_broker' : 'localhost', 'client_id' : 'ap-strey'}
            ,'zabbix' : {'server' : 'localhost', 'host': 'ap-strey'}
            #,'cycles' : {'28tkhn4V' : '5'}
                  }
        '''
        super.__init__()

        self.reserve_req_msg = {
            "Req": "reserve",
            "App": "RadonVision",
            "Host": "WS02",
            "User": "mstrey"
        }

        self.free_req_msg = {"Req": "free"}
        '''try:
            self.mqtt_cid = self.config['mqtt']['client_id']
        except KeyError:
            self.mqtt_cid = socket.gethostname()'''

        self.mqtt_cid = mqtt_actor_id

        self.mqtt = paho.mqtt.client

        self.mqttc = self.mqtt.Client(self.mqtt_cid)

        self.mqttc.reinitialise()
        # The reinitialise() function resets the client to its starting state
        # as if it had just been created. It takes the same arguments as the Client() constructor.

        self.link_request = 0

        self.link_request_cnt = 0

        self.link_reply = 0

        self.link_accept = 0

        self.IS_ID = is_id

        self.Instr_ID = instr_id

        self.sys_topic = {  #system topics for communicating with the instrument
            0: self.IS_ID + '/' + self.Instr_ID + '/cmd',
            1: self.IS_ID + '/' + self.Instr_ID + '/control',
            2: self.IS_ID + '/' + self.Instr_ID + '/meta',
            3: self.IS_ID + '/' + self.Instr_ID + '/msg'
        }
        dirs = AppDirs("mqtt")
        for loc in [
                os.curdir,
                os.path.expanduser("~"), dirs.user_config_dir,
                dirs.site_config_dir
        ]:
            try:
                with open(os.path.join(loc, "mqtt.conf"), "r") as ymlfile:
                    config = yaml.safe_load(ymlfile)
            except IOError:
                pass

        if config == {}:
            theLogger.debug(
                "There seems to be no configuration file. Using defaults.\n")

        # ** MQTT config:
        try:
            self.mqtt_broker = self.config['mqtt']['mqtt_broker']
        except KeyError:
            self.mqtt_broker = 'localhost'

        theLogger.info('The MQTT Client ID of this MQTT Actor is %s.\n',
                       self.mqtt_cid)

        # Bind functions to callback functions
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message

        self.mqttc.connect(self.mqtt_broker)

        self.mqttc.loop_start()

        self.pre_work()  # do some prepare work
        '''while True:
            if not self.mqtt_msg_rx.empty():
                self.msg_analyzer(self.mqtt_msg_rx)'''
