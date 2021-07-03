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

import hashids  # type: ignore
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.modules.rfc2217.rfc2217_actor import Rfc2217Actor
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

logger.debug("%s -> %s", __package__, __file__)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    __lock = threading.Lock()

    @staticmethod
    def convert_properties(info=None, name=""):
        """Helper function to convert mdns service information
        to the desired yaml format"""
        if not info or not name:
            return None
        properties = info.properties
        if properties is not None:
            _model = properties.get(b"MODEL_ENC", None)
            if _model is None:
                return None
        _model = _model.decode("utf-8")
        _serial_short = properties.get(b"SERIAL_SHORT", None)
        if _serial_short is None:
            return None
        _device_id = _serial_short.decode("utf-8").split(".")[0]
        _sarad_protocol = _serial_short.decode("utf-8").split(".")[1]
        hids = hashids.Hashids()
        _ids = hids.decode(_device_id)
        if _ids is None:
            return None
        if not (len(_ids) == 3) or not info.port:
            return None
        _addr = ""
        try:
            _addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            _addr = socket.gethostbyaddr(_addr_ip)[0]
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
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
        logger.debug(out)
        return json.dumps(out)

    @staticmethod
    def get_ip():
        """Find my own IP address"""
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            test_socket.connect(("10.255.255.255", 1))
            ip_address = test_socket.getsockname()[0]
        except Exception:  # pylint: disable=broad-except
            ip_address = "127.0.0.1"
        finally:
            test_socket.close()
        logger.debug("My IP address is %s", ip_address)
        return ip_address

    def __init__(self, _type):
        """
        Initialize a mdns Listener for a specific device group
        """
        with self.__lock:
            self.__type: str = type
            self.__zeroconf = Zeroconf(
                ip_version=config["ip_version"], interfaces=[self.get_ip(), "127.0.0.1"]
            )
            self.__browser = ServiceBrowser(self.__zeroconf, _type, self)
            self.__dev_folder: str = config["DEV_FOLDER"] + os.path.sep
            if not os.path.exists(self.__dev_folder):
                os.makedirs(self.__dev_folder)
            logger.debug("Output to: %s", self.__dev_folder)
        # Clean __dev_folder for a fresh start
        self.remove_all_services()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a new service
        representing a device is being detected"""
        with self.__lock:
            logger.info("[Add] Found service %s of type %s", name, type_)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            if info is not None:
                logger.info("[Add] %s", info.properties)
                # Take the first 3 elements to form a short_name
                short_name = ".".join(name.split(".", 3)[:-1])
                # If an actor already exists, this will return
                # the address of the excisting one, else it will create a new one.
                this_actor = ActorSystem().createActor(
                    Rfc2217Actor, globalName=short_name
                )
                data = self.convert_properties(name=name, info=info)
                msg = {"CMD": "SETUP", "PAR": data}
                logger.debug("Ask to setup the device actor with %s...", msg)
                setup_return = ActorSystem().ask(this_actor, msg)
                if not setup_return["ERROR_CODE"] in (
                    RETURN_MESSAGES["OK"]["ERROR_CODE"],
                    RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
                ):
                    logger.critical("Adding a new service failed. Kill device actor.")
                    ActorSystem().tell(this_actor, ActorExitRequest())

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=C0103
        """Hook, being called when a service
        representing a device is being updated"""
        logger.info("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        with self.__lock:
            logger.info("[Del] Service %s of type %s", name, type_)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            dev_file = fr"{self.__dev_folder}{name}"
            logger.debug("[Del] Info: %s", info)
            if os.path.exists(dev_file):
                os.remove(dev_file)
            this_actor = ActorSystem().createActor(Rfc2217Actor, globalName=name)
            logger.debug("Ask to kill the device actor...")
            kill_return = ActorSystem().ask(this_actor, ActorExitRequest())
            if not kill_return["ERROR_CODE"] == RETURN_MESSAGES["OK"]["ERROR_CODE"]:
                logger.critical("Killing the device actor failed.")

    def remove_all_services(self) -> None:
        """Kill all device actors and remove all device files from device folder."""
        with self.__lock:
            if os.path.exists(self.__dev_folder):
                for root, _, files in os.walk(self.__dev_folder):
                    for name in files:
                        if "_rfc2217" in name:
                            dev_file = os.path.join(root, name)
                            logger.debug("[Del] Removed %s", name)
                            os.remove(dev_file)
                            this_actor = ActorSystem().createActor(
                                Rfc2217Actor, globalName=name
                            )
                            logger.debug("Ask to kill the device actor...")
                            kill_return = ActorSystem().ask(
                                this_actor, ActorExitRequest()
                            )
                            if (
                                not kill_return["ERROR_CODE"]
                                == RETURN_MESSAGES["OK"]["ERROR_CODE"]
                            ):
                                logger.critical("Killing the device actor failed.")
