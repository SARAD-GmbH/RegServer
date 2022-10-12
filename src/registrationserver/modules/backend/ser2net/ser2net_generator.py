"""Generation of ser2net device actors from definitions given in the config file.

:Created:
    2022-09-22

:Authors:
    | Michael Strey <strey@sarad.de>
"""
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
from registrationserver.config import (app_folder, config,
                                       ser2net_backend_config)
from registrationserver.helpers import check_message, make_command_msg
from registrationserver.logger import logger
from registrationserver.modules.backend.ser2net.ser2net_actor import \
    Ser2netActor
from sarad.sari import SaradInst  # type: ignore

logger.debug("%s -> %s", __package__, __file__)


class Ser2netGenerator(BaseActor):
    """Checks the config file and adds new SARAD Instruments to the system by
    creating a device actor"""

    SERVERS = ser2net_backend_config

    @staticmethod
    def _get_port_and_id(is_id):
        id_string = is_id.decode("utf-8")
        id_list = id_string.rstrip("\r\n").split("-", 1)
        return {"port": int(id_list[0]), "id": id_list[1]}

    @staticmethod
    def _get_instrument_id(ip_address, port):
        """Build a client socket for the listening ser2net server socket.

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
        self.active_ser2net_servers = {}  # Dict of Ser2net servers with device Actors

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        for ip_address in self.SERVERS:
            port = self.SERVERS[ip_address]
            instr_id = self._get_instrument_id(ip_address, port)
            self._create_and_setup_actor(instr_id, ip_address, port)
        self._subscribe_to_actor_dict_msg()

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        """Handler to exit the redirector actor."""
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        super().receiveMsg_ActorExitRequest(msg, sender)
        self.is1_addresses.extend(self.active_is1_addresses)

    def _create_and_setup_actor(self, instr_id, ip_address, port):
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
            device_actor = self._create_actor(Ser2netActor, actor_id)
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
