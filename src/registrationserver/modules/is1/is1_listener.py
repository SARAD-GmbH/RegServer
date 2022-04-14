"""Listening for notifications from Instrument Server 1

:Created:
    2022-04-14

:Authors:
    | Michael Strey <strey@sarad.de>
"""
import datetime
import select
import socket

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (ActorCreatedMsg, CreateActorMsg,
                                               SetDeviceStatusMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.helpers import get_actor
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown

logger.debug("%s -> %s", __package__, __file__)


class Is1Listener(BaseActor):
    """Listens for messages from Instrument Server 1

    * adds new SARAD Instruments to the system by creating a device actor
    """

    @overrides
    def __init__(self):
        super().__init__()
        self.my_parent = None
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        self._host = config["HOST"]
        logger.debug("IP address of Registration Server: %s", self._host)
        for self._port in [50002]:
            try:
                server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                server_socket.bind((self._host, self._port))
                self._port = server_socket.getsockname()[1]
                break
            except OSError:
                try:
                    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    server_socket.bind((self._host, self._port))
                    self._port = server_socket.getsockname()[1]
                    break
                except OSError as exception:
                    logger.error("Cannot use port %d. %s", self._port, exception)
                    server_socket.close()
        try:
            server_socket.listen()  # listen(5) maybe???
        except OSError:
            self._port = None
        logger.debug("Server socket: %s", server_socket)
        self.read_list = [server_socket]
        if self._port is not None:
            logger.info("Socket listening on %s:%d", self._host, self._port)

    def listen(self):
        """Listen for notification from Instrument Server"""
        server_socket = self.read_list[0]
        timeout = 0.1
        readable, _writable, _errored = select.select(self.read_list, [], [], timeout)
        for self.conn in readable:
            if self.conn is server_socket:
                self._client_socket, self._socket_info = server_socket.accept()
                self.read_list.append(self._client_socket)
                logger.debug("Connection from %s", self._socket_info)
            else:
                self._cmd_handler()
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="Connect")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "Connect":
            self.listen()

    def _cmd_handler(self):
        """Handle a binary SARAD command received via the socket."""
