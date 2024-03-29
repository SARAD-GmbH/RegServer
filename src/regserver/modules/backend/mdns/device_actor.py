"""Device actor for socket communication in the backend

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""
from datetime import timedelta
from enum import Enum
from threading import Thread

import requests
from overrides import overrides  # type: ignore
from regserver.actor_messages import ReservationStatusMsg, Status
from regserver.config import config
from regserver.hostname_functions import compare_hostnames
from regserver.logger import logger
from regserver.modules.device_actor import DeviceBaseActor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CMD_CYCLE_TIMEOUT = 1
DEFAULT_TIMEOUT = 8  # seconds
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


class Purpose(Enum):
    """One item for every possible purpose the HTTP request is be made for."""

    SETUP = 1
    WAKEUP = 2
    RESERVE = 3
    FREE = 4
    STATUS = 5


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
        self.request_thread = Thread(
            target=self._http_get_function,
            kwargs={
                "endpoint": "",
                "params": None,
                "purpose": Purpose.SETUP,
            },
            daemon=True,
        )
        self.next_method = None

    def _http_get_function(self, endpoint="", params=None, purpose=Purpose.SETUP):
        try:
            resp = self.http.get(endpoint, params=params)
            self.response = resp.json()
            self.success = Status.OK
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            self.success = Status.IS_NOT_FOUND
        else:
            if (self.response is None) or (self.response == {}):
                logger.error("%s not available", self.device_id)
                self.success = Status.NOT_FOUND
            else:
                device_desc = self.response.get(self.device_id)
                if (device_desc is None) or (device_desc == {}):
                    logger.error("%s not available", self.device_id)
                    self.success = Status.NOT_FOUND
                else:
                    ident = device_desc.get("Identification")
                    if ident is None:
                        logger.error("No Identification section available.")
                        self.success = Status.NOT_FOUND
        if purpose == Purpose.SETUP:
            self.next_method = self._finish_setup_mdns_actor
        elif purpose == Purpose.WAKEUP:
            self.next_method = self._finish_wakeup
        elif purpose == Purpose.RESERVE:
            self.next_method = self._finish_reserve
        elif purpose == Purpose.FREE:
            self.next_method = self._finish_free
        elif purpose == Purpose.STATUS:
            self.next_method = self._finish_set_device_status

    def _start_thread(self, thread):
        if not self.request_thread.is_alive():
            self.request_thread = thread
            self.request_thread.start()
            self.wakeupAfter(timedelta(seconds=0.5), payload="request")
        else:
            self.wakeupAfter(
                timedelta(seconds=0.5),
                payload=thread,
            )

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

    def receiveMsg_SetupMdnsActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupMdnsActorMsg containing setup information
        that is special to the mDNS device actor"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._is_host = msg.is_host
        self._api_port = msg.api_port
        self.device_id = msg.device_id
        self.base_url = f"http://{self._is_host}:{self._api_port}"
        self._start_thread(
            Thread(
                target=self._http_get_function,
                kwargs={
                    "endpoint": f"{self.base_url}/list/{self.device_id}/",
                    "params": None,
                    "purpose": Purpose.SETUP,
                },
                daemon=True,
            )
        )

    def _finish_setup_mdns_actor(self):
        """Do everything that is required after receiving the reply to the HTTP request."""
        if self.success == Status.OK:
            self.wakeupAfter(timedelta(seconds=UPDATE_INTERVAL), payload="update")
        elif self.success in (Status.NOT_FOUND, Status.IS_NOT_FOUND):
            self._kill_myself()

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handle WakeupMessage for regular updates"""
        if msg.payload == "request":
            if self.next_method is None:
                self.wakeupAfter(timedelta(seconds=0.5), payload=msg.payload)
            else:
                self.next_method()
                self.next_method = None
        elif msg.payload == "update":
            if self.occupied:
                try:
                    logger.debug(
                        "Check whether %s still occupies %s.",
                        self.device_status["Reservation"]["Host"],
                        self.device_id,
                    )
                except KeyError:
                    logger.error(
                        "%s occupied, but we don't know by whom", self.device_id
                    )
                if not self.request_thread.is_alive():
                    self._start_thread(
                        Thread(
                            target=self._http_get_function,
                            kwargs={
                                "endpoint": f"{self.base_url}/list/{self.device_id}/",
                                "params": None,
                                "purpose": Purpose.WAKEUP,
                            },
                            daemon=True,
                        )
                    )
        elif isinstance(msg.payload, Thread):
            self._start_thread(msg.payload)

    def _finish_wakeup(self):
        """Handle WakeupMessage for regular updates"""
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
        elif self.success in (Status.NOT_FOUND, Status.IS_NOT_FOUND):
            self._kill_myself()

    @overrides
    def _request_free_at_is(self):
        self._start_thread(
            Thread(
                target=self._http_get_function,
                kwargs={
                    "endpoint": f"{self.base_url}/list/{self.device_id}/free",
                    "params": None,
                    "purpose": Purpose.FREE,
                },
                daemon=True,
            )
        )

    def _finish_free(self):
        """Handle the reply from remote host for FREE request."""
        if self.success == Status.OK:
            success = Status(self.response.get("Error code", 98))
            self.occupied = False
        else:
            success = self.success
        if self.success in (Status.NOT_FOUND, Status.IS_NOT_FOUND):
            self._kill_myself()
        super()._handle_free_reply_from_is(success)

    @overrides
    def _request_reserve_at_is(self):
        """Reserve the requested instrument at the instrument server."""
        app = self.reserve_device_msg.app
        user = self.reserve_device_msg.user
        host = self.reserve_device_msg.host
        who = f"{app} - {user} - {host}"
        logger.debug("Try to reserve %s for %s.", self.device_id, who)
        self._start_thread(
            Thread(
                target=self._http_get_function,
                kwargs={
                    "endpoint": f"{self.base_url}/list/{self.device_id}/reserve",
                    "params": {"who": who},
                    "purpose": Purpose.RESERVE,
                },
                daemon=True,
            )
        )

    def _finish_reserve(self):
        """Forward the reservation state from the Instrument Server to the REST API."""
        logger.debug("_finish_reserve")
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
        self.return_message = ReservationStatusMsg(
            instr_id=self.instr_id, status=success
        )
        if success in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            logger.error(
                "Reservation failed with %s. Removing device from list.", success
            )
            self._kill_myself()
        elif success == Status.ERROR:
            logger.error("%s during reservation", success)
            self._kill_myself()
        self._send_reservation_status_msg()

    @overrides
    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        super().receiveMsg_SetDeviceStatusMsg(msg, sender)
        if not (self.reserve_lock or self.free_lock):
            self.occupied = False
            if self.device_status:
                self.device_status["Reservation"] = msg.device_status.get("Reservation")
            else:
                self.device_status = msg.device_status
            logger.debug("Device status: %s", self.device_status)
            self._start_thread(
                Thread(
                    target=self._http_get_function,
                    kwargs={
                        "endpoint": f"{self.base_url}/list/{self.device_id}/",
                        "params": None,
                        "purpose": Purpose.STATUS,
                    },
                    daemon=True,
                )
            )

    def _finish_set_device_status(self):
        # pylint: disable=invalid-name
        """Finalize SetDeviceStatusMsg handler after receiving HTTP request."""
        if self.success == Status.OK:
            device_desc = self.response[self.device_id]
            logger.debug("device_desc: %s", device_desc)
            ident = self.device_status["Identification"]
            remote_ident = device_desc["Identification"]
            ident["IS Id"] = remote_ident.get("IS Id")
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
                    using_host = reservation.get("Host", "")
                    if self.reserve_device_msg is not None:
                        my_host = self.reserve_device_msg.host
                    else:
                        my_host = config["MY_HOSTNAME"]
                    if compare_hostnames(using_host, my_host):
                        logger.debug("Occupied by me.")
                    else:
                        logger.debug("Occupied by somebody else.")
                        logger.debug("Using host: %s, my host: %s", using_host, my_host)
                        self.occupied = True
                        reservation.pop("IP", None)
                        reservation.pop("Port", None)
                    self.wakeupAfter(
                        timedelta(seconds=UPDATE_INTERVAL), payload="update"
                    )
                    self.device_status["Reservation"] = reservation
                else:
                    self.device_status.pop("Reservation", None)
            self._publish_status_change()
        else:
            self._kill_myself()
