"""Actor representing an instrument server host in mDNS backend

:Created:
    2022-10-14

:Authors:
    | Michael Strey <strey@sarad.de>

"""
from datetime import timedelta

import requests
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, SetDeviceStatusMsg,
                                               SetupMdnsActorMsg, Status)
from registrationserver.base_actor import BaseActor
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.device_actor import DeviceActor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PING_INTERVAL = 5  # in minutes
DEFAULT_TIMEOUT = 5  # seconds


class TimeoutHTTPAdapter(HTTPAdapter):
    """Class to unify timeouts for all requests"""

    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


class HostActor(BaseActor):
    """Class representing a host providing at least one SARAD instrument."""

    @overrides
    def __init__(self):
        super().__init__()
        self.on_kill = True
        self._is_host = None
        self._api_port = None
        self.base_url = ""
        self.http = requests.Session()
        assert_status_hook = (
            lambda response, *args, **kwargs: response.raise_for_status()
        )
        self.http.hooks["response"] = [assert_status_hook]
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1,
        )
        adapter = TimeoutHTTPAdapter(max_retries=retry_strategy)
        self.http.mount("https://", adapter)
        self.http.mount("http://", adapter)

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg initialising the device status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        device_id = list(msg.device_status)[0]
        data = msg.device_status[device_id]
        self._is_host = data["Remote"]["Address"]
        self._api_port = data["Remote"]["API port"]
        remote_device_id = data["Remote"]["Device Id"]
        if device_id not in self.child_actors:
            device_actor = self._create_actor(DeviceActor, device_id)
            self.send(
                device_actor,
                SetupMdnsActorMsg(self._is_host, self._api_port, remote_device_id),
            )
        else:
            device_actor = self.child_actors[device_id]["actor_address"]
        self.send(device_actor, SetDeviceStatusMsg(data))
        self._ping()

    def receiveMsg_WakeupMessage(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handle WakeupMessage for regular pings to hosts REST API"""
        self._ping()

    def _ping(self):
        self.base_url = f"http://{self._is_host}:{self._api_port}"
        try:
            _resp = self.http.get(f"{self.base_url}/list/")
        except Exception as exception:  # pylint: disable=broad-except
            logger.debug("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.error("%s: %s", success, self._is_host)
            self.send(self.myAddress, KillMsg())
        else:
            self.wakeupAfter(timedelta(minutes=PING_INTERVAL), payload="ping")
