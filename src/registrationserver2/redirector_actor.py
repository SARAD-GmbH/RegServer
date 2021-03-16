"""
Created on 01.12.2020

@author: rfoerster
"""
import socket
import traceback
import logging

from dataclasses import dataclass

from thespian.actors import Actor
from registrationserver2.modules import device_base_actor
from registrationserver2 import actor_system
from registrationserver2.modules.device_actor_manager import DEVICE_ACTOR_MANAGER
from registrationserver2 import theLogger

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


@dataclass
class SockInfo:
    """Refer to SocketClient"""

    address: str
    port: int


@dataclass
class SocketClient:
    """Example: SocketClient(client_socket=<socket.socket fd=3708,
    family=AddressFamily.AF_INET, type=SocketKind.SOCK_STREAM, proto=0,
    laddr=('127.0.0.1', 55224), raddr=('127.0.0.1', 56066)>,
    client_address=SockInfo(address='127.0.0.1', port=56066))"""

    client_socket: socket
    client_address: SockInfo


class RedirectorActor(Actor):
    """Creating port for listening to Packages from a SARAD© Application"""

    _sock: socket
    _sockclient: SockInfo
    _device: device_base_actor

    ILLEGAL_STATE = {
        "ERROR": "Actor not setup correctly, make sure to send SETUP message first",
        "ERROR_CODE": 5,
    }  # The actor was in a wrong state
    ILLEGAL_WRONGTYPE = {
        "ERROR": "Wrong message type, dictionary expected",
        "ERROR_CODE": 3,
    }  # The message received by the actor was not of expected type
    ILLEGAL_WRONGFORMAT = {
        "ERROR": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    }  # The message received by the actor did not match the expected format.

    LOOP = {"CMD": "LOOP"}

    def receive(self):
        """Listen to Port and redirect any messages"""
        client_socket: socket
        try:
            client_socket, socket_info = self._sock.accept()
            while True:
                data = client_socket.recv(9002)
                theLogger.info(f"{data} from {socket_info}")
                if not data:
                    break
                remote = actor_system.ask(
                    DEVICE_ACTOR_MANAGER, {"CMD": "GET", "NAME": ""}
                )
                actor_system.ask(remote, {"CMD": "SEND", "DATA": data})
        except BaseException as error:  # pylint: disable=W0703
            theLogger.error(
                f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
            )
            client_socket = None
            return
        self._sockclient = SocketClient(
            client_socket[0], SockInfo(client_socket[1][0], client_socket[1][1])
        )
        # get data here
        # awr = self.ask(self._device, {'CMD':'SEND', 'DATA':data})

        client_socket.close()

    def receiveMessage(self, msg, sender):
        # pylint: disable=W0613,C0103 #@UnusedVariable
        """Actor receive message loop"""

        if sender == self.myAddress and msg is self.LOOP:
            self.receive()
            self.send(self.myAddress, self.LOOP)
            return

        if not isinstance(msg, dict):
            self.send(sender, self.ILLEGAL_WRONGTYPE)
            return

        cmd_string = msg.get("CMD", None)

        if not cmd_string:
            self.send(sender, self.ILLEGAL_WRONGFORMAT)
            return

        if cmd_string == "SETUP":
            self._device = msg.get("DEVICE", None)
            if not self._device:
                self.send(sender, self.ILLEGAL_STATE)
            if not self._sock:  # create socket
                _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                _sock.bind(("", 0))  # listen to any address on any available port
                _sock.listen()
                _sock.settimeout(0.5)
            if not self._sock:
                self.send(sender, self.ILLEGAL_STATE)

            # send back the actual used port
            self.send(sender, {"DATA": self._sock.getsockname()})
