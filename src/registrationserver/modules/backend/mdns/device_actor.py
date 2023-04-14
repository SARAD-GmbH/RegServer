"""Device actor for socket communication in the backend

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""
from datetime import timedelta
from threading import Thread

import requests
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, ReservationStatusMsg,
                                               Status)
from registrationserver.config import config
from registrationserver.helpers import sanitize_hn
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from registrationserver.shutdown import system_shutdown
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# logger.debug("%s -> %s", __package__, __file__)

CMD_CYCLE_TIMEOUT = 1
DEFAULT_TIMEOUT = 5  # seconds
RETRY = 0  # number of retries for HTTP requests
UPDATE_INTERVAL = 3  # in seconds


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


class DeviceActor(DeviceBaseActor):
    # pylint: disable=too-many-instance-attributes
    """Actor for dealing with raw socket connections between App and IS2"""

    @overrides
    def __init__(self):
        super().__init__()
        self._is_host = None
        self._api_port = None
        self.device_id = None
        self.base_url = ""
        self.occupied = False  # Is device occupied by somebody else?
        self.http = None
        self.response = None  # Response from http request
        self.success = Status.OK

    def _http_get_function(self, endpoint, params=None):
        try:
            resp = self.http.get(endpoint, params=params)
            self.response = resp.json()
            self.success = Status.OK
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            self.success = Status.IS_NOT_FOUND
            self.send(self.myAddress, KillMsg())
        else:
            if (self.response is None) or (self.response == {}):
                logger.error("%s not available", self.device_id)
                self.success = Status.NOT_FOUND
                self.send(self.myAddress, KillMsg())
            else:
                device_desc = self.response.get(self.device_id)
                if (device_desc is None) or (device_desc == {}):
                    logger.error("%s not available", self.device_id)
                    self.success = Status.NOT_FOUND
                    self.send(self.myAddress, KillMsg())
                else:
                    ident = device_desc.get("Identification")
                    if ident is None:
                        logger.error("No Identification section available.")
                        self.success = Status.NOT_FOUND
                        self.send(self.myAddress, KillMsg())

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

    def receiveMsg_SetupMdnsActorMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for SetupMdnsActorMsg containing setup information
        that is special to the mDNS device actor"""
        self._is_host = msg.is_host
        self._api_port = msg.api_port
        self.device_id = msg.device_id
        self.base_url = f"http://{self._is_host}:{self._api_port}"
        self._http_get_function(f"{self.base_url}/list/{self.device_id}/")
        if self.success == Status.OK:
            self.wakeupAfter(timedelta(seconds=UPDATE_INTERVAL), payload="update")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handle WakeupMessage for regular updates"""
        if self.occupied and (msg.payload == "update"):
            try:
                logger.debug(
                    "Check whether %s still occupies %s.",
                    self.device_status["Reservation"]["Host"],
                    self.device_id,
                )
            except KeyError:
                logger.error("%s occupied, but we don't know by whom", self.device_id)
            self._http_get_function(f"{self.base_url}/list/{self.device_id}/")
            if self.success == Status.OK:
                device_desc = self.response[self.device_id]
                reservation = device_desc.get("Reservation")
                if reservation is None:
                    active = False
                else:
                    active = reservation.get("Active", False)
                self.device_status["Reservation"]["Active"] = active
                logger.debug("%s reservation active: %s", self.device_id, active)
                self._publish_status_change()
                if not active:
                    self.occupied = False
        self.wakeupAfter(timedelta(seconds=UPDATE_INTERVAL), payload="update")

    @overrides
    def _request_free_at_is(self):
        self._http_get_function(f"{self.base_url}/list/{self.device_id}/free")
        if self.success == Status.OK:
            success = Status(self.response.get("Error code", 98))
        else:
            success = self.success
        self._handle_free_reply_from_is(success)

    @overrides
    def _request_reserve_at_is(self):
        """Reserve the requested instrument at the instrument server."""
        app = self.reserve_device_msg.app
        user = self.reserve_device_msg.user
        host = sanitize_hn(self.reserve_device_msg.host)
        who = f"{app} - {user} - {host}"
        logger.debug("Try to reserve %s for %s.", self.device_id, who)
        self._http_get_function(
            f"{self.base_url}/list/{self.device_id}/reserve",
            params={"who": who},
        )
        if self.success == Status.OK:
            success = Status(self.response.get("Error code", 98))
        else:
            success = self.success
        if success == Status.OCCUPIED:
            self.occupied = True
        else:
            self.occupied = False
        if success in (Status.OK, Status.OCCUPIED):
            self.device_status["Reservation"] = self.response[self.device_id].get(
                "Reservation", {}
            )
        self._handle_reserve_reply_from_is(success)

    @overrides
    def _handle_reserve_reply_from_is(self, success: Status):
        """Forward the reservation state from the Instrument Server to the REST API."""
        self.return_message = ReservationStatusMsg(
            instr_id=self.instr_id, status=success
        )
        if success in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            logger.error(
                "Reservation failed with %s. Removing device from list.", success
            )
            self.send(self.myAddress, KillMsg())
        elif success == Status.ERROR:
            logger.critical("%s during reservation", success)
            system_shutdown()
        self._publish_status_change()
        self._send_reservation_status_msg()

    @overrides
    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        """Handler for SetDeviceStatusMsg initialising the device status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.occupied = False
        self.device_status = msg.device_status
        logger.debug("Device status: %s", self.device_status)
        self._http_get_function(f"{self.base_url}/list/{self.device_id}/")
        if self.success == Status.OK:
            device_desc = self.response[self.device_id]
            logger.debug("device_desc: %s", device_desc)
            ident = self.device_status["Identification"]
            remote_ident = device_desc["Identification"]
            ident["Origin"] = remote_ident.get("Origin")
            ident["Firmware version"] = remote_ident.get("Firmware version")
            self.device_status["Identification"] = ident
            reservation = device_desc.get("Reservation")
            if reservation is None:
                logger.debug(
                    "API reply from % has no Reservation section", self.device_id
                )
                self.device_status.pop("Reservation", None)
            else:
                if reservation.get("Active", False):
                    using_host = sanitize_hn(reservation.get("Host", ""))
                    my_host = sanitize_hn(config["MY_HOSTNAME"])
                    if using_host == my_host:
                        logger.debug("Occupied by me.")
                    else:
                        logger.debug("Occupied by somebody else.")
                        logger.debug("Using host: %s, my host: %s", using_host, my_host)
                        self.occupied = True
                        reservation.pop("IP", None)
                        reservation.pop("Port", None)
                    self.device_status["Reservation"] = reservation
                else:
                    self.device_status.pop("Reservation", None)
            self._publish_status_change()
        else:
            super().receiveMsg_SetDeviceStatusMsg(msg, sender)
