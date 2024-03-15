"""Device actor of the Registration Server -- implementation for raw TCP
as used in Instrument Server 1

:Created:
    2022-04-20

:Authors:
    | Michael Strey <strey@sarad.de>
"""
import socket
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Thread
from time import sleep
from typing import Union

from overrides import overrides  # type: ignore
from regserver.actor_messages import (Is1Address, Is1RemoveMsg, RxBinaryMsg,
                                      Status)
from regserver.config import usb_backend_config
from regserver.helpers import check_message, make_command_msg
from regserver.logger import logger
from regserver.modules.device_actor import DeviceBaseActor
from sarad.dacm import DacmInst  # type: ignore
from sarad.doseman import DosemanInst  # type: ignore
from sarad.radonscout import RscInst  # type: ignore
from sarad.sari import SaradInst  # type: ignore


class ThreadType(Enum):
    """One item for every possible thread."""

    CHECK_CONNECTION = 1
    TX_BINARY = 2
    RESERVE = 3


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
        self.status = Status.OK
        self.check_connection_thread = Thread(
            target=self.scan_is,
            daemon=True,
        )
        self.tx_binary_thread = Thread(
            target=self._tx_binary,
            kwargs={"data": None, "sender": None},
            daemon=True,
        )
        self.reserve_thread = Thread(
            target=self._reserve_function,
            daemon=True,
        )
        self.instrument: Union[SaradInst, None] = None

    def _start_thread(self, thread, thread_type: ThreadType):
        if (
            not self.check_connection_thread.is_alive()
            and not self.tx_binary_thread.is_alive()
            and not self.reserve_thread.is_alive()
        ):
            if thread_type == ThreadType.CHECK_CONNECTION:
                self.check_connection_thread = thread
                self.check_connection_thread.start()
            elif thread_type == ThreadType.TX_BINARY:
                self.tx_binary_thread = thread
                self.tx_binary_thread.start()
            elif thread_type == ThreadType.RESERVE:
                self.reserve_thread = thread
                self.reserve_thread.start()
        else:
            self.wakeupAfter(timedelta(seconds=0.5), payload=(thread, thread_type))

    def receiveMsg_SetupIs1ActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupIs1ActorMsg containing setup information
        that is special to the IS1 device actor"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._is = msg.is1_address
        self._com_port = msg.com_port
        family_id = msg.family_id
        if family_id == 1:
            family_class = DosemanInst
        elif family_id == 2:
            family_class = RscInst
        elif family_id == 5:
            family_class = DacmInst
        else:
            logger.critical("Family %s not supported", family_id)
            return
        self.instrument = family_class()
        if usb_backend_config["SET_RTC"]:
            if usb_backend_config["USE_UTC"]:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            logger.info("Set RTC of %s to %s", self.my_id, now)
            # TODO self.instrument.set_real_time_clock(now)
        self.wakeupAfter(timedelta(seconds=10), payload="Rescan")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        try:
            is_reserved = self.device_status["Reservation"]["Active"]
        except KeyError:
            is_reserved = False
        if msg.payload == "Rescan":
            self.wakeupAfter(timedelta(seconds=10), payload="Rescan")
            if (not self.on_kill) and (not is_reserved):
                logger.debug(
                    "Check %s for living instruments",
                    self._is.hostname,
                )
                self._start_thread(
                    Thread(
                        target=self.scan_is,
                        kwargs={"is1_address": self._is},
                        daemon=True,
                    ),
                    ThreadType.CHECK_CONNECTION,
                )
        elif isinstance(msg.payload[0], Thread):
            self._start_thread(msg.payload[0], msg.payload[1])

    def _establish_socket(self):
        try:
            if self._socket is None:
                socket.setdefaulttimeout(5)
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                retry_counter = 2
                while retry_counter:
                    try:
                        logger.debug(
                            "Trying to connect %s:%d",
                            self._is.hostname,
                            self._is.port,
                        )
                        self._socket.connect((self._is.hostname, self._is.port))
                        retry_counter = 0
                        return
                    except ConnectionRefusedError:
                        retry_counter = retry_counter - 1
                        logger.debug(
                            "Connection refused. %d retries left", retry_counter
                        )
                        sleep(1)
                    except (TimeoutError, socket.timeout, ConnectionResetError):
                        logger.error("Timeout connecting %s", self._is.hostname)
                        retry_counter = 0
                    except BlockingIOError:
                        logger.error("BlockingIOError connecting %s", self._is.hostname)
                        retry_counter = 0
                self._kill_myself()
                self._socket = None
        except OSError as re_exception:
            logger.error("Failed to re-establish socket: %s", re_exception)
            self._socket = None

    def _destroy_socket(self):
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
                self._socket.close()
            except OSError as exception:
                logger.warning(exception)
            self._socket = None
            logger.debug("Socket shutdown and closed.")

    def _send_via_socket(self, msg) -> bool:
        retry_counter = 2
        success = False
        while retry_counter:
            try:
                self._socket.sendall(msg)
                retry_counter = 0
                success = True
            except OSError as exception:
                logger.error(exception)
                self._establish_socket()
                retry_counter = retry_counter - 1
                logger.debug("%d retries left", retry_counter)
                sleep(1)
        return success

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        is_reserved = self.device_status.get("Reservation", False)
        if is_reserved:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        if is_reserved:
            self._start_thread(
                Thread(
                    target=self._tx_binary,
                    kwargs={"data": msg.data},
                    daemon=True,
                ),
                ThreadType.TX_BINARY,
            )

    def _tx_binary(self, data):
        self._establish_socket()
        if self._socket is None:
            logger.error("Can't establish the client socket.")
            return
        # Dirty workaround for bug in SARAD instruments
        # Sometimes an instrument just doesn't answer.
        retry_counter = 2
        success = False
        while retry_counter:
            if self._send_via_socket(data):
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
            self._kill_myself()
            reply = b""
        self.send(self.redirector_actor, RxBinaryMsg(reply))

    @overrides
    def _request_reserve_at_is(self):
        # pylint: disable=unused-argument
        """Reserve the requested instrument at the instrument server."""
        try:
            is_reserved = self.device_status["Reservation"]["Active"]
        except KeyError:
            is_reserved = False
        if is_reserved:
            self.status = Status.OCCUPIED
            self._finish_reserve()
        else:
            self._start_thread(
                Thread(
                    target=self._reserve_function,
                    daemon=True,
                ),
                ThreadType.RESERVE,
            )

    def _reserve_function(self):
        self._establish_socket()
        if self._socket is None:
            logger.error("Can't establish the client socket.")
            self._handle_reserve_reply_from_is(Status.IS_NOT_FOUND)
            return
        cmd_msg = make_command_msg(
            [self.SELECT_COM, (self._com_port).to_bytes(1, byteorder="little")]
        )
        if self._send_via_socket(cmd_msg):
            try:
                reply = self._socket.recv(1024)
            except (TimeoutError, socket.timeout, ConnectionResetError):
                logger.error("Timeout on waiting for reply to SELECT_COM: %s", cmd_msg)
                self.status = Status.IS_NOT_FOUND
            else:
                checked_reply = check_message(reply, multiframe=False)
                logger.debug("Reserve at IS1 replied %s", checked_reply)
                if (
                    checked_reply["is_valid"]
                    and checked_reply["payload"][0].to_bytes(1, byteorder="little")
                    == self.COM_SELECTED
                ):
                    self.status = Status.OK
                else:
                    self.status = Status.NOT_FOUND
        else:
            self.status = Status.IS_NOT_FOUND
        self._destroy_socket()
        self._finish_reserve()

    def _finish_reserve(self):
        """Forward the reservation state from the Instrument Server to the REST API."""
        self._handle_reserve_reply_from_is(self.status)

    @overrides
    def _request_free_at_is(self):
        self._destroy_socket()
        self._handle_free_reply_from_is(Status.OK)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        self._destroy_socket()
        self.send(self.parent.parent_address, Is1RemoveMsg(is1_address=self._is))
        super()._kill_myself(register=register, resurrect=resurrect)

    def scan_is(self, is1_address: Is1Address):
        """Look for SARAD instruments at the given Instrument Server"""
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
                    sleep(1)
                except (OSError, TimeoutError, socket.timeout):
                    logger.debug("%s:%d not reachable", is_host, is_port)
                    self._kill_myself()
                    return
            if retry:
                logger.error("Connection refused on %s:%d", is_host, is_port)
                self._kill_myself()
                return
            try:
                client_socket.sendall(cmd_msg)
                reply = client_socket.recv(1024)
            except (ConnectionResetError, TimeoutError, socket.timeout) as exception:
                logger.error("%s. IS1 closed or disconnected.", exception)
                self._kill_myself()
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
                    self._kill_myself()
                    return
                checked_reply = check_message(reply, multiframe=False)
            client_socket.shutdown(socket.SHUT_WR)
