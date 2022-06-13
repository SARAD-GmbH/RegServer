"""Device actor for socket communication in the backend

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""


from datetime import datetime, timedelta

import requests
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, ReservationStatusMsg,
                                               Status)
from registrationserver.config import config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from registrationserver.shutdown import system_shutdown

logger.debug("%s -> %s", __package__, __file__)

CMD_CYCLE_TIMEOUT = 1


class DeviceActor(DeviceBaseActor):
    """Actor for dealing with raw socket connections between App and IS2"""

    @overrides
    def __init__(self):
        super().__init__()
        self._is_host = None
        self._api_port = None
        self.list_resp = {}
        self.time_of_req = datetime(1970, 1, 1)
        self.device_id = None

    def receiveMsg_SetupMdnsActorMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for SetupMdnsActorMsg containing setup information
        that is special to the mDNS device actor"""
        self._is_host = msg.is_host
        self._api_port = msg.api_port
        self.device_id = msg.device_id

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        base_url = f"http://{self._is_host}:{self._api_port}"
        age = datetime.utcnow() - self.time_of_req
        if age > timedelta(seconds=1):
            try:
                self.list_resp = requests.get(f"{base_url}/list/").json()
                self.time_of_req = datetime.utcnow()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                logger.error("%s, cannot access REST API of IS", success)
                super().receiveMsg_FreeDeviceMsg(msg, sender)
                return
        success = Status.NOT_FOUND
        for device_id, device_desc in self.list_resp.items():
            if device_id.split(".")[0] == self.my_id.split(".")[0]:
                reservation = device_desc.get("Reservation")
                if (reservation is None) or reservation.get("Active", True):
                    try:
                        resp = requests.get(f"{base_url}/list/{device_id}/free").json()
                    except Exception as exception:  # pylint: disable=broad-except
                        logger.error("REST API of IS is not responding. %s", exception)
                        success = Status.IS_NOT_FOUND
                        logger.error("%s, cannot access REST API of IS", success)
                    else:
                        error_code = resp.get("Error code")
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
        base_url = f"http://{self._is_host}:{self._api_port}"
        age = datetime.utcnow() - self.time_of_req
        if age > timedelta(seconds=1):
            try:
                self.list_resp = requests.get(f"{base_url}/list/").json()
                self.time_of_req = datetime.utcnow()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                self._forward_reservation(success)
                return
        success = Status.NOT_FOUND
        for device_id, device_desc in self.list_resp.items():
            if device_id.split(".")[0] == self.my_id.split(".")[0]:
                reservation = device_desc.get("Reservation")
                if reservation is not None:
                    reservation.pop("IP", None)
                    reservation.pop("Port", None)
                    self.device_status["Reservation"] = reservation
                if (reservation is None) or not reservation.get("Active", False):
                    app = f"{self.app} - {self.user} - {self.host}"
                    logger.debug("Try to reserve this instrument for %s.", app)
                    try:
                        resp = requests.get(
                            f"{base_url}/list/{device_id}/reserve", {"who": app}
                        ).json()
                    except Exception as exception:  # pylint: disable=broad-except
                        logger.error("REST API of IS is not responding. %s", exception)
                        success = Status.IS_NOT_FOUND
                        self._forward_reservation(success)
                        return
                    self.device_status["Reservation"] = resp[device_id].get(
                        "Reservation"
                    )
                    error_code = resp.get("Error code")
                    logger.debug("Error code: %d", error_code)
                    if error_code is None:
                        success = Status.ERROR
                    else:
                        success = Status(error_code)
                else:
                    using_host = device_desc["Reservation"]["Host"].split(".")[0]
                    my_host = config["MY_HOSTNAME"].split(".")[0]
                    if using_host == my_host:
                        logger.debug("Already occupied by me.")
                        success = Status.OK_SKIPPED
                    else:
                        logger.debug("Occupied by somebody else.")
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
        self.send(
            self.sender_api,
            ReservationStatusMsg(instr_id=short_id(self.my_id), status=success),
        )

    @overrides
    def receiveMsg_GetDeviceStatusMsg(self, msg, sender):
        """Handler for GetDeviceStatusMsg asking to send updated information
        about the device status to the sender.

        Sends back a message containing the device_status."""
        if (self._is_host is None) or (self._api_port is None):
            logger.warning("Actor initialisation incomplete.")
            super().receiveMsg_GetDeviceStatusMsg(msg, sender)
            return
        base_url = f"http://{self._is_host}:{self._api_port}"
        age = datetime.utcnow() - self.time_of_req
        if age > timedelta(seconds=1):
            try:
                self.list_resp = requests.get(f"{base_url}/list/").json()
                self.time_of_req = datetime.utcnow()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("REST API of IS is not responding. %s", exception)
                success = Status.IS_NOT_FOUND
                logger.error(success)
                self.send(self.myAddress, KillMsg())
            else:
                success = Status.NOT_FOUND
                for device_id, device_desc in self.list_resp.items():
                    if device_id.split(".")[0] == self.my_id.split(".")[0]:
                        self.device_status["Identification"]["Origin"] = device_desc[
                            "Identification"
                        ].get("Origin")
                        reservation = device_desc.get("Reservation")
                        if reservation is not None:
                            using_host = reservation.get("Host", "").split(".")[0]
                            my_host = config["MY_HOSTNAME"].split(".")[0]
                            if using_host == my_host:
                                logger.debug("Occupied by me.")
                                success = Status.OK_SKIPPED
                            else:
                                logger.debug("Occupied by somebody else.")
                                success = Status.OCCUPIED
                                reservation.pop("IP", None)
                                reservation.pop("Port", None)
                            self.device_status["Reservation"] = reservation
        super().receiveMsg_GetDeviceStatusMsg(msg, sender)
