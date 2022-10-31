"""Listening for notifications from Instrument Server 1

:Created:
    2022-04-14

:Authors:
    | Michael Strey <strey@sarad.de>
"""
import pickle
import select
import socket
import time
from datetime import timedelta
from typing import List

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (Is1Address, SetDeviceStatusMsg,
                                               SetupIs1ActorMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import app_folder, config, is1_backend_config
from registrationserver.helpers import check_message, make_command_msg
from registrationserver.logger import logger
from registrationserver.modules.backend.is1.is1_actor import Is1Actor
from sarad.sari import SaradInst  # type: ignore

# logger.debug("%s -> %s", __package__, __file__)


class Is1Listener(BaseActor):
    """Listens for messages from Instrument Server 1

    * adds new SARAD Instruments to the system by creating a device actor
    """

    GET_FIRST_COM = [b"\xe0", b""]
    GET_NEXT_COM = [b"\xe1", b""]
    PORTS = [is1_backend_config["REG_PORT"]]

    @staticmethod
    def _get_port_and_id(is_id):
        id_string = is_id.decode("utf-8")
        id_list = id_string.rstrip("\r\n").split("-", 1)
        return {"port": int(id_list[0]), "id": id_list[1]}

    @staticmethod
    def _get_instrument_id(payload: bytes):
        """Decode payload of the reply received from IS1 to get instrument id

        Args:
            payload (bytes): content of the reply to GET_FIRST_COM or GET_NEXT_COM

        Returns:
            Dict of port, type, version, sn, family"""
        try:
            logger.debug("Payload: %s", payload)
            port = int(payload[1])
            type_id = int(payload[2])
            version = int(payload[3])
            serial_number = int.from_bytes(
                payload[4:6], byteorder="little", signed=False
            )
            family_id = int(payload[6])
            hid = Hashids()
            instr_id = hid.encode(family_id, type_id, serial_number)
            return {
                "port": port,
                "type_id": type_id,
                "version": version,
                "sn": serial_number,
                "family_id": family_id,
                "instr_id": instr_id,
            }
        except TypeError:
            logger.error("TypeError when parsing the payload.")
            return False
        except ReferenceError:
            logger.error("ReferenceError when parsing the payload.")
            return False
        except LookupError:
            logger.error("LookupError when parsing the payload.")
            return False
        except ValueError:
            logger.error("ValueError when parsing the payload.")
            return False
        except Exception:  # pylint: disable=broad-except
            logger.error("Unknown error when parsing the payload.")
            return False

    @staticmethod
    def _get_name(instr_id):
        """Get instrument name from library of SARAD products and instr_id

        Args:
            instr_id (str): hash id of family_id, type_id, serial number

        Returns:
            string with name of instrument type"""
        hid = Hashids()
        family_id = hid.decode(instr_id)[0]
        type_id = hid.decode(instr_id)[1]
        for family in SaradInst.products:
            if family["family_id"] == family_id:
                for instr_type in family["types"]:
                    if instr_type["type_id"] == type_id:
                        return instr_type["type_name"]
        return "Unknown"

    @staticmethod
    def _deduplicate(is1_addresses: List[Is1Address]):
        return list(set(is1_addresses))

    @overrides
    def __init__(self):
        super().__init__()
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        my_ip = config["MY_IP"]
        logger.debug("IP address of Registration Server: %s", my_ip)
        for my_port in self.PORTS:
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_socket.bind((my_ip, my_port))
                my_port = server_socket.getsockname()[1]
                break
            except OSError as exception:
                logger.error("Cannot use port %d. %s", my_port, exception)
                server_socket.close()
        try:
            server_socket.listen()  # listen(5) maybe???
        except OSError:
            my_port = None
        logger.debug("Server socket: %s", server_socket)
        self.read_list = [server_socket]
        if my_port is not None:
            logger.info("Socket listening on %s:%d", my_ip, my_port)
        self.is1_addresses = []  # List of Is1Adress
        self.active_is1_addresses = []  # List of Is1Adress with device Actors
        self.pickle_file_name = f"{app_folder}wlan_instruments.pickle"

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        try:
            with open(self.pickle_file_name, "rb") as pickle_file:
                self.is1_addresses = self._deduplicate(pickle.load(pickle_file))
        except FileNotFoundError:
            logger.warning("Cannot find %s", self.pickle_file_name)
        except AttributeError:
            logger.error("Error reading persistent instrument server list")
        logger.info(
            "List of formerly used IS1 addresses restored from %s: %s",
            self.pickle_file_name,
            self.is1_addresses,
        )
        addresses = self.is1_addresses
        for address in addresses:
            self._scan_is(address)
        self._subscribe_to_actor_dict_msg()
        self.wakeupAfter(timedelta(seconds=0.01), payload="Connect")
        self.wakeupAfter(
            timedelta(seconds=is1_backend_config["SCAN_INTERVAL"]),
            payload="Rescan",
        )

    def listen(self):
        """Listen for notification from Instrument Server"""
        server_socket = self.read_list[0]
        timeout = 0.1
        try:
            readable, _writable, _errored = select.select(
                self.read_list, [], [], timeout
            )
            for self.conn in readable:
                if self.conn is server_socket:
                    self._client_socket, self._socket_info = server_socket.accept()
                    self.read_list.append(self._client_socket)
                    logger.info("Connection from %s", self._socket_info)
                else:
                    self._cmd_handler(self._socket_info[0])
        except ValueError:
            logger.error("None of ports in %s available", self.PORTS)
        self.wakeupAfter(timedelta(seconds=1), payload="Connect")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "Connect" and not self.on_kill:
            self.listen()
        if msg.payload == "Rescan" and not self.on_kill:
            addresses = self.is1_addresses
            for address in addresses:
                logger.info(
                    "Check %s for living instruments",
                    address.hostname,
                )
                self._scan_is(address)
            self.wakeupAfter(
                timedelta(seconds=is1_backend_config["SCAN_INTERVAL"]), payload="Rescan"
            )

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
            logger.debug("IS1 hostname: %s", is_port_id["id"])
            self._scan_is(
                Is1Address(
                    ip_address=is_host,
                    port=is_port_id["port"],
                    hostname=is_port_id["id"],
                )
            )

    def _scan_is(self, address: Is1Address):
        is_host = address.hostname
        is_port = address.port
        cmd_msg = make_command_msg(self.GET_FIRST_COM)
        logger.debug("Send GetFirstCOM: %s", cmd_msg)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.settimeout(3)
            retry = True
            counter = 5
            while retry and counter:
                try:
                    logger.debug("Trying to connect %s:%d", address.ip_address, is_port)
                    client_socket.connect((is_host, is_port))
                    retry = False
                except ConnectionRefusedError:
                    counter = counter - 1
                    logger.debug("%d retries left", counter)
                    time.sleep(1)
                except (OSError, TimeoutError, socket.timeout):
                    logger.debug("%s:%d not reachable", is_host, is_port)
                    return
            if retry:
                logger.critical("Connection refused on %s:%d", is_host, is_port)
                return
            try:
                client_socket.sendall(cmd_msg)
                reply = client_socket.recv(1024)
            except (
                OSError,
                TimeoutError,
                socket.timeout,
                ConnectionResetError,
            ) as exception:
                logger.error("%s. IS1 closed or disconnected.", exception)
                return
            checked_reply = check_message(reply, multiframe=False)
            while checked_reply["is_valid"] and checked_reply["payload"] not in [
                b"\xe4",
                b"",
            ]:
                this_instrument = self._get_instrument_id(checked_reply["payload"])
                if this_instrument:
                    logger.info(
                        "Instrument %s on COM port %d",
                        this_instrument["instr_id"],
                        this_instrument["port"],
                    )
                    self._create_and_setup_actor(
                        instr_id=this_instrument["instr_id"],
                        port=this_instrument["port"],
                        is1_address=address,
                    )
                    cmd_msg = make_command_msg(self.GET_NEXT_COM)
                    try:
                        client_socket.sendall(cmd_msg)
                        reply = client_socket.recv(1024)
                    except (
                        OSError,
                        TimeoutError,
                        socket.timeout,
                        ConnectionResetError,
                    ) as exception:
                        logger.error("%s. IS1 closed or disconnected.", exception)
                        return
                    checked_reply = check_message(reply, multiframe=False)
                else:
                    logger.error("Error parsing payload received from instrument")
                    return
            client_socket.shutdown(socket.SHUT_WR)
            return

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        """Handler to exit the redirector actor."""
        self.read_list[0].close()
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        super().receiveMsg_ActorExitRequest(msg, sender)
        self.is1_addresses.extend(self.active_is1_addresses)
        with open(self.pickle_file_name, "wb") as pickle_file:
            pickle.dump(
                self._deduplicate(self.is1_addresses),
                pickle_file,
                pickle.HIGHEST_PROTOCOL,
            )

    def _create_and_setup_actor(self, instr_id, port, is1_address: Is1Address):
        logger.debug("[_create_and_setup_actor]")
        hid = Hashids()
        family_id = hid.decode(instr_id)[0]
        type_id = hid.decode(instr_id)[1]
        serial_number = hid.decode(instr_id)[2]
        if family_id == 5:
            sarad_type = "sarad-dacm"
        elif family_id in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "[Add Instrument]: unknown instrument family (index: %s)",
                family_id,
            )
            sarad_type = "unknown"
        actor_id = f"{instr_id}.{sarad_type}.is1"
        set_of_instruments = set()
        set_of_instruments.add(actor_id)
        if actor_id not in self.child_actors:
            logger.debug("Create actor %s", actor_id)
            device_actor = self._create_actor(Is1Actor, actor_id, None)
            self.send(
                device_actor,
                SetupIs1ActorMsg(
                    is1_address=is1_address,
                    com_port=port,
                ),
            )
        else:
            device_actor = self.child_actors[actor_id]["actor_address"]
        device_status = {
            "Identification": {
                "Name": self._get_name(instr_id),
                "Family": family_id,
                "Type": type_id,
                "Serial number": serial_number,
                "Host": is1_address.hostname,
                "Origin": is1_address.hostname,
                "Protocol": sarad_type,
            },
            "State": 2,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))
        logger.debug("IS1 list before add: %s", self.is1_addresses)
        is1_hostnames = []
        for address in self.is1_addresses:
            is1_hostnames.append(address.hostname)
        if is1_address.hostname not in is1_hostnames:
            self.active_is1_addresses.append(is1_address)
        else:
            self.active_is1_addresses.append(
                self.is1_addresses.pop(self.is1_addresses.index(is1_address))
            )
        logger.debug("List of active IS1: %s", self.active_is1_addresses)
        logger.debug("List of IS1 for next scan: %s", self.is1_addresses)

    def receiveMsg_Is1RemoveMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for message informing about the IS1 address
        belonging to a device actor that is about to be removed."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.is1_addresses.append(
            self.active_is1_addresses.pop(
                self.active_is1_addresses.index(msg.is1_address)
            )
        )
        self.is1_addresses = self._deduplicate(self.is1_addresses)
