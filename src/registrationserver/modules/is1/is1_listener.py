"""Listening for notifications from Instrument Server 1

:Created:
    2022-04-14

:Authors:
    | Michael Strey <strey@sarad.de>
"""
import datetime
import select
import socket
import time
from typing import List

from overrides import overrides  # type: ignore
from registrationserver.base_actor import BaseActor
from registrationserver.logger import logger

logger.debug("%s -> %s", __package__, __file__)


class Is1Listener(BaseActor):
    """Listens for messages from Instrument Server 1

    * adds new SARAD Instruments to the system by creating a device actor
    """

    GET_FIRST_COM = [b"\xe0", b""]
    GET_NEXT_COM = [b"\xe1", b""]
    SELECT_COM = [b"\xe2", b""]

    @staticmethod
    def get_ip():
        """Find the external IP address of the computer running the RegServer

        Returns:
            string: IP address
        """
        my_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        my_socket.settimeout(0)
        try:
            # doesn't even have to be reachable
            my_socket.connect(("10.255.255.255", 1))
            address = my_socket.getsockname()[0]
        except Exception:  # pylint: disable=broad-except
            address = "127.0.0.1"
        finally:
            my_socket.close()
        return address

    @staticmethod
    def _make_command_msg(cmd_data: List[bytes]) -> bytes:
        """Encode the message to be sent to the SARAD instrument.
        Arguments are the one byte long command
        and the data bytes to be sent."""
        cmd: bytes = cmd_data[0]
        data: bytes = cmd_data[1]
        payload: bytes = cmd + data
        control_byte = len(payload) - 1
        if cmd:  # Control message
            control_byte = control_byte | 0x80  # set Bit 7
        neg_control_byte = control_byte ^ 0xFF
        checksum = 0
        for byte in payload:
            checksum = checksum + byte
        checksum_bytes = (checksum).to_bytes(2, byteorder="little")
        output = (
            b"B"
            + bytes([control_byte])
            + bytes([neg_control_byte])
            + payload
            + checksum_bytes
            + b"E"
        )
        return output

    @overrides
    def __init__(self):
        super().__init__()
        self.my_parent = None
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        self._host = self.get_ip()
        logger.debug("IP address of Registration Server: %s", self._host)
        for self._port in [50001]:
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

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="Connect")

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
        for _i in range(0, 5):
            try:
                data = self.conn.recv(1024)
                break
            except (ConnectionResetError, BrokenPipeError):
                logger.error("Connection reset by Instrument Server 1.")
                data = None
                time.sleep(5)
        if data is not None and data != b"":
            logger.debug(
                "Received %s from Instrument Server 1",
                data,
            )
            cmd_msg = self._make_command_msg(self.GET_FIRST_COM)
            logger.debug("Get first COM: %s", cmd_msg)
            self.conn.sendall(cmd_msg)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        """Handler to exit the redirector actor."""
        self.read_list[0].close()
        super().receiveMsg_KillMsg(msg, sender)
