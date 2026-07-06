"""Listening for mDNS multicast messages announcing the existence of new
services (SARAD devices) in the local network.

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import ipaddress
import socket
import threading
import time

from regserver.actor_messages import KillMsg, SetupLanDeviceMsg
from regserver.config import config, lan_backend_config
from regserver.helpers import get_actor, sarad_protocol, short_id
from regserver.logger import logger
from regserver.shutdown import system_shutdown
from sarad.global_helpers import decode_instr_id  # type: ignore
from thespian.actors import ActorSystem  # type: ignore
from zeroconf import (BadTypeInNameException, NonUniqueNameException,
                      ServiceBrowser, ServiceListener, Zeroconf)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    @staticmethod
    def device_id(name):
        """Convert mDNS name into a proper device_id/actor_id"""
        mdns_type = name.split(".", 2)[-1]
        if mdns_type == lan_backend_config["TYPE"]:
            return f"{short_id(name, check=False)}.{sarad_protocol(name)}.mdns"
        return name

    @staticmethod
    def get_host_addr(info=None):
        """Helper function to get the host name from mdns service information"""
        if info is None:
            logger.error("info in Zeroconf message is None")
            return None
        try:
            addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            return socket.gethostbyaddr(addr_ip)[0]
        except socket.herror:
            logger.error("No network connection.")
        except Exception:  # pylint: disable=broad-except
            logger.critical("Fatal error -> Emergency shutdown")
            system_shutdown()
        return None

    def convert_properties(self, zc, type_, name):
        # pylint: disable=invalid-name
        """Helper function to convert mdns service information
        to the desired dictionary"""
        info = zc.get_service_info(
            type_, name, timeout=lan_backend_config["MDNS_TIMEOUT"]
        )
        if not info or not name:
            logger.error(
                "Cannot convert properties. `info` in Zeroconf message is None"
            )
            return None
        properties = info.properties
        if properties is not None:
            model = properties.get(b"MODEL_ENC", b"")
            try:
                model = model.decode("utf-8")
            except AttributeError:
                logger.warning("MODEL_ENC in Zeroconf message is None")
                model = ""
        else:
            logger.error("Service info contains no properties")
            return None
        try:
            occupied = bool(properties.get(b"OCCUPIED").decode("utf-8") == "True")
        except AttributeError:
            logger.warning("OCCUPIED in Zeroconf message is None")
            occupied = False
        serial_short = properties.get(b"SERIAL_SHORT")
        if serial_short is None:
            logger.error("serial_short is None")
            return None
        instr_id = serial_short.decode("utf-8").split(".")[0]
        sarad_protocol_ = serial_short.decode("utf-8").split(".")[1]
        ids = decode_instr_id(instr_id)
        if ids is None:
            logger.error("ids is None")
            return None
        if len(ids) != 3:
            logger.error("len(ids) != 3")
            return None
        addr = ""
        try:
            addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            addr = socket.gethostbyaddr(addr_ip)[0]
        except socket.herror:
            logger.error("No network connection.")
            addr_ip = info.addresses[0]
        except Exception:  # pylint: disable=broad-except
            logger.critical("Fatal error")
            system_shutdown()
        return {
            self.device_id(name): {
                "Identification": {
                    "Name": model,
                    "Family": ids[0],
                    "Type": ids[1],
                    "Serial number": ids[2],
                    "Host": addr,
                    "Protocol": sarad_protocol_,
                },
                "Remote": {
                    "Address": addr_ip,
                    "Name": name,
                    "API port": info.port,
                    "Device Id": properties.get(b"DEVICE_ID", b"").decode("utf-8"),
                },
                "Reservation": {
                    "Active": occupied,
                },
            }
        }

    def _get_hostname(self, zc, type_, name):
        # pylint: disable=invalid-name
        try:
            info = zc.get_service_info(
                type_, name, timeout=lan_backend_config["MDNS_TIMEOUT"]
            )
        except (OSError, BadTypeInNameException, NonUniqueNameException):
            logger.error("An error occurred in zc.get_service_info().")
        hostname = self.get_host_addr(info)
        if hostname is None:
            logger.warning("Cannot handle Zeroconf service with info=%s", info)
        return hostname

    def __init__(self, registrar_actor):
        """
        Initialize a mdns Listener for a specific device group
        """
        logger.info("Init mDNS listener")
        self.registrar = registrar_actor
        self.zeroconf = None
        self.browser = None
        self.host_creator_actor = get_actor(self.registrar, "host_creator")
        self.last_activity = time.time()
        self.lock = threading.Lock()

    def _update_activity(self):
        with self.lock:
            self.last_activity = time.time()

    def start(self, service_type):
        """Start the ZeroConf listener thread"""
        if not lan_backend_config.get("HOSTS_WHITELIST", []):
            try:
                self.zeroconf = Zeroconf(
                    ip_version=lan_backend_config["IP_VERSION"],
                    interfaces=[config["MY_IP"], "127.0.0.1"],
                )
                self.browser = ServiceBrowser(self.zeroconf, service_type, self)
            except (OSError, BadTypeInNameException, NonUniqueNameException):
                logger.critical(
                    "An error occurred while initializing the ServiceBrowser."
                )
                system_shutdown()
        self._update_activity()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a new service
        representing a device is being detected"""
        logger.debug("[Add] Service %s of type %s", name, type_)
        hostname = self._get_hostname(zc, type_, name)
        data = self.convert_properties(zc, type_, name)
        logger.debug("[Add] Service %s of type %s with data %s", name, type_, data)
        if data is not None and hostname is not None:
            first_key = next(iter(data))
            if data[first_key].get("Remote", False):
                if data[first_key]["Remote"].get("API port"):
                    api_port = data[first_key]["Remote"]["API port"]
                else:
                    api_port = 0
            else:
                api_port = 0
            try:
                msg = SetupLanDeviceMsg(
                    host=hostname, port=api_port, scan_interval=0, device_status=data
                )
                ActorSystem().tell(self.host_creator_actor, msg)
            except OSError:
                logger.critical(
                    "OSError in ActorSystem().tell. SetupLanDeviceMsg: %s", msg
                )
        else:
            logger.error(
                "add_service was called with bad parameters: %s, %s, %s",
                zc,
                type_,
                name,
            )
        self._update_activity()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a service
        representing a device is being updated"""
        logger.debug("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        logger.info("[Del] Service %s of type %s", name, type_)
        info = zc.get_service_info(
            type_, name, timeout=int(lan_backend_config["MDNS_TIMEOUT"])
        )
        logger.debug("[Del] Info: %s", info)
        device_id = self.device_id(name)
        device_actor = get_actor(self.registrar, device_id)
        if device_actor is None:
            logger.debug("Actor %s does not exist.", device_id)
        else:
            logger.debug("Kill device actor %s", device_id)
            ActorSystem().tell(device_actor, KillMsg())
        self._update_activity()

    def shutdown(self) -> None:
        """Cleanup"""
        if self.browser is not None:
            self.browser.cancel()
        if self.zeroconf is not None:
            self.zeroconf.close()
        logger.info("Zeroconf listener closed")

    def get_last_activity(self) -> float:
        """Return the timestamp of last activity"""
        with self.lock:
            return self.last_activity


class ZeroconfWatchdog:
    """Watchdog for threaded Zeroconf Listener"""

    def __init__(self, registrar_actor, service_type: str, timeout_seconds: int = 60):
        self.service_type = service_type
        self.timeout = timeout_seconds
        self.listener = None
        self.running = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.registrar = registrar_actor

    def start(self):
        """Start or restart the Zeroconf Listener"""
        self.running = True
        self._bootstrap_zeroconf()
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def restart(self):
        self._cleanup()
        self._bootstrap_zeroconf()

    def _bootstrap_zeroconf(self):
        logger.debug("Start Zeroconf listener...")
        self.listener = MdnsListener(self.registrar)
        # Startet das Listening für den spezifischen Service-Typ
        self.listener.start(self.service_type)

    def _cleanup(self):
        logger.debug("Clean up old instances...")
        if self.listener:
            try:
                self.listener.shutdown()
            except Exception as e:
                logger.error("Error closing service listener: %s", e)
        self.listener = None

    def _monitor_loop(self):
        while self.running:
            time.sleep(1)  # Überprüfungsintervall
            if not self.listener:
                continue
            time_since_last_activity = time.time() - self.listener.get_last_activity()
            # Wenn das Timeout überschritten wurde, starten wir neu
            if time_since_last_activity > self.timeout:
                logger.warning(
                    "Zeroconf watchdog: No activity since %s s! Restart listener...",
                    int(time_since_last_activity),
                )
                self.restart()

    def stop(self):
        """Stop the Zeroconf Listener"""
        self.running = False
        self._cleanup()
