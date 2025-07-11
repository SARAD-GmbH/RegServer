"""Actor representing an instrument server host in the LAN backend

:Created:
    2022-10-14

:Authors:
    | Michael Strey <strey@sarad.de>

"""

import time
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Thread

import requests  # type: ignore
from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorCreatedMsg, ActorType, HostInfoMsg,
                                      HostObj, KillMsg, SetDeviceStatusMsg,
                                      SetupMdnsActorMsg, Status,
                                      TransportTechnology)
from regserver.base_actor import BaseActor
from regserver.helpers import sarad_protocol, short_id, transport_technology
from regserver.logger import logger
from regserver.modules.backend.mdns.device_actor import DeviceActor
from requests.adapters import HTTPAdapter  # type: ignore
from urllib3.util.retry import Retry  # type: ignore

PING_INTERVAL = 5  # in minutes
DEFAULT_TIMEOUT = 8  # seconds
RETRY = 0  # number of retries for HTTP requests


class TimeoutHTTPAdapter(HTTPAdapter):
    """Class to unify timeouts for all requests"""

    @overrides
    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    @overrides
    def send(
        self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None
    ):  # pylint: disable=too-many-arguments, too-many-positional-arguments
        if timeout is None:
            timeout = self.timeout
        return super().send(request, stream, timeout, verify, cert, proxies)


