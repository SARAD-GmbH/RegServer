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
    COM_SELECTED = b"\xe5"

    @overrides
    def __init__(self):
        super().__init__()
        self._is_port = None
        self._is_host = None
        self._com_port = None

    def receiveMsg_SetupIs1ActorMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for SetupIs1ActorMsg containing setup information
        that is special to the IS1 device actor"""
        self._is_port = msg.is_port
        self._is_host = msg.is_host
        self._com_port = msg.com_port

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.connect((self._is_host, self._is_port))
            client_socket.sendall(msg.data)
            reply = client_socket.recv(1024)
        return_message = RxBinaryMsg(reply)
        self.send(self.redirector_actor(), return_message)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server."""
        cmd_msg = make_command_msg(
            [self.SELECT_COM, (self._com_port).to_bytes(1, byteorder="little")]
        )
        socket.setdefaulttimeout(3)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            retry = True
            counter = 5
            while retry and counter:
                try:
                    logger.debug(
                        "Trying to connect %s:%d", self._is_host, self._is_port
                    )
                    client_socket.connect((self._is_host, self._is_port))
                    retry = False
                except ConnectionRefusedError:
                    counter = counter - 1
                    logger.debug("%d retries left", counter)
                    time.sleep(1)
            if retry:
                logger.critical(
                    "Connection refused on %s:%d", self._is_host, self._is_port
                )
                self._forward_reservation(False)
                return
            logger.debug("Connected")
            retry = True
            counter = 5
            while retry and counter:
                try:
                    client_socket.sendall(cmd_msg)
                    logger.debug("Msg sent: %s", cmd_msg)
                    retry = False
                except OSError as exception:
                    logger.error(exception)
                    counter = counter - 1
                    logger.debug("%d retries left", counter)
                    time.sleep(1)
            if retry:
                logger.error("Cannot send to IS1")
                self._forward_reservation(False)
                return
            try:
                reply = client_socket.recv(1024)
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
