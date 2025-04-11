"""Device actor for socket communication in the backend

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import socket
from datetime import timedelta
from enum import Enum
from threading import Thread

import requests  # type: ignore
from overrides import overrides  # type: ignore
from regserver.actor_messages import RecentValueMsg, RxBinaryMsg, Status
from regserver.config import config
from regserver.hostname_functions import compare_hostnames
from regserver.logger import logger
from regserver.modules.device_actor import BIN_TIMEOUT, DeviceBaseActor
from requests.adapters import HTTPAdapter  # type: ignore
from sarad.instrument import Gps
from urllib3.util.retry import Retry  # type: ignore

DEFAULT_TIMEOUT = 20  # seconds
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
        # pylint: disable=too-many-arguments, too-many-positional-arguments
        if timeout is None:
            timeout = self.timeout
        return super().send(request, stream, timeout, verify, cert, proxies)


class Purpose(Enum):
    """One item for every possible purpose the HTTP request is be made for."""

    GENERAL = 0
    SETUP = 1
    UPDATE = 2
    RESERVE = 3
    FREE = 4
    STATUS = 5
    VALUE = 6
    SET_RTC = 7
    MONITOR_START = 8
    MONITOR_STOP = 9


class DeviceActor(DeviceBaseActor):
    # pylint: disable=too-many-instance-attributes
    """Actor for dealing with raw socket connections between App and IS2"""

    @overrides
    def __init__(self):
        super().__init__()
        self._is_host = ""
        self._api_port = 0
        self.device_id = ""
        self.base_url = ""
        self.occupied = False  # Is device occupied by somebody else?
        self.http = requests.Session()
        self.response: dict = {}  # Response from http request
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
        self._client_socket = None

    def _http_get_function(self, endpoint="", params=None, purpose=Purpose.SETUP):
        try:
            resp = self.http.get(endpoint, params=params)
            self.response = resp.json()
            self.success = Status.OK
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            self.response = {}
            self.success = Status.IS_NOT_FOUND
        else:
            if not self.response:
                logger.error("%s not available", self.device_id)
                self.success = Status.NOT_FOUND
            elif purpose in [Purpose.RESERVE, Purpose.SETUP, Purpose.FREE]:
                device_desc = self.response.get(self.device_id)
                if (device_desc is None) or (device_desc == {}):
                    logger.error("%s not available", self.device_id)
                    self.success = Status.NOT_FOUND
                else:
                    ident = device_desc.get("Identification")
                    if ident is None:
                        logger.error("No Identification section available.")
                        self.success = Status.NOT_FOUND
        self._handle_http_reply(purpose)

    def _http_post_function(self, endpoint="", params=None, purpose=Purpose.GENERAL):
        try:
            resp = self.http.post(endpoint, params=params)
            self.response = resp.json()
            self.success = Status.OK
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            self.response = {}
            self.success = Status.NOT_FOUND
        else:
            if not self.response:
                logger.error("%s not available", self.device_id)
                self.success = Status.NOT_FOUND
        self._handle_http_reply(purpose)

    def _handle_http_reply(self, purpose: Purpose):
        # pylint: disable=too-many-branches
        if purpose == Purpose.SETUP:
            self._finish_setup_mdns_actor()
        elif purpose == Purpose.UPDATE:
            self._finish_update()
        elif purpose == Purpose.RESERVE:
            self._finish_reserve()
        elif purpose == Purpose.FREE:
            self._finish_free()
        elif purpose == Purpose.VALUE:
            logger.debug("Target responded: %s", self.response)
            if self.success == Status.OK:
                error_code = self.response.get("Error code", 0)
                if error_code:
                    answer = RecentValueMsg(
                        status=Status(error_code),
                        instr_id=self.instr_id,
                    )
                else:
                    if self.response.get("GPS", False):
                        gps = Gps(
                            valid=self.response["GPS"]["Valid"],
                            latitude=self.response["GPS"]["Latitude"],
                            longitude=self.response["GPS"]["Longitude"],
                            altitude=self.response["GPS"]["Altitude"],
                            deviation=self.response["GPS"]["Deviation"],
                        )
                    else:
                        gps = None
                    answer = RecentValueMsg(
                        status=self.success,
                        instr_id=self.instr_id,
                        component_name=self.response.get("Component name", ""),
                        sensor_name=self.response.get("Sensor name", ""),
                        measurand_name=self.response.get("Measurand name", ""),
                        measurand=self.response.get("Measurand", ""),
                        operator=self.response.get("Operator", ""),
                        value=self.response.get("Value", 0),
                        unit=self.response.get("Unit", ""),
                        timestamp=self.response.get("Timestamp", 0),
                        utc_offset=self.response.get("UTC offset", 0),
                        sample_interval=self.response.get("Sample interval", 0),
                        gps=gps,
                    )
            else:
                answer = RecentValueMsg(
                    status=self.success,
                    instr_id=self.instr_id,
                )
            self._handle_recent_value_reply_from_is(answer)
        elif purpose == Purpose.STATUS:
            logger.debug(
                "_finish_set_device_status called from SetDeviceStatus at %s",
                self.device_id,
            )
            self._finish_set_device_status({})
        elif purpose == Purpose.SET_RTC:
            logger.info("Target responded to Set-RTC request: %s", self.response)
            if self.success == Status.OK:
                error_code = self.response.get("Error code", 98)
            else:
                error_code = self.success
            self._handle_set_rtc_reply_from_is(
                status=Status(error_code),
                confirm=True,
                utc_offset=self.response.get("UTC offset", -13),
                wait=self.response.get("Wait", 0),
            )
        elif purpose == Purpose.MONITOR_START:
            logger.info(
                "Target responded to Start-Monitoring request: %s", self.response
            )
            if self.success == Status.OK:
                error_code = self.response.get("Error code", 98)
            else:
                error_code = self.success
            self._handle_start_monitoring_reply_from_is(
                status=Status(error_code),
                confirm=True,
                offset=timedelta(seconds=self.response.get("Offset", 0)),
            )
        elif purpose == Purpose.MONITOR_STOP:
            logger.info(
                "Target responded to Stop-Monitoring request: %s", self.response
            )
            if self.success == Status.OK:
                error_code = self.response.get("Error code", 98)
            else:
                error_code = self.success
            self._handle_stop_monitoring_reply_from_is(status=Status(error_code))

    def _start_thread(self, thread):
        if not self.request_thread.is_alive():
            self.request_thread = thread
            self.request_thread.start()
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
            logger.debug(
                "_finish_set_device_status called from _finish_setup_mdns_actor at %s",
                self.device_id,
            )
            self._finish_set_device_status({})
        elif self.success in (Status.NOT_FOUND, Status.IS_NOT_FOUND):
            logger.info(
                "_kill_myself called from _finish_setup_mdns_actor. %s, self.on_kill is %s",
                self.success,
                self.on_kill,
            )
            self._kill_myself()

    @overrides
    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle WakeupMessage for regular updates"""
        if msg.payload == "update":
            if self.occupied:
                try:
                    logger.debug(
                        "Check whether %s still occupies %s.",
                        self.device_status["Reservation"]["Host"],
                        self.device_id,
                    )
                except (KeyError, TypeError):
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
                                "purpose": Purpose.UPDATE,
                            },
                            daemon=True,
                        )
                    )
        elif isinstance(msg.payload, Thread):
            self._start_thread(msg.payload)

    def _finish_update(self):
        """Handle WakeupMessage for regular updates"""
        if self.success == Status.OK:
            device_desc = self.response.get(self.device_id, False)
            if device_desc:
                reservation = device_desc.get("Reservation", False)
            else:
                logger.info(
                    "_kill_myself called from _finish_update. %s, self.on_kill is %s",
                    self.success,
                    self.on_kill,
                )
                self._kill_myself()
                return
            if reservation:
                active = reservation.get("Active", False)
            else:
                active = False
            self.device_status["Reservation"]["Active"] = active
            logger.debug("%s reservation active: %s", self.device_id, active)
            self._publish_status_change()
            if not active:
                self.occupied = False
            self.wakeupAfter(timedelta(seconds=UPDATE_INTERVAL), payload="update")
        elif self.success in (Status.NOT_FOUND, Status.IS_NOT_FOUND):
            logger.info(
                "_kill_myself called from _finish_update. %s, self.on_kill is %s",
                self.success,
                self.on_kill,
            )
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
        if self._client_socket is not None:
            self._client_socket.close()
            self._client_socket = None
        self._handle_free_reply_from_is(success)

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
            try:
                is_host = self.response[self.device_id]["Reservation"]["IP"]
                is_port = self.response[self.device_id]["Reservation"]["Port"]
            except KeyError:
                logger.error("Cannot create the client socket. Uncomplete reservation.")
                success = Status.NOT_FOUND
            if (success == Status.OK) and (self._client_socket is None):
                self._client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._client_socket.settimeout(BIN_TIMEOUT.seconds)
                try:
                    logger.debug("Trying to connect %s:%d", is_host, is_port)
                    self._client_socket.connect((is_host, is_port))
                except (
                    ConnectionRefusedError,
                    OSError,
                    TimeoutError,
                    socket.timeout,
                ) as exception:
                    logger.debug("%s:%d not reachable. %s", is_host, is_port, exception)
                    success = Status.NOT_FOUND
        else:
            success = self.success
        self._handle_reserve_reply_from_is(success)

    @overrides
    def _request_recent_value_at_is(self, msg, sender):
        self._start_thread(
            Thread(
                target=self._http_get_function,
                kwargs={
                    "endpoint": f"{self.base_url}/values/{self.device_id}",
                    "params": {
                        "app": msg.app,
                        "user": msg.user,
                        "host": msg.host,
                        "component": msg.component,
                        "sensor": msg.sensor,
                        "measurand": msg.measurand,
                    },
                    "purpose": Purpose.VALUE,
                },
                daemon=True,
            )
        )

    @overrides
    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        if not (self.reserve_lock.value or self.free_lock.value):
            self.occupied = False
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

    @overrides
    def _finish_set_device_status(self, device_status):
        """Finalize SetDeviceStatusMsg handler after receiving HTTP request."""
        if self.success == Status.OK:
            device_desc = self.response.get(self.device_id, False)
            logger.debug("device_desc: %s", device_desc)
            error = False
            if device_desc:
                identification = device_desc.get("Identification", False)
                error = not bool(identification)
            else:
                error = True
            if error:
                logger.info(
                    "_kill_myself called from _finish_set_device_status. %s, self.on_kill is %s",
                    self.success,
                    self.on_kill,
                )
                self._kill_myself()
                return
            self.device_status["Identification"] = identification
            reservation = device_desc.get("Reservation")
            if reservation is None:
                logger.debug(
                    "API reply from % has no Reservation section", self.device_id
                )
                self.device_status.pop("Reservation", None)
            else:
                using_host = reservation.get("Host", "")
                if self.reserve_device_msg is not None:
                    my_host = self.reserve_device_msg.host
                else:
                    my_host = config["MY_HOSTNAME"]
                if compare_hostnames(using_host, my_host):
                    logger.debug(
                        "Occupied by me. Using host is %s, my host is %s",
                        using_host,
                        my_host,
                    )
                else:
                    logger.debug("Occupied by somebody else.")
                    logger.debug("Using host: %s, my host: %s", using_host, my_host)
                    self.occupied = True
                    reservation.pop("IP", None)
                    reservation.pop("Port", None)
                self.device_status["Reservation"] = reservation
                self.wakeupAfter(timedelta(seconds=UPDATE_INTERVAL), payload="update")
            self._publish_status_change()
        else:
            logger.info(
                "_kill_myself called from _finish_set_device_status. %s, self.on_kill is %s",
                self.success,
                self.on_kill,
            )
            self._kill_myself()

    @overrides
    def _request_set_rtc_at_is(self, confirm=False):
        self._start_thread(
            Thread(
                target=self._http_post_function,
                kwargs={
                    "endpoint": f"{self.base_url}/instruments/{self.instr_id}/set-rtc",
                    "purpose": Purpose.SET_RTC,
                },
                daemon=True,
            )
        )
        super()._request_set_rtc_at_is(confirm)

    @overrides
    def _request_start_monitoring_at_is(self, start_time=..., confirm=False):
        self._start_thread(
            Thread(
                target=self._http_post_function,
                kwargs={
                    "endpoint": f"{self.base_url}/instruments/{self.instr_id}/start-monitoring",
                    "params": {"start_time": start_time.isoformat()},
                    "purpose": Purpose.MONITOR_START,
                },
                daemon=True,
            )
        )
        super()._request_start_monitoring_at_is(start_time, confirm)

    @overrides
    def _request_stop_monitoring_at_is(self):
        self._start_thread(
            Thread(
                target=self._http_post_function,
                kwargs={
                    "endpoint": f"{self.base_url}/instruments/{self.instr_id}/stop-monitoring",
                    "purpose": Purpose.MONITOR_STOP,
                },
                daemon=True,
            )
        )
        super()._request_stop_monitoring_at_is()

    @overrides
    def _request_bin_at_is(self, data):
        """Forward cmd data into the direction of the instrument."""
        super()._request_bin_at_is(data)
        try:
            self._client_socket.sendall(data)
            reply = self._client_socket.recv(1024)
        except (
            OSError,
            TimeoutError,
            socket.timeout,
            ConnectionResetError,
            NameError,
            AttributeError,
        ) as exception:
            logger.error("%s. IS closed or disconnected.", exception)
            reply = self.RET_TIMEOUT
        self._handle_bin_reply_from_is(RxBinaryMsg(data=reply))
