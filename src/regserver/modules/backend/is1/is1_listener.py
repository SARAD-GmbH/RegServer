"""Listening for notifications from Instrument Server 1

:Created:
    2022-04-14

:Authors:
    | Michael Strey <strey@sarad.de>
"""

import select
import socket
import time
from datetime import datetime, timedelta
from threading import Thread

import tomlkit
from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, HostInfoMsg, HostObj,
                                      Is1Address, SetDeviceStatusMsg,
                                      SetupUsbActorMsg, TransportTechnology)
from regserver.base_actor import BaseActor
from regserver.config import CONFIG_FILE, config, is1_backend_config
from regserver.helpers import check_message, make_command_msg
from regserver.hostname_functions import get_fqdn_from_pqdn
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor
from sarad.cluster import id_family_mapping  # type: ignore
from sarad.global_helpers import (decode_instr_id, encode_instr_id,
                                  get_sarad_type, sarad_family)
from sarad.sari import Route, SaradInst  # type: ignore


class Is1Listener(BaseActor):
    """Listens for messages from Instrument Server 1

    * adds new SARAD Instruments to the system by creating a device actor
    """

    GET_FIRST_COM = [b"\xe0", b""]
    SELECT_COM = b"\xe2"
    COM_SELECTED = b"\xe5"
    COM_NOT_AVAILABLE = b"\xe6"
    COM_FRAME_ERROR = b"\xe7"
    COM_TIMEOUT = b"\xe8"
    PORTS = [is1_backend_config["REG_PORT"]]

    @staticmethod
    def _get_port_and_id(is_id):
        id_string = is_id.decode("utf-8")
        id_list = id_string.rstrip("\r\n").split("-", 1)
        port = int(id_list[0])
        host = id_list[1]
        fqdn = get_fqdn_from_pqdn(host)
        return {"port": port, "id": fqdn}

    @staticmethod
    def _get_instrument_id(payload: bytes):
        """Decode payload of the reply received from IS1 to get instrument id

        Args:
            payload (bytes): content of the reply to GET_FIRST_COM

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
            instr_id = encode_instr_id(family_id, type_id, serial_number)
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
        family_id = decode_instr_id(instr_id)[0]
        type_id = decode_instr_id(instr_id)[1]
        for instr_type in sarad_family(family_id)["types"]:
            if instr_type["type_id"] == type_id:
                return instr_type["type_name"]
        return "Unknown"

    @staticmethod
    def _deduplicate(list_of_objects: list[Is1Address]):
        return list(set(list_of_objects))

    @overrides
    def __init__(self):
        super().__init__()
        self._client_socket = None
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
        self.is1_addresses = []  # List of Is1Address
        self.active_is1_addresses = (
            {}
        )  # Dict of Is1Address with device Actor_Ids as keys
        self.scan_is_thread = Thread(target=self._scan_is_function, daemon=True)
        self.cmd_thread = Thread(target=self._cmd_handler_function, daemon=True)
        self.actor_type = ActorType.HOST
        self.last_ip = ""
        self.instrument: SaradInst = None

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        hosts = is1_backend_config["IS1_HOSTS"]
        logger.info(hosts)
        deduplicated_hosts = list(set(hosts))
        for host in deduplicated_hosts:
            self.is1_addresses.append(
                Is1Address(hostname=host, port=is1_backend_config["IS1_PORT"])
            )
        logger.info(
            "List of formerly used IS1 addresses: %s",
            self.is1_addresses,
        )
        self._scan_is()
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
                    self._client_socket, _socket_info = server_socket.accept()
                    self.read_list.append(self._client_socket)
                    logger.info("Connection from %s", _socket_info)
                    self.last_ip = _socket_info[0]
                else:
                    self._cmd_handler()
        except ValueError:
            logger.error("None of ports in %s available", self.PORTS)

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "Connect" and not self.on_kill:
            self.listen()
            self.wakeupAfter(timedelta(seconds=1), payload="Connect")
        if msg.payload == "Rescan" and not self.on_kill:
            self._scan_is()
            self.wakeupAfter(
                timedelta(seconds=is1_backend_config["SCAN_INTERVAL"]), payload="Rescan"
            )

    def _cmd_handler(self):
        if (not self.cmd_thread.is_alive()) and (not self.scan_is_thread.is_alive()):
            self.cmd_thread = Thread(target=self._cmd_handler_function, daemon=True)
            try:
                self.cmd_thread.start()
            except RuntimeError:
                pass

    def _cmd_handler_function(self):
        """Handle a binary SARAD command received via the socket."""
        try:
            fqdn = socket.getfqdn(self.last_ip)
        except socket.error:
            fqdn = ""
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
            if not fqdn:
                fqdn = is_port_id["id"]
            logger.debug("IS1 port: %d", is_port_id["port"])
            logger.debug("IS1 hostname: %s", fqdn)
            self._scan_one_is(
                Is1Address(
                    hostname=fqdn,
                    port=is_port_id["port"],
                )
            )

    def _scan_is(self):
        if (not self.cmd_thread.is_alive()) and (not self.scan_is_thread.is_alive()):
            logger.debug("Scan IS1 thread isn't alive.")
            self.scan_is_thread = Thread(target=self._scan_is_function, daemon=True)
            try:
                self.scan_is_thread.start()
            except RuntimeError:
                pass
        else:
            logger.debug("Scan IS1 thread is still alive.")

    def _scan_is_function(self):
        for address in self.is1_addresses:
            logger.debug(
                "Check %s for living instruments",
                address.hostname,
            )
            self._scan_one_is(address)
        self._update_host_info()

    def _get_message_payload(self, cmd_msg, address: Is1Address):
        is_host = address.hostname
        is_port = address.port
        result = {"is_valid": False}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.settimeout(5)
            retry = True
            counter = 1
            time.sleep(1)
            while retry and counter:
                try:
                    logger.debug("Trying to connect %s:%d", address.hostname, is_port)
                    client_socket.connect((is_host, is_port))
                    retry = False
                except ConnectionRefusedError:
                    counter = counter - 1
                    logger.debug("%d retries left", counter)
                    time.sleep(1)
                except (OSError, TimeoutError, socket.timeout) as exception:
                    logger.debug("%s:%d not reachable. %s", is_host, is_port, exception)
                    return result
            if retry:
                logger.error("Connection refused on %s:%d", is_host, is_port)
                return result
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
                return result
            client_socket.shutdown(socket.SHUT_WR)
            return check_message(reply, multiframe=False)

    def _scan_one_is(self, address: Is1Address):
        cmd_msg = make_command_msg(self.GET_FIRST_COM)
        logger.debug("Send GetFirstCOM: %s", cmd_msg)
        checked_reply = self._get_message_payload(cmd_msg, address)
        if checked_reply["is_valid"] and checked_reply["payload"] not in [
            b"\xe4",
            b"",
        ]:
            this_instrument = self._get_instrument_id(checked_reply["payload"])
            if this_instrument:
                logger.info(
                    "Instrument %s on COM%d",
                    this_instrument["instr_id"],
                    this_instrument["port"],
                )
                cmd_msg = make_command_msg(
                    [
                        self.SELECT_COM,
                        (this_instrument["port"]).to_bytes(1, byteorder="little"),
                    ]
                )
                checked_reply = self._get_message_payload(cmd_msg, address)
                if (
                    checked_reply["is_valid"]
                    and checked_reply["payload"][0].to_bytes(1, byteorder="little")
                    == self.COM_SELECTED
                ):
                    instr_id = this_instrument["instr_id"]
                    family_id = decode_instr_id(instr_id)[0]
                    if id_family_mapping.get(family_id) is not None:
                        self._create_and_setup_actor(
                            instr_id=instr_id,
                            is1_address=address,
                            firmware_version=this_instrument["version"],
                        )
                self._update_host_info()
            else:
                logger.error("Error parsing payload received from instrument")

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        """Handler to exit the redirector actor."""
        self.read_list[0].close()
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        super().receiveMsg_ActorExitRequest(msg, sender)
        for _actor_id, is1_address in self.active_is1_addresses.items():
            self.is1_addresses.append(is1_address)
        logger.info("is1_addresses = %s", self.is1_addresses)
        with open(CONFIG_FILE, encoding="utf8") as custom_file:
            customization = tomlkit.load(custom_file)
        if not customization.get("is1_backend", False):
            customization["is1_backend"] = {"hosts": []}
        if not customization["is1_backend"].get("hosts", False):
            customization["is1_backend"]["hosts"] = []
        is1_hosts = customization["is1_backend"]["hosts"]
        for is1_address in self.is1_addresses:
            is1_hosts.append(is1_address.hostname)
        customization["is1_backend"]["hosts"] = list(set(is1_hosts))
        with open(CONFIG_FILE, "w", encoding="utf8") as custom_file:
            tomlkit.dump(customization, custom_file)

    def _create_and_setup_actor(
        self, instr_id, is1_address: Is1Address, firmware_version: int
    ):
        logger.debug("[_create_and_setup_actor]")
        family_id = decode_instr_id(instr_id)[0]
        sarad_type = get_sarad_type(instr_id)
        actor_id = f"{instr_id}.{sarad_type}.is1"
        route = Route(ip_address=is1_address.hostname, ip_port=is1_address.port)
        self.instrument = id_family_mapping.get(family_id)
        if self.instrument is None:
            logger.critical("Family %s not supported", family_id)
            return
        if actor_id not in self.child_actors:
            self.instrument.route = route
            try:
                is_connected = self.instrument.get_description()
                logger.info(is_connected)
            except TypeError:
                logger.error("Cannot get instrument description of %s", self.my_id)
                is_connected = False
            if not is_connected:
                logger.error("%s isn't a valid instrument", instr_id)
                return
            logger.debug("Create actor %s", actor_id)
            family = id_family_mapping.get(family_id).family
            route = Route(ip_address=is1_address.hostname, ip_port=is1_address.port)
            device_actor = self._create_actor(UsbActor, actor_id, None)
            self.send(
                device_actor,
                SetupUsbActorMsg(route, family, True),
            )
        else:
            device_actor = self.child_actors[actor_id]["actor_address"]
        device_status = {
            "Identification": {
                "Name": self.instrument.type_name,
                "Family": family_id,
                "Type": decode_instr_id(instr_id)[1],
                "Serial number": decode_instr_id(instr_id)[2],
                "Host": is1_address.hostname,
                "Firmware version": firmware_version,
                "IS Id": is1_address.hostname,
                "Protocol": sarad_type,
            },
            "State": 2,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))
        logger.debug("IS1 list before add: %s", self.is1_addresses)
        self.active_is1_addresses[actor_id] = is1_address
        try:
            self.is1_addresses.remove(is1_address)
        except (KeyError, ValueError, TypeError):
            logger.error("%s not in self.is1_addresses", is1_address)
        logger.debug("List of active IS1: %s", self.active_is1_addresses)
        logger.debug("List of IS1 for next scan: %s", self.is1_addresses)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        if not self.on_kill:
            for actor_id, child_actor in self.child_actors.items():
                if child_actor["actor_address"] == msg.childAddress:
                    try:
                        self.is1_addresses.append(
                            self.active_is1_addresses.pop(actor_id)
                        )
                        self.is1_addresses = self._deduplicate(self.is1_addresses)
                        logger.debug("Addresses for next scan: %s", self.is1_addresses)
                        self._update_host_info()
                    except (KeyError, ValueError, TypeError):
                        logger.error(
                            "%s not in self.active_is1_addresses.", msg.is1_address
                        )
                        logger.info("Hopefully this error can be ignored.")
        super().receiveMsg_ChildActorExited(msg, sender)

    def receiveMsg_GetHostInfoMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetHostInfoMsg asking for an updated list of connected hosts"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._update_host_info()

    def _update_host_info(self):
        """Provide the registrar with updated list of hosts."""
        hosts = []
        for _actor_id, is1_address in self.active_is1_addresses.items():
            hosts.append(
                HostObj(
                    host=is1_address.hostname,
                    is_id=is1_address.hostname,
                    transport_technology=TransportTechnology.IS1,
                    description="Instrument with WLAN module",
                    place="unknown",
                    latitude=0,
                    longitude=0,
                    altitude=0,
                    state=2,
                    version="IS1",
                    running_since=datetime(year=1970, month=1, day=1),
                )
            )
        for is1_address in self.is1_addresses:
            hosts.append(
                HostObj(
                    host=is1_address.hostname,
                    is_id=is1_address.hostname,
                    transport_technology=TransportTechnology.IS1,
                    description="Instrument with WLAN module",
                    place="unknown",
                    latitude=0,
                    longitude=0,
                    altitude=0,
                    state=0,
                    version="IS1",
                    running_since=datetime(year=1970, month=1, day=1),
                )
            )
        self.send(self.registrar, HostInfoMsg(hosts=hosts))

    def receiveMsg_RescanMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for rescan command from Registrar"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._scan_is()
