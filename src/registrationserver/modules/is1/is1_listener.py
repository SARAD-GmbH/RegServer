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

    @staticmethod
    def _get_port_and_id(is_id):
        id_string = is_id.decode("utf-8")
        id_list = id_string.split("-")
        return {"port": int(id_list[0]), "id": id_list[1]}

    @staticmethod
    def _check_message(answer: bytes, multiframe: bool):
        """Returns a dictionary of:
        is_valid: True if answer is valid, False otherwise
        is_control_message: True if control message
        payload: Payload of answer
        number_of_bytes_in_payload
        raw"""
        logger.debug("Checking answer from serial port:")
        logger.debug("Raw answer: %s", answer)
        if answer.startswith(b"B") and answer.endswith(b"E"):
            control_byte = answer[1]
            control_byte_ok = bool((control_byte ^ 0xFF) == answer[2])
            number_of_bytes_in_payload = (control_byte & 0x7F) + 1
            is_control = bool(control_byte & 0x80)
            status_byte = answer[3]
            logger.debug("Status byte: %s", status_byte)
            payload = answer[3 : 3 + number_of_bytes_in_payload]
            calculated_checksum = 0
            for byte in payload:
                calculated_checksum = calculated_checksum + byte
            received_checksum_bytes = answer[
                3 + number_of_bytes_in_payload : 5 + number_of_bytes_in_payload
            ]
            received_checksum = int.from_bytes(
                received_checksum_bytes, byteorder="little", signed=False
            )
            checksum_ok = bool(received_checksum == calculated_checksum)
            is_valid = bool(control_byte_ok and checksum_ok)
        else:
            logger.debug("Invalid B-E frame")
            is_valid = False
        if not is_valid:
            is_control = False
            payload = b""
            number_of_bytes_in_payload = 0
        # is_rend is True if that this is the last frame of a multiframe reply
        # (DOSEman data download)
        is_rend = bool(is_valid and is_control and (payload == b"\x04"))
        logger.debug("Payload: %s", payload)
        return {
            "is_valid": is_valid,
            "is_control": is_control,
            "is_last_frame": (not multiframe) or is_rend,
            "payload": payload,
            "number_of_bytes_in_payload": number_of_bytes_in_payload,
            "raw": answer,
        }

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
                self._cmd_handler(self._socket_info[0])
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="Connect")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "Connect":
            self.listen()

    def _cmd_handler(self, is_host):
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
            is_port_id = self._get_port_and_id(data)
            logger.debug("IS1 port: %d", is_port_id["port"])
            logger.debug("IS1 id: %s", is_port_id["id"])
            cmd_msg = self._make_command_msg(self.GET_FIRST_COM)
            logger.debug("Send GetFirstCOM: %s", cmd_msg)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((is_host, is_port_id["port"]))
                client_socket.sendall(cmd_msg)
                reply = client_socket.recv(1024)
                checked_reply = self._check_message(reply, multiframe=False)
                while checked_reply != b"\xe4":
                    logger.debug("Received reply: %s", checked_reply["payload"])
                    cmd_msg = self._make_command_msg(self.GET_NEXT_COM)
                    client_socket.sendall(cmd_msg)
                    reply = client_socket.recv(1024)
                    checked_reply = self._check_message(reply, multiframe=False)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        """Handler to exit the redirector actor."""
        self.read_list[0].close()
        super().receiveMsg_KillMsg(msg, sender)
