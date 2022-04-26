"""Device actor of the Registration Server -- implementation for raw TCP
as used in Instrument Server 1

:Created:
    2022-04-20

:Authors:
    | Michael Strey <strey@sarad.de>
"""
import socket
import time

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import RxBinaryMsg
from registrationserver.helpers import check_message, make_command_msg
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor

logger.debug("%s -> %s", __package__, __file__)


class Is1Actor(DeviceBaseActor):
    """Actor for dealing with connection to Instrument Server 1"""

    SELECT_COM = b"\xe2"
    CLOSE_COM_PORT = b"\xe9"
    COM_SELECTED = b"\xe5"
    COM_NOT_AVAILABLE = b"\xe6"
    COM_FRAME_ERROR = b"\xe7"
    COM_TIMEOUT = b"\xe8"

    @overrides
    def __init__(self):
        super().__init__()
        self._is_port = None
        self._is_host = None
        self._com_port = None
        self._socket = None

    def receiveMsg_SetupIs1ActorMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for SetupIs1ActorMsg containing setup information
        that is special to the IS1 device actor"""
        self._is_port = msg.is_port
        self._is_host = msg.is_host
        self._com_port = msg.com_port

    def _establish_socket(self):
        if self._socket is None:
            socket.setdefaulttimeout(8)
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            retry = True
            counter = 5
            while retry and counter:
                try:
                    logger.debug(
                        "Trying to connect %s:%d", self._is_host, self._is_port
                    )
                    self._socket.connect((self._is_host, self._is_port))
                    retry = False
                    return True
                except ConnectionRefusedError:
                    counter = counter - 1
                    logger.debug("%d retries left", counter)
                    time.sleep(1)
            if retry:
                logger.error(
                    "Connection refused on %s:%d", self._is_host, self._is_port
                )
                return False
        else:
            return True

    def _destroy_socket(self):
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
                self._socket.close()
            except OSError as exception:
                logger.warning(exception)
            self._socket = None
            logger.debug("Socket shutdown and closed.")

    def _send_via_socket(self, msg):
        retry = True
        counter = 5
        while retry and counter:
            try:
                self._socket.sendall(msg)
                retry = False
            except OSError as exception:
                logger.error(exception)
                try:
                    self._establish_socket()
                except OSError as re_exception:
                    logger.error("Failed to re-establish socket: %s", re_exception)
                counter = counter - 1
                logger.debug("%d retries left", counter)
                time.sleep(1)
        if retry:
            logger.error("Cannot send to IS1")
            try:
                self._destroy_socket()
            except OSError as destroy_exception:
                logger.error("Failed to destroy socket: %s", destroy_exception)
            return

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        cmd_msg = make_command_msg(
            [self.CLOSE_COM_PORT, (self._com_port).to_bytes(1, byteorder="little")]
        )
        self._send_via_socket(cmd_msg)
        super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        self._destroy_socket()
        super().receiveMsg_ChildActorExited(msg, sender)

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if not self._establish_socket():
            logger.error("Can't establish the client socket.")
            return
        self._send_via_socket(msg.data)
        try:
            reply = self._socket.recv(1024)
        except TimeoutError:
            logger.error("Timeout on waiting for reply from IS1")
            return
        return_message = RxBinaryMsg(reply)
        self.send(self.redirector_actor(), return_message)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server."""
        if not self._establish_socket():
            logger.error("Can't establish the client socket.")
            self._forward_reservation(False)
            return
        cmd_msg = make_command_msg(
            [self.SELECT_COM, (self._com_port).to_bytes(1, byteorder="little")]
        )
        self._send_via_socket(cmd_msg)
        try:
            reply = self._socket.recv(1024)
        except TimeoutError:
            logger.error("Timeout on waiting for reply to SELECT_COM.")
            self._forward_reservation(False)
            return
        checked_reply = check_message(reply, multiframe=False)
        if checked_reply["is_valid"] and checked_reply["payload"] == self.COM_SELECTED:
            logger.debug("Reserve at IS1 replied %s", checked_reply)
            self._forward_reservation(True)
        else:
            self._forward_reservation(False)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        self._destroy_socket()
        super().receiveMsg_KillMsg(msg, sender)
