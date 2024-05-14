"""Device actor of the Registration Server -- implementation for raw TCP
as used in Instrument Server 1

:Created:
    2022-04-20

:Authors:
    | Michael Strey <strey@sarad.de>
"""

import socket
from datetime import timedelta
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
from sarad.instrument import Route  # type: ignore
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
    SELECT_COM = b"\xe2"
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
        self.instrument.route = Route(
            ip_address=self._is.hostname, ip_port=self._is.port
        )
        self.instrument.device_id = self.my_id
        if usb_backend_config["SET_RTC"]:
            self.instrument.utc_offset = usb_backend_config["UTC_OFFSET"]
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
                        daemon=True,
                    ),
                    ThreadType.CHECK_CONNECTION,
                )
        elif isinstance(msg.payload[0], Thread):
            self._start_thread(msg.payload[0], msg.payload[1])

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
        reply = self.instrument.get_message_payload(data, timeout=1)
        self.send(self.redirector_actor, RxBinaryMsg(reply["raw"]))

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
            self._handle_reserve_reply_from_is(self.status)
        else:
            self._start_thread(
                Thread(
                    target=self._reserve_function,
                    daemon=True,
                ),
                ThreadType.RESERVE,
            )

    def _reserve_function(self):
        cmd_msg = make_command_msg(
            [self.SELECT_COM, (self._com_port).to_bytes(1, byteorder="little")]
        )
        checked_reply = self.instrument.get_message_payload(cmd_msg, timeout=1)
        if (
            checked_reply["is_valid"]
            and checked_reply["payload"][0].to_bytes(1, byteorder="little")
            == self.COM_SELECTED
        ):
            self.status = Status.OK
        else:
            self.status = Status.NOT_FOUND
        self._handle_reserve_reply_from_is(self.status)

    @overrides
    def _request_free_at_is(self):
        self.instrument.release_instrument()
        self._handle_free_reply_from_is(Status.OK)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        self.instrument.release_instrument()
        self.send(self.parent.parent_address, Is1RemoveMsg(is1_address=self._is))
        super()._kill_myself(register=register, resurrect=resurrect)

    def scan_is(self):
        """Look for SARAD instruments at the given Instrument Server"""
        cmd_msg = make_command_msg(self.GET_FIRST_COM)
        checked_reply = self.instrument.get_message_payload(cmd_msg, timeout=1)
        logger.debug("Scan IS replied: %s", checked_reply)
        if not checked_reply["is_valid"]:
            self._kill_myself()
