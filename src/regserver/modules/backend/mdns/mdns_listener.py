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
from datetime import timedelta

from regserver.actor_messages import (ActorCreatedMsg, CreateActorMsg, KillMsg,
                                      SetDeviceStatusMsg, SetupHostActorMsg)
from regserver.config import config, mdns_backend_config
from regserver.helpers import (get_actor, sarad_protocol, short_id,
                               transport_technology)
from regserver.hostname_functions import compare_hostnames
from regserver.logger import logger
from regserver.modules.backend.mdns.host_actor import HostActor
from regserver.shutdown import system_shutdown
from sarad.global_helpers import decode_instr_id  # type: ignore
from thespian.actors import ActorSystem  # type: ignore
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    @staticmethod
    def device_id(name):
        """Convert mDNS name into a proper device_id/actor_id"""
        if transport_technology(name) == mdns_backend_config["TYPE"]:
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
            type_, name, timeout=mdns_backend_config["MDNS_TIMEOUT"]
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

    def _get_host_actor(self, zc, type_, name):
        # pylint: disable=invalid-name
        info = zc.get_service_info(
            type_, name, timeout=mdns_backend_config["MDNS_TIMEOUT"]
        )
        hostname = self.get_host_addr(info)
        if hostname is None:
            logger.warning("Cannot handle Zeroconf service with info=%s", info)
            host_actor = None
            return host_actor, hostname
        host_actor = get_actor(self.registrar, hostname)
        return host_actor, hostname

    def __init__(self, registrar_actor):
        """
        Initialize a mdns Listener for a specific device group
        """
        logger.info("Init mDNS listener")
        self.registrar = registrar_actor
        self.zeroconf = None
        self.browser = None
        self.hosts_whitelist = mdns_backend_config.get("HOSTS_WHITELIST", [])
        for host in self.hosts_whitelist:
            hostname = host[0]
            logger.debug("Ask Registrar to create Host Actor %s", hostname)
            with ActorSystem().private() as add_host:
                try:
                    reply = add_host.ask(
                        self.registrar,
                        CreateActorMsg(HostActor, hostname),
                        timeout=timedelta(seconds=20),
                    )
                except ConnectionResetError as exception:
                    logger.debug(exception)
                    reply = None
            if not isinstance(reply, ActorCreatedMsg):
                logger.critical("Got %s instead of ActorCreateMsg", reply)
                logger.critical("Check `hosts_whitelist` in `config.toml`!")
                logger.critical("-> Stop and shutdown system")
                system_shutdown()
            elif reply.actor_address is None:
                return
            else:
                host_actor = reply.actor_address
                ActorSystem().tell(
                    host_actor,
                    SetupHostActorMsg(
                        host=hostname,
                        port=host[1],
                        scan_interval=mdns_backend_config["SCAN_INTERVAL"],
                    ),
                )

    def start(self, service_type):
        """Start the ZeroConf listener thread"""
        if not self.hosts_whitelist:
            self.zeroconf = Zeroconf(
                ip_version=mdns_backend_config["IP_VERSION"],
                interfaces=[config["MY_IP"], "127.0.0.1"],
            )
            self.browser = ServiceBrowser(self.zeroconf, service_type, self)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a new service
        representing a device is being detected"""
        logger.info("[Add] Service %s of type %s", name, type_)
        host_actor, hostname = self._get_host_actor(zc, type_, name)
        logger.debug("hostname: %s, host_actor: %s", hostname, host_actor)
        if hostname is None:
            return
        my_hostname = config["MY_HOSTNAME"]
        logger.debug("Host to add: %s", hostname)
        logger.debug("My hostname: %s", my_hostname)
        hosts_blacklist = mdns_backend_config.get("HOSTS_BLACKLIST", [])
        if (
            (host_actor is None)
            and (not compare_hostnames(my_hostname, hostname))
            and (hostname not in hosts_blacklist)
        ):
            logger.debug("Ask Registrar to create Host Actor %s", hostname)
            with ActorSystem().private() as create_host:
                try:
                    reply = create_host.ask(
                        self.registrar,
                        CreateActorMsg(HostActor, hostname),
                        timeout=timedelta(seconds=20),
                    )
                except ConnectionResetError as exception:
                    logger.debug(exception)
                    reply = None
            if not isinstance(reply, ActorCreatedMsg):
                logger.critical("Got %s instead of ActorCreateMsg", reply)
                logger.critical("-> Stop and shutdown system")
                system_shutdown()
            elif reply.actor_address is None:
                return
            else:
                host_actor = reply.actor_address
        data = self.convert_properties(zc, type_, name)
        if (data is not None) and (host_actor is not None):
            first_key = next(iter(data))
            if data[first_key].get("Remote", False):
                if data[first_key]["Remote"].get("API port"):
                    api_port = data[first_key]["Remote"]["API port"]
                else:
                    api_port = 0
            else:
                api_port = 0
            ActorSystem().tell(
                host_actor,
                SetupHostActorMsg(host=hostname, port=api_port, scan_interval=0),
            )
            logger.debug("Tell Host Actor to setup device actor with %s", data)
            ActorSystem().tell(host_actor, SetDeviceStatusMsg(data))
        elif data is None:
            logger.error(
                "add_service was called with bad parameters: %s, %s, %s",
                zc,
                type_,
                name,
            )

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a service
        representing a device is being updated"""
        logger.info("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        logger.info("[Del] Service %s of type %s", name, type_)
        info = zc.get_service_info(
            type_, name, timeout=int(mdns_backend_config["MDNS_TIMEOUT"])
        )
        logger.debug("[Del] Info: %s", info)
        device_id = self.device_id(name)
        device_actor = get_actor(self.registrar, device_id)
        if device_actor is None:
            logger.debug("Actor %s does not exist.", device_id)
        else:
            logger.debug("Kill device actor %s", device_id)
            ActorSystem().tell(device_actor, KillMsg())

    def shutdown(self) -> None:
        """Cleanup"""
        if self.browser is not None:
            self.browser.cancel()
        if self.zeroconf is not None:
            self.zeroconf.close()
        logger.info("Zeroconf listener closed")