class HostActor(BaseActor):
    """Class representing a host providing at least one SARAD instrument."""

    @staticmethod
    def mdns_id(local_id):
        """Convert device_id from local name into a proper mDNS device_id/actor_id"""
        if transport_technology(local_id) != TransportTechnology.LAN:
            return f"{short_id(local_id, check=False)}.{sarad_protocol(local_id)}.mdns"
        return local_id

    @overrides
    def __init__(self):
        super().__init__()
        self.base_url = ""
        self.get_updates = True
        self._virgin = True
        self._asys = None
        self.http = None
        self.scan_interval = 0
        self.host = HostObj(
            host="",
            is_id="",
            transport_technology=TransportTechnology.LAN,
            description="",
            place="",
            latitude=0,
            longitude=0,
            altitude=0,
            state=1,
            version="",
            running_since=datetime(year=1970, month=1, day=1),
        )
        self.port = 0
        self.ping_thread = Thread(target=self._ping_function, daemon=True)
        self.scan_thread = Thread(target=self._scan_function, daemon=True)
        self.rescan_thread = Thread(target=self._rescan_function, daemon=True)
        self.shutdown_thread = Thread(target=self._shutdown_function, daemon=True)
        self.get_host_info_thread = Thread(
            target=self._get_host_info_function, daemon=True
        )
        self.actor_type = ActorType.HOST
        self.shutdown_password = ""

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        self.http = requests.Session()
        self.http.hooks["response"] = [
            lambda response, *args, **kwargs: response.raise_for_status()
        ]
        retry_strategy = Retry(
            total=RETRY,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1,
        )
        adapter = TimeoutHTTPAdapter(max_retries=retry_strategy)
        self.http.mount("https://", adapter)
        self.http.mount("http://", adapter)
        self._asys = msg.asys_address
        self._subscribe_to_actor_dict_msg()
        logger.info("Ping %s every %d minutes.", self.my_id, PING_INTERVAL)
        self.wakeupAfter(timedelta(seconds=1), payload="ping")
        super().receiveMsg_SetupMsg(msg, sender)

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        if self.my_id in msg.actor_dict:
            if self._virgin:
                self.send(
                    self._asys,
                    ActorCreatedMsg(
                        self.myAddress,
                        actor_type=self.actor_type,
                        hostname=self.my_id,
                        port=self.port,
                    ),
                )
                self._virgin = False

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)
        if not self.child_actors:
            self.host.state = self.host.state and 1
            self.send(self.registrar, HostInfoMsg([self.host]))

    def receiveMsg_SetupHostActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupHostActorMsg initialising the host status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.scan_interval and not msg.scan_interval:
            logger.info("Stop scanning %s. We can rely on mDNS ", self.base_url)
        self.scan_interval = msg.scan_interval
        self.base_url = f"http://{msg.host}:{msg.port}"
        self.port = msg.port
        if self.scan_interval:
            logger.info("Scan %s every %d seconds", self.base_url, self.scan_interval)
            self.wakeupAfter(timedelta(seconds=1), payload="scan")

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg initialising the device status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        device_id = list(msg.device_status)[0]
        if transport_technology(device_id) == TransportTechnology.LAN:
            self._set_device_status(msg.device_status)

    def receiveMsg_GetHostInfoMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetHostInfoMsg asking to send back a HostInfoMsg."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._get_host_info()

    def _set_device_status(self, device_status):
        device_id = list(device_status)[0]
        for old_device_id in self.actor_dict:
            if (short_id(old_device_id) == short_id(device_id)) and (
                device_id != old_device_id
            ):
                logger.debug(
                    "%s is already represented by %s",
                    short_id(device_id),
                    old_device_id,
                )
                return
        data = device_status[device_id]
        is_host = data["Remote"]["Address"]
        api_port = data["Remote"]["API port"]
        remote_device_id = data["Remote"]["Device Id"]
        if device_id not in self.child_actors:
            device_actor = self._create_actor(DeviceActor, device_id, None)
            self.send(
                device_actor,
                SetupMdnsActorMsg(is_host, api_port, remote_device_id),
            )
            self._get_host_info()
        else:
            device_actor = self.child_actors[device_id]["actor_address"]
        data["State"] = 2
        self.send(device_actor, SetDeviceStatusMsg(data))

    def receiveMsg_RescanMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for RescanMsg causing a re-scan for local instruments at the remote host"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if (msg.host is None) or (msg.host == self.host.host):
            if not self.rescan_thread.is_alive():
                self.rescan_thread = Thread(target=self._rescan_function, daemon=True)
                try:
                    self.rescan_thread.start()
                except RuntimeError:
                    pass

    def _rescan_function(self):
        logger.debug("Send /scan endpoint to REST API of %s", self.my_id)
        try:
            _resp = self.http.post(f"{self.base_url}/hosts/127.0.0.1/scan")
        except Exception:  # pylint: disable=broad-except
            try:
                _resp = self.http.get(f"{self.base_url}/scan")
            except Exception as exception:  # pylint: disable=broad-except
                logger.debug("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                logger.warning("%s in _rescan_function of %s", success, self.my_id)
                self._forward_to_children(KillMsg())

    def receiveMsg_ShutdownMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ShutdownMsg causing a shutdown for restart at the remote host"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.shutdown_password = msg.password
        if (msg.host is None) or (msg.host == self.host.host):
            if not self.shutdown_thread.is_alive():
                self.shutdown_thread = Thread(
                    target=self._shutdown_function, daemon=True
                )
                try:
                    self.shutdown_thread.start()
                except RuntimeError:
                    pass

    def _shutdown_function(self):
        logger.debug("Send /shutdown endpoint to REST API of %s", self.my_id)
        try:
            _resp = self.http.post(
                f"{self.base_url}/hosts/127.0.0.1/restart?password={self.shutdown_password}"
            )
        except Exception as exception:  # pylint: disable=broad-except
            logger.debug("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.warning("%s in _shutdown_function of %s", success, self.my_id)
            self._forward_to_children(KillMsg())

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handle WakeupMessage for regular pings to hosts REST API"""
        logger.debug("WakeupMessage %s received at %s", msg, self.my_id)
        if msg.payload == "ping":
            self._ping()
        elif msg.payload == "scan":
            self._scan()
            if self.scan_interval:
                self.wakeupAfter(timedelta(seconds=self.scan_interval), payload="scan")

    def _ping(self):
        if (not self.ping_thread.is_alive()) and (not self.scan_thread.is_alive()):
            self.ping_thread = Thread(target=self._ping_function, daemon=True)
            try:
                self.ping_thread.start()
            except RuntimeError:
                pass

    def _ping_function(self):
        ping_dict = {}
        try:
            resp = self.http.post(f"{self.base_url}/ping")
            ping_dict = resp.json()
        except Exception as exception1:  # pylint: disable=broad-except
            logger.warning(
                "%s/ping to %s is not responding. %s",
                self.base_url,
                self.my_id,
                exception1,
            )
            try:
                resp = self.http.get(f"{self.base_url}/ping")
                ping_dict = resp.json()
            except Exception as exception2:  # pylint: disable=broad-except
                logger.debug("REST API of IS is not responding. %s", exception2)
                success = Status.IS_NOT_FOUND
                logger.debug("%s in _ping_function of %s", success, self.my_id)
        if ping_dict:
            updated_host = replace(
                self.host,
                version=ping_dict.get("version", self.host.version),
                running_since=datetime.fromisoformat(
                    ping_dict.get(
                        "running_since",
                        self.host.running_since.isoformat(timespec="seconds"),
                    ),
                ),
            )
            self.host = updated_host
            self.send(self.registrar, HostInfoMsg([self.host]))
            if not self.child_actors:
                self._scan()
        else:
            self.host.state = 0
            self._forward_to_children(KillMsg())
            logger.debug("Update host info in _ping_function()")
            self.send(self.registrar, HostInfoMsg([self.host]))
        self.wakeupAfter(timedelta(minutes=PING_INTERVAL), payload="ping")

    def _scan(self):
        self.scan_thread = Thread(target=self._scan_function, daemon=True)
        try:
            self.scan_thread.start()
        except RuntimeError as exception:
            logger.warning(exception)

    def _scan_function(self):
        logger.debug(
            "Scan REST API of %s for new instruments and host info", self.my_id
        )
        while not self.base_url:
            logger.warning("Waiting for base URL")
            time.sleep(0.5)
        try:
            resp = self.http.get(f"{self.base_url}/list")
            device_list = resp.json()
        except Exception as exception:  # pylint: disable=broad-except
            logger.warning("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.warning("%s in _scan_function of %s", success, self.my_id)
            self._forward_to_children(KillMsg())
        else:
            updated_instr_list = []
            if (device_list is None) or (device_list == {}):
                logger.debug(
                    "Instrument list on remote host %s is empty.", self.host.host
                )
            else:
                for device_id, device_status in device_list.items():
                    if transport_technology(device_id) in [
                        TransportTechnology.LOCAL,
                        TransportTechnology.IS1,
                    ]:
                        updated_instr_list.append(short_id(device_id))
                        device_status["Remote"] = {
                            "Address": self.host.host,
                            "API port": self.port,
                            "Device Id": device_id,
                        }
                        device_status["Identification"]["Host"] = self.host.host
                        device_actor_id = self.mdns_id(device_id)
                        if device_actor_id not in self.child_actors:
                            self._set_device_status({device_actor_id: device_status})
            current_instr_list = [short_id(x) for x in self.child_actors]
            for current_instr in current_instr_list:
                if current_instr not in updated_instr_list:
                    logger.debug("@%s, remove %s", self.my_id, current_instr)
                    for device_actor_id, child_actor in self.child_actors.items():
                        if current_instr in device_actor_id:
                            self.send(child_actor["actor_address"], KillMsg())
        logger.debug("Scan of %s finished", self.my_id)

    def _get_host_info(self):
        self.get_host_info_thread = Thread(
            target=self._get_host_info_function, daemon=True
        )
        try:
            self.get_host_info_thread.start()
        except RuntimeError:
            pass

    def _get_host_info_function(self):
        while not self.base_url:
            time.sleep(0.5)
        if self.child_actors:
            host_state = 2  # host online, fully functional
        else:
            host_state = 1  # host online, no instruments connected
        try:
            host_resp = self.http.get(f"{self.base_url}/hosts/127.0.0.1")
            host_info = host_resp.json()
        except Exception as exception:  # pylint: disable=broad-except
            logger.warning("REST API of IS is not responding. %s", exception)
            self._no_host_info(host_state)
        else:
            if (host_info is None) or (host_info == {}):
                logger.debug("No host information available on %s.", self.host.host)
                self._no_host_info(host_state)
            else:
                self._replace_host_info(host_info)
        self.send(self.registrar, HostInfoMsg([self.host]))

    def _no_host_info(self, state):
        self.host = replace(
            self.host,
            host=self.my_id,
            is_id=self.my_id,
            state=state,
            description="No host information retrievable from REST API of this host.",
        )
        ping_dict = {}
        try:
            resp = self.http.post(f"{self.base_url}/ping")
            ping_dict = resp.json()
        except Exception:  # pylint: disable=broad-except
            try:
                resp = self.http.get(f"{self.base_url}/ping")
                ping_dict = resp.json()
            except Exception as exception:  # pylint: disable=broad-except
                logger.debug("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                logger.warning("%s in _no_host_info of %s", success, self.my_id)
        if ping_dict:
            self.host = replace(
                self.host,
                version=ping_dict.get("version", self.host.version),
                running_since=datetime.fromisoformat(
                    ping_dict.get(
                        "running_since",
                        self.host.running_since.isoformat(timespec="seconds"),
                    ),
                ),
            )
        else:
            self.host.state = 0
            self._forward_to_children(KillMsg())
            logger.debug("Update host info in _no_host_info()")
            self.send(self.registrar, HostInfoMsg([self.host]))

    def _replace_host_info(self, host_info: dict):
        if self.child_actors:
            default_state = 2
        else:
            default_state = 1
        default_time = "1970-01-01T00:00:00"
        self.host = replace(
            self.host,
            host=self.my_id,
            is_id=host_info.get("is_id", self.host),
            state=host_info.get("state", default_state),
            description=host_info.get("description", ""),
            place=host_info.get("place", ""),
            latitude=host_info.get("latitude", 0),
            longitude=host_info.get("longitude", 0),
            altitude=host_info.get("altitude", 0),
            version=host_info.get("version", ""),
            running_since=datetime.fromisoformat(
                host_info.get("running_since", default_time)
            ),
        )
