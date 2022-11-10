"""Device actor of the Registration Server -- implementation for raw TCP
as used in Instrument Server 1

:Created:
    2022-04-20

:Authors:
    | Michael Strey <strey@sarad.de>
"""
import datetime
import socket
import time

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (Is1Address, Is1RemoveMsg,
                                               KillMsg, RxBinaryMsg, Status)
from registrationserver.helpers import check_message, make_command_msg
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor

# logger.debug("%s -> %s", __package__, __file__)


class Is1Actor(DeviceBaseActor):
    """Actor for dealing with connection to Instrument Server 1"""

    GET_FIRST_COM = [b"\xe0", b""]
    GET_NEXT_COM = [b"\xe1", b""]
    SELECT_COM = b"\xe2"
    CLOSE_COM_PORT = b"\xe9"
    COM_SELECTED = b"\xe5"
    COM_NOT_AVAILABLE = b"\xe6"
    COM_FRAME_ERROR = b"\xe7"
    COM_TIMEOUT = b"\xe8"

    @overrides
    def __init__(self):
        super().__init__()
        self._is: Is1Address = None
        self._com_port = None
        self._socket = None
        self.last_activity = datetime.datetime.utcnow()

    def receiveMsg_SetupIs1ActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupIs1ActorMsg containing setup information
        that is special to the IS1 device actor"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._is = msg.is1_address
        self._com_port = msg.com_port
        self.wakeupAfter(datetime.timedelta(seconds=20), payload="Rescan")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "Rescan" and not self.on_kill:
            time_condition = bool(
                datetime.datetime.utcnow() - self.last_activity
                > datetime.timedelta(seconds=10)
            )
            logger.debug(
                "time_condition = %s",
                time_condition,
            )
            if time_condition:
                logger.debug(
                    "Check %s for living instruments",
                    self._is.hostname,
                )
                self._scan_is(self._is)
            self.wakeupAfter(datetime.timedelta(seconds=60), payload="Rescan")
            self.last_activity = datetime.datetime.utcnow()

    def _establish_socket(self):
        if self._socket is None:
            socket.setdefaulttimeout(5)
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            retry_counter = 3
            while retry_counter:
                try:
                    logger.debug(
                        "Trying to connect %s:%d", self._is.ip_address, self._is.port
                    )
                    self._socket.connect((self._is.hostname, self._is.port))
                    retry_counter = 0
                    return True
                except ConnectionRefusedError:
                    retry_counter = retry_counter - 1
                    logger.debug("Connection refused. %d retries left", retry_counter)
                    time.sleep(1)
                except (TimeoutError, socket.timeout, ConnectionResetError):
                    logger.error("Timeout connecting %s", self._is.hostname)
                    retry_counter = 0
                except BlockingIOError:
                    logger.error("BlockingIOError connecting %s", self._is.hostname)
                    retry_counter = 0
            self.send(self.myAddress, KillMsg())
            return False
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
        retry_counter = 5
        success = False
        while retry_counter:
            try:
                self._socket.sendall(msg)
                retry_counter = 0
                success = True
            except OSError as exception:
                logger.error(exception)
                try:
                    self._establish_socket()
                except OSError as re_exception:
                    logger.error("Failed to re-establish socket: %s", re_exception)
                retry_counter = retry_counter - 1
                logger.debug("%d retries left", retry_counter)
                time.sleep(1)
        if not success:
            logger.error("Cannot send to IS1")
            self.send(self.myAddress, KillMsg())

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        if not self._establish_socket():
            logger.error("Can't establish the client socket.")
            return
        # Dirty workaround for bug in SARAD instruments
        # Sometimes an instrument just doesn't answer.
        retry_counter = 5
        success = False
        while retry_counter:
            self._send_via_socket(msg.data)
            try:
                reply = self._socket.recv(1024)
                retry_counter = 0
                success = True
            except (TimeoutError, socket.timeout):
                logger.warning("Timeout on waiting for reply from IS1. Retrying...")
                retry_counter = retry_counter - 1
            except ConnectionResetError as exception:
                logger.error(exception)
                retry_counter = 0
        if not success:
            logger.error("Giving up on %s and removing this actor", self.my_id)
            self.send(self.myAddress, KillMsg())
            reply = b""
        self.send(self.redirector_actor, RxBinaryMsg(reply))
        self.last_activity = datetime.datetime.utcnow()

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument
        """Reserve the requested instrument at the instrument server."""
        if not self._establish_socket():
            logger.error("Can't establish the client socket.")
            self._forward_reservation(Status.IS_NOT_FOUND)
            return
        cmd_msg = make_command_msg(
            [self.SELECT_COM, (self._com_port).to_bytes(1, byteorder="little")]
        )
        self._send_via_socket(cmd_msg)
        try:
            reply = self._socket.recv(1024)
        except (TimeoutError, socket.timeout, ConnectionResetError):
            logger.error("Timeout on waiting for reply to SELECT_COM: %s", cmd_msg)
            self._forward_reservation(Status.IS_NOT_FOUND)
            self._destroy_socket()
            return
        checked_reply = check_message(reply, multiframe=False)
        logger.debug("Reserve at IS1 replied %s", checked_reply)
        if (
            checked_reply["is_valid"]
            and checked_reply["payload"][0].to_bytes(1, byteorder="little")
            == self.COM_SELECTED
        ):
            self._forward_reservation(Status.OK)
        elif (
            checked_reply["is_valid"]
            and checked_reply["payload"] == self.COM_NOT_AVAILABLE
        ):
            self.send(self.myAddress, KillMsg())
        else:
            self._forward_reservation(Status.NOT_FOUND)
        self._destroy_socket()

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        self._destroy_socket()
        super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        self._destroy_socket()
        self.send(self.parent.parent_address, Is1RemoveMsg(is1_address=self._is))
        super().receiveMsg_KillMsg(msg, sender)

    def _scan_is(self, is1_address: Is1Address):
        is_host = is1_address.hostname
        is_port = is1_address.port
        cmd_msg = make_command_msg(self.GET_FIRST_COM)
        logger.debug("Send GetFirstCOM: %s", cmd_msg)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.settimeout(3)
            retry = True
            counter = 3
            while retry and counter:
                try:
                    logger.debug("Trying to connect %s:%d", is_host, is_port)
                    client_socket.connect((is_host, is_port))
                    retry = False
                except ConnectionRefusedError:
                    counter = counter - 1
                    logger.debug("%d retries left", counter)
                    time.sleep(1)
                except (OSError, TimeoutError, socket.timeout):
                    logger.debug("%s:%d not reachable", is_host, is_port)
                    self.send(self.myAddress, KillMsg())
                    return
            if retry:
                logger.critical("Connection refused on %s:%d", is_host, is_port)
                self.send(self.myAddress, KillMsg())
                return
            try:
                client_socket.sendall(cmd_msg)
                reply = client_socket.recv(1024)
            except (ConnectionResetError, TimeoutError, socket.timeout) as exception:
                logger.error("%s. IS1 closed or disconnected.", exception)
                self.send(self.myAddress, KillMsg())
                return
            checked_reply = check_message(reply, multiframe=False)
            while checked_reply["is_valid"] and checked_reply["payload"] not in [
                b"\xe4",
                b"",
            ]:
                cmd_msg = make_command_msg(self.GET_NEXT_COM)
                try:
                    client_socket.sendall(cmd_msg)
                    reply = client_socket.recv(1024)
                except (
                    ConnectionResetError,
                    TimeoutError,
                    socket.timeout,
                ) as exception:
                    logger.error("%s. IS1 closed or disconnected.", exception)
                    self.send(self.myAddress, KillMsg())
                    return
                checked_reply = check_message(reply, multiframe=False)
            client_socket.shutdown(socket.SHUT_WR)
            return
