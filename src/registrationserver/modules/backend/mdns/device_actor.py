"""Device actor for socket communication in the backend

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""
import requests
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, SetupMdnsActorAckMsg,
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


class DeviceActor(DeviceBaseActor):
    """Actor for dealing with raw socket connections between App and IS2"""

    @overrides
    def __init__(self):
        super().__init__()
        self._is_host = None
        self._api_port = None
        self.device_id = None
        self.base_url = ""
        self.http = requests.Session()
        assert_status_hook = (
            lambda response, *args, **kwargs: response.raise_for_status()
        )
        self.http.hooks["response"] = [assert_status_hook]
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1,
        )
        adapter = TimeoutHTTPAdapter(max_retries=retry_strategy)
        self.http.mount("https://", adapter)
        self.http.mount("http://", adapter)

    def receiveMsg_SetupMdnsActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetupMdnsActorMsg containing setup information
        that is special to the mDNS device actor"""
        self._is_host = msg.is_host
        self._api_port = msg.api_port
        self.device_id = msg.device_id
        self.base_url = f"http://{self._is_host}:{self._api_port}"
        try:
            _resp = self.http.get(f"{self.base_url}/list/{self.device_id}/")
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.error(success)
            self.send(self.myAddress, KillMsg())
        self.send(sender, SetupMdnsActorAckMsg())

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        try:
            resp = self.http.get(f"{self.base_url}/list/{self.device_id}/")
            device_resp = resp.json()
            device_desc = device_resp[self.device_id]
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.error("%s, cannot access REST API of IS", success)
            super().receiveMsg_FreeDeviceMsg(msg, sender)
            return
        success = Status.NOT_FOUND
        reservation = device_desc.get("Reservation")
        if (reservation is None) or reservation.get("Active", True):
            try:
                resp = self.http.get(f"{self.base_url}/list/{self.device_id}/free")
                resp_free = resp.json()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                logger.error("%s, cannot access REST API of IS", success)
            else:
                error_code = resp_free.get("Error code")
                logger.debug("Error code: %d", error_code)
                if error_code is None:
                    success = Status.ERROR
                else:
                    success = Status(error_code)
        else:
            logger.debug("Tried to free a device that was not reserved.")
            success = Status.OK_SKIPPED
        logger.debug("Freeing remote device ended with %s", success)
        super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def _reserve_at_is(self):
        """Reserve the requested instrument at the instrument server."""
        try:
            resp = self.http.get(f"{self.base_url}/list/{self.device_id}/")
            device_resp = resp.json()
            device_desc = device_resp[self.device_id]
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            self._forward_reservation(success)
            return
        success = Status.NOT_FOUND
        reservation = device_desc.get("Reservation")
        if reservation is not None:
            reservation.pop("IP", None)
            reservation.pop("Port", None)
            self.device_status["Reservation"] = reservation
        if (reservation is None) or not reservation.get("Active", False):
            logger.debug("%s is not reserved yet", self.device_id)
            app = f"{self.app} - {self.user} - {sanitize_hn(self.host)}"
            logger.debug("Try to reserve this instrument for %s.", app)
            try:
                resp = self.http.get(
                    f"{self.base_url}/list/{self.device_id}/reserve",
                    params={"who": app},
                )
                resp_reserve = resp.json()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                self._forward_reservation(success)
                return
            self.device_status["Reservation"] = resp_reserve[self.device_id].get(
                "Reservation", {}
            )
            error_code = resp_reserve.get("Error code")
            logger.debug("Error code: %d", error_code)
            if error_code is None:
                success = Status.ERROR
            else:
                success = Status(error_code)
        else:
            logger.debug("%s is already reserved", self.device_id)
            using_host = sanitize_hn(device_desc["Reservation"]["Host"])
            my_host = sanitize_hn(config["MY_HOSTNAME"])
            if using_host == my_host:
                logger.debug("Already occupied by me.")
                success = Status.OK_SKIPPED
            else:
                logger.debug("Occupied by somebody else.")
                logger.debug("Using host: %s, my host: %s", using_host, my_host)
                success = Status.OCCUPIED
        self._forward_reservation(success)

    @overrides
    def _forward_reservation(self, success: Status):
        """Forward the reservation state from the Instrument Server to the REST API."""
        if success in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            logger.error(
                "Reservation failed with %s. Removing device from list.", success
            )
            self.send(self.myAddress, KillMsg())
        elif success == Status.ERROR:
            logger.critical("%s during reservation", success)
            system_shutdown()
        self._update_reservation_status(self.device_status["Reservation"])

    @overrides
    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        """Handler for SetDeviceStatusMsg initialising the device status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.device_status = msg.device_status
        logger.debug("Device status: %s", self.device_status)
        try:
            resp = self.http.get(f"{self.base_url}/list/{self.device_id}/")
            device_resp = resp.json()
            device_desc = device_resp[self.device_id]
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("REST API of IS is not responding. %s", exception)
            success = Status.IS_NOT_FOUND
            logger.error(success)
            self.send(self.myAddress, KillMsg())
        else:
            logger.debug("device_resp: %s", device_resp)
            logger.debug("device_desc: %s", device_desc)
            success = Status.NOT_FOUND
            if device_desc.get("Identification") is None:
                logger.warning(
                    "No Identification information available for %s", self.device_id
                )
                self.send(self.myAddress, KillMsg())
                super().receiveMsg_GetDeviceStatusMsg(msg, sender)
                return
            self.device_status["Identification"]["Origin"] = device_desc[
                "Identification"
            ].get("Origin")
            reservation = device_desc.get("Reservation")
            if reservation is not None:
                if reservation.get("Active", False):
                    using_host = sanitize_hn(reservation.get("Host", ""))
                    my_host = sanitize_hn(config["MY_HOSTNAME"])
                    if using_host == my_host:
                        logger.debug("Occupied by me.")
                        success = Status.OK_SKIPPED
                    else:
                        logger.debug("Occupied by somebody else.")
                        logger.debug("Using host: %s, my host: %s", using_host, my_host)
                        success = Status.OCCUPIED
                        reservation.pop("IP", None)
                        reservation.pop("Port", None)
                    self.device_status["Reservation"] = reservation
                else:
                    success = Status.OK
                    self.device_status.pop("Reservation", None)
        self._publish_status_change()
