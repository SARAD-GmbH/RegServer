"""Device actor for socket communication in the backend

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import socket
import time

import requests
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import KillMsg, RxBinaryMsg, Status
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor

logger.debug("%s -> %s", __package__, __file__)

CMD_CYCLE_TIMEOUT = 1


class DeviceActor(DeviceBaseActor):
    """Actor for dealing with raw socket connections"""

    @overrides
    def __init__(self):
        super().__init__()
        self._socket = None
        self._is_host = None
        self._is_port = None

    def receiveMsg_SetupIs1ActorMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for SetupIs1ActorMsg containing setup information
        that is special to the IS1 device actor"""
        self._is_port = msg.is_port
        self._is_host = msg.is_host

    def _establish_socket(self):
        if self._socket is None:
            socket.setdefaulttimeout(5)
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
                except socket.timeout as exception:
                    logger.error("%s. Killing myself.", exception)
                    self.send(self.myAddress, KillMsg())
                    return False
            if retry:
                logger.error(
                    "Connection refused on %s:%d", self._is_host, self._is_port
                )
                self.send(self.myAddress, KillMsg())
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
            self.send(self.myAddress, KillMsg())

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        if not self._establish_socket():
            logger.error("Can't establish the client socket.")
            return
        self._send_via_socket(msg.data)
        try:
            reply = self._socket.recv(1024)
        except (TimeoutError, socket.timeout):
            logger.error("Timeout on waiting for reply from IS")
            self.send(self.myAddress, KillMsg())
            return
        return_message = RxBinaryMsg(reply)
        self.send(self.redirector_actor, return_message)

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        self._destroy_socket()
        super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        self._destroy_socket()
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server. This function has
        to be implemented (overridden) in the protocol specific modules.
        TODO: Read the reply from the REST API of the Instrument Server.
        In this dummy we suppose, that the instrument is always available for us.
        """
        base_url = f'http://{self._is_host}:{config["API_PORT"]}'
        device_id = self.my_id
        app = f"{self.app} - {self.user}"
        resp = requests.get(f"{base_url}/list/{device_id}/reserve", {"who": app})
        if resp.status_code != 200:
            success = Status.IS_NOT_FOUND
        else:
            logger.debug(resp.json())
            try:
                success = Status(resp.json()["Error code"])
            except KeyError:
                success = Status.ERROR
        self._forward_reservation(success)
