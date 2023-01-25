"""Actor representing an instrument server host in mDNS backend

:Created:
    2022-10-14

:Authors:
    | Michael Strey <strey@sarad.de>

"""
from datetime import timedelta

import requests
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (ActorCreatedMsg, KillMsg,
                                               SetDeviceStatusMsg,
                                               SetupMdnsActorMsg, Status)
from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.device_actor import DeviceActor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PING_INTERVAL = 5  # in minutes
DEFAULT_TIMEOUT = 5  # seconds
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
    ):
        # pylint: disable=too-many-arguments
        if timeout is None:
            timeout = self.timeout
        return super().send(request, stream, timeout, verify, cert, proxies)


class HostActor(BaseActor):
    """Class representing a host providing at least one SARAD instrument."""

    @overrides
    def __init__(self):
        super().__init__()
        self.on_kill = True
        self.base_url = ""
        self.get_updates = True
        self._virgin = True
        self._asys = None
        self.http = None

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
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
        self.wakeupAfter(timedelta(minutes=PING_INTERVAL), payload="ping")

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        if self.my_id in msg.actor_dict:
            if self._virgin:
                self.send(self._asys, ActorCreatedMsg(self.myAddress))
                self._virgin = False

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg initialising the device status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        device_id = list(msg.device_status)[0]
        data = msg.device_status[device_id]
        is_host = data["Remote"]["Address"]
        api_port = data["Remote"]["API port"]
        self.base_url = f"http://{is_host}:{api_port}"
        remote_device_id = data["Remote"]["Device Id"]
        if self.my_id != config["MY_HOSTNAME"]:
            if device_id not in self.child_actors:
                device_actor = self._create_actor(DeviceActor, device_id, None)
                self.send(
                    device_actor,
                    SetupMdnsActorMsg(is_host, api_port, remote_device_id),
                )
            else:
                device_actor = self.child_actors[device_id]["actor_address"]
            self.send(device_actor, SetDeviceStatusMsg(data))

    def receiveMsg_WakeupMessage(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handle WakeupMessage for regular pings to hosts REST API"""
        self._ping()

    def _ping(self):
        try:
            _resp = self.http.get(f"{self.base_url}/ping/")
        except Exception as exception:  # pylint: disable=broad-except
            logger.debug("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.error("%s: %s", success, self.my_id)
            self.send(self.myAddress, KillMsg())
        else:
            self.wakeupAfter(timedelta(minutes=PING_INTERVAL), payload="ping")
