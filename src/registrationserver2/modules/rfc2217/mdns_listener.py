"""Listening for mDNS multicast messages announcing the existence of new
services (SARAD devices) in the local network.

Created
    2020-09-30

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml:: uml-mdns_listener.puml

"""
import ipaddress
import json
import os
import socket
import threading
import traceback

import hashids  # type: ignore
import registrationserver2
from registrationserver2 import FOLDER_AVAILABLE, FOLDER_HISTORY, theLogger
from registrationserver2.config import config
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.modules.rfc2217.rfc2217_actor import Rfc2217Actor
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

theLogger.info("%s -> %s", __package__, __file__)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    __lock = threading.Lock()

    def __init__(self, _type):
        """
        Initialize a mdns Listener for a specific device group
        """
        with self.__lock:
            self.__type: str = type
            self.__zeroconf = Zeroconf()
            self.__browser = ServiceBrowser(self.__zeroconf, _type, self)
            self.__folder_history: str = FOLDER_HISTORY + os.path.sep
            self.__folder_available: str = FOLDER_AVAILABLE + os.path.sep
            if not os.path.exists(self.__folder_history):
                os.makedirs(self.__folder_history)
            if not os.path.exists(self.__folder_available):
                os.makedirs(self.__folder_available)
            theLogger.debug("Output to: %s", self.__folder_history)
        # Clean __folder_available for a fresh start
        self.remove_all_services()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a new service
        representing a device is being detected"""
        with self.__lock:
            theLogger.info("[Add]:\tFound: Service of type %s. Name: %s", type_, name)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            if info is not None:
                theLogger.info("[Add]:\t%s", info.properties)
            # If an actor already exists, this will return
            # the address of the excisting one, else it will create a new one.
            this_actor = registrationserver2.actor_system.createActor(
                Rfc2217Actor, globalName=name
            )
            data = self.convert_properties(name=name, info=info)
            setup_return = registrationserver2.actor_system.ask(
                this_actor, {"CMD": "SETUP", "PAR": data}
            )
            theLogger.info(setup_return)
            if not (
                setup_return is RETURN_MESSAGES["OK"]
                or setup_return is RETURN_MESSAGES["OK_UPDATED"]
            ):
                registrationserver2.actor_system.tell(this_actor, {"CMD": "KILL"})

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        with self.__lock:
            theLogger.info("[Del]:\tRemoved: Service of type %s. Name: %s", type_, name)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            link = fr"{self.__folder_available}{name}"
            theLogger.debug("[Del]:\tInfo: %s", info)
            if os.path.exists(link):
                os.unlink(link)
            this_actor = registrationserver2.actor_system.createActor(
                Rfc2217Actor, globalName=name
            )
            theLogger.info(
                registrationserver2.actor_system.ask(this_actor, {"CMD": "KILL"})
            )

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=C0103
        """Hook, being called when a service
        representing a device is being updated"""
        with self.__lock:
            theLogger.info("[Update]:\tService of type %s. Name: %s", type_, name)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            if not info:
                return
            theLogger.info("[Update]:\tGot Info: %s", info)
            # If an actor already exists, this will return
            # the address of the excisting one, else it will create a new one.
            this_actor = registrationserver2.actor_system.createActor(
                Rfc2217Actor, globalName=name
            )
            data = self.convert_properties(name=name, info=info)
            setup_return = registrationserver2.actor_system.ask(
                this_actor, {"CMD": "SETUP", "PAR": data}
            )
            theLogger.info(setup_return)
            if not (
                setup_return is RETURN_MESSAGES["OK"]
                or setup_return is RETURN_MESSAGES["OK_UPDATED"]
            ):
                registrationserver2.actor_system.tell(this_actor, {"CMD": "KILL"})

    def remove_all_services(self) -> None:
        """Kill all device actors and remove all links to device file from FOLDER_AVAILABLE."""
        with self.__lock:
            if os.path.exists(self.__folder_available):
                for root, _, files in os.walk(self.__folder_available):
                    for name in files:
                        if "_rfc2217" in name:
                            link = os.path.join(root, name)
                            theLogger.debug("[Del]:\tRemoved: %s", name)
                            os.unlink(link)
                            this_actor = registrationserver2.actor_system.createActor(
                                Rfc2217Actor, globalName=name
                            )
                            theLogger.info(
                                registrationserver2.actor_system.ask(
                                    this_actor, {"CMD": "KILL"}
                                )
                            )

    @staticmethod
    def convert_properties(info=None, name=""):
        """Helper function to convert mdns service information
        to the desired yaml format"""
        if not info or not name:
            return None

        properties = info.properties

        if not properties or not (_model := properties.get(b"MODEL_ENC", None)):
            return None

        _model = _model.decode("utf-8")

        if not (_serial_short := properties.get(b"SERIAL_SHORT", None)):
            return None

        _device_id = _serial_short.decode("utf-8").split(".")[0]
        _sarad_protocol = _serial_short.decode("utf-8").split(".")[1]
        hids = hashids.Hashids()

        if not (_ids := hids.decode(_device_id)):
            return None

        if not (len(_ids) == 3) or not info.port:
            return None

        _addr = ""
        try:
            _addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            _addr = socket.gethostbyaddr(_addr_ip)[0]
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
        out = {
            "Identification": {
                "Name": properties[b"MODEL_ENC"].decode("utf-8"),
                "Family": _ids[0],
                "Type": _ids[1],
                "Serial number": _ids[2],
                "Host": _addr,
                "Protocol": _sarad_protocol,
            },
            "Remote": {"Address": _addr_ip, "Port": info.port, "Name": name},
        }
        theLogger.debug(out)
        return json.dumps(out)
