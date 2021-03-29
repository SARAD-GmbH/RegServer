"""Creates a listening server socket and forwards pakets received over this
socket as actor messages to the device actor.


Created
    2020-12-01

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml :: uml-redirector_actor.puml

"""
import socket
import traceback
from dataclasses import dataclass

import thespian.actors  # type: ignore
from thespian.actors import Actor  # type: ignore

from registrationserver2 import actor_system, theLogger
from registrationserver2.modules.messages import RETURN_MESSAGES

theLogger.info("%s -> %s", __package__, __file__)


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

    # client_socket: socket
    # client_address: SockInfo


class RedirectorActor(Actor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    ACCEPTED_COMMANDS = {
        "SETUP": "_setup",
        "KILL": "_kill",
    }
    LOOP = {"CMD": "LOOP"}

    HOST = "127.0.0.1"  # Standard loopback interface address (localhost)
    PORT = 50000  # Port to listen on (non-privileged ports are > 1023)

    def __init__(self):
        super().__init__()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind((self.HOST, self.PORT))
        self._socket.listen()
        self.my_parent = None
        theLogger.info("Socket listening on port %d", self.PORT)

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return

        if not isinstance(msg, dict):
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGTYPE"])
            return
        cmd_key = msg.get("CMD", None)
        if cmd_key is None:
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"])
            return
        cmd = self.ACCEPTED_COMMANDS.get(cmd_key, None)
        if cmd is None:
            self.send(sender, RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"])
            return
        if getattr(self, cmd, None) is None:
            self.send(sender, RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"])
            return
        self.send(sender, getattr(self, cmd)(msg))

    def _setup(self, msg):
        if self.my_parent is None:
            parent_name = msg["PAR"]["PARENT_NAME"]
            self.my_parent = self.createActor(Actor, globalName=parent_name)
            return RETURN_MESSAGES["OK"]
        return RETURN_MESSAGES["OK_SKIPPED"]

    def receive(self):
        """Listen to Port and redirect any messages"""
        client_socket: socket
        try:
            client_socket, socket_info = self._socket.accept()
            while True:
                data = client_socket.recv(9002)
                theLogger.info("%s from %s", data, socket_info)
                if not data:
                    break
                actor_system.ask(self.my_parent, {"CMD": "SEND", "DATA": data})
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "[Send data]:\t%s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
            client_socket = None
            return
        self._sockclient = SocketClient(
            client_socket[0], SockInfo(client_socket[1][0], client_socket[1][1])
        )
        # get data here
        # awr = self.ask(self._device, {'CMD':'SEND', 'DATA':data})
        client_socket.close()

    # def receiveMessage(self, msg, sender):
    #     # pylint: disable=W0613,C0103 #@UnusedVariable
    #     """Actor receive message loop"""

    #     if sender == self.myAddress and msg is self.LOOP:
    #         self.receive()
    #         self.send(self.myAddress, self.LOOP)
    #         return

    #     if not isinstance(msg, dict):
    #         self.send(sender, self.ILLEGAL_WRONGTYPE)
    #         return

    #     cmd_string = msg.get("CMD", None)

    #     if not cmd_string:
    #         self.send(sender, self.ILLEGAL_WRONGFORMAT)
    #         return

    #     if cmd_string == "SETUP":
    #         self._device = msg.get("DEVICE", None)
    #         if not self._device:
    #             self.send(sender, self.ILLEGAL_STATE)
    #         if not self._sock:  # create socket
    #             _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #             _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #             _sock.bind(("", 0))  # listen to any address on any available port
    #             _sock.listen()
    #             _sock.settimeout(0.5)
    #         if not self._sock:
    #             self.send(sender, self.ILLEGAL_STATE)

    #         # send back the actual used port
    #         self.send(sender, {"DATA": self._sock.getsockname()})
