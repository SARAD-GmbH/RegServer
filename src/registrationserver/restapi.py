"""REST API -- the interface to the SARAD app

:Created:
    2020-10-02

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-restapi.puml

"""

import sys
import time
from datetime import datetime, timedelta

from flask import Flask, request
from flask_restx import Api, Resource  # type: ignore
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import Thespian_ActorStatus
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)
from waitress import serve

from registrationserver.actor_messages import (AddPortToLoopMsg,
                                               GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetRecentValueMsg,
                                               GetUsbPortsMsg, RecentValueMsg,
                                               RemovePortFromLoopMsg,
                                               RescanFinishedMsg, RescanMsg,
                                               ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg, Status)
from registrationserver.config import mqtt_config
from registrationserver.helpers import (check_msg, get_actor,
                                        get_device_status, get_device_statuses,
                                        get_registrar_actor, sanitize_hn,
                                        send_free_message,
                                        send_reserve_message,
                                        transport_technology)
from registrationserver.logger import logger  # type: ignore
from registrationserver.shutdown import system_shutdown

# logger.debug("%s -> %s", __package__, __file__)

STARTTIME = datetime.utcnow()


app = Flask(__name__)
api = Api(app)


class Dummy:
    """Dummy output to ignore stdout"""

    @staticmethod
    def write(arg=None, **kwargs):
        """Does Nothing"""

    @staticmethod
    def flush(arg=None, **kwargs):
        """Does Nothing"""


@api.route("/", "/ping", "/ping/")
class Ping(Resource):
    """Send a sign of life to confirm that the host is online."""

    def get(self):
        """Send a sign of life to confirm that the host is online."""
        logger.debug("Ping received")
        return {"service": "SARAD Registration Server", "running_since": str(STARTTIME)}


@api.route("/shutdown", "/shutdown/")
class Shutdown(Resource):
    """Allows to shutdown the Registration Server."""

    def get(self):
        """Allows to shutdown the Registration Server."""
        remote_addr = request.remote_addr
        remote_user = request.remote_user
        try:
            attribute_who = request.args.get("who").strip('"')
        except (IndexError, AttributeError):
            status = Status.ATTRIBUTE_ERROR
        else:
            if attribute_who in ("Michael", "Riccardo"):
                status = Status.OK
            else:
                status = Status.ATTRIBUTE_ERROR
        answer = {}
        if status == Status.OK:
            logger.info(
                "Shutdown by user intervention from %s @ %s",
                attribute_who,
                remote_addr,
            )
            system_shutdown()
            answer = {
                "Notification": "Registration Server going down for restart.",
                "Requester": attribute_who,
            }
        elif status == Status.ATTRIBUTE_ERROR:
            logger.warning(
                "%s requesting shutdown without proper attribute", remote_addr
            )
        else:
            logger.error("Unexpected error in shutdown by user.")
            status = Status.ERROR
        answer["Error code"] = status.value
        answer["Error"] = str(status)
        answer["Remote addr"] = remote_addr
        answer["Remote user"] = remote_user
        return answer


@api.route("/list", "/list/")
class List(Resource):
    """Path for getting the list of active devices"""

    def get(self):
        """Path for getting the list of active devices"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        return get_device_statuses(registrar_actor)


@api.route("/scan", "/scan/")
class Scan(Resource):
    """Refresh the list of active devices"""

    def get(self):
        """Refresh the list of active devices"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(registrar_actor, "cluster")
        with ActorSystem().private() as scan_sys:
            try:
                reply = scan_sys.ask(
                    cluster_actor, RescanMsg(), timeout=timedelta(seconds=60)
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, RescanFinishedMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return {
            "Error code": reply.status.value,
            "Error": str(reply.status),
        }


@api.route("/list/<string:device_id>", "/list/<string:device_id>/")
class ListDevice(Resource):
    """Path for getting information for a single active device"""

    def get(self, device_id):
        """Path for getting information for a single active device"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        return {device_id: get_device_status(registrar_actor, device_id)}


@api.route("/list/<string:device_id>/reserve", "/list/<string:device_id>/reserve/")
class ReserveDevice(Resource):
    """Path for reserving a single active device"""

    def get(self, device_id):
        """Path for reserving a single active device"""
        # Collect information about who sent the request.
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Registrar Actor. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        try:
            attribute_who = request.args.get("who").strip('"')
            application = attribute_who.split(" - ")[0]
            user = attribute_who.split(" - ")[1]
            request_host = sanitize_hn(attribute_who.split(" - ")[2])
        except (IndexError, AttributeError):
            logger.warning("Reserve request without proper who attribute.")
            status = Status.ATTRIBUTE_ERROR
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
            }
        logger.info(
            "Request reservation of %s for %s@%s",
            device_id,
            attribute_who,
            request_host,
        )
        device_state = get_device_status(registrar_actor, device_id)
        if (
            transport_technology(device_id) not in ["local", "is1", "mdns", "mqtt"]
        ) or (device_state == {}):
            logger.error("Requested service not supported by actor system.")
            status = Status.NOT_FOUND
        else:
            status = send_reserve_message(
                device_id, registrar_actor, request_host, user, application
            )
        if status == Status.CRITICAL:
            status = Status.IS_NOT_FOUND
        if status in (
            Status.OK,
            Status.OK_SKIPPED,
            Status.OK_UPDATED,
            Status.OCCUPIED,
            Status.NOT_FOUND,
            Status.IS_NOT_FOUND,
        ):
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: get_device_status(registrar_actor, device_id),
            }
        status = Status.CRITICAL
        logger.critical("No response from Device Actor. -> Emergency shutdown")
        system_shutdown()
        return {
            "Error code": status.value,
            "Error": str(status),
            device_id: {},
            "Notification": "Registration Server going down for restart.",
            "Requester": "Emergency shutdown",
        }


@api.route("/list/<string:device_id>/free", "/list/<string:device_id>/free/")
class FreeDevice(Resource):
    """Path for freeing a single active device"""

    def get(self, device_id):
        """Path for freeing a single active device"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
        else:
            is_status = send_free_message(device_id, registrar_actor)
            if is_status == Status.CRITICAL:
                status = Status.IS_NOT_FOUND
            else:
                status = is_status
        if status == Status.CRITICAL:
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        return {
            "Error code": status.value,
            "Error": str(status),
            device_id: get_device_status(registrar_actor, device_id),
        }


@api.route("/values/<string:device_id>", "/values/<string:device_id>/")
class GetValues(Resource):
    """Path to get values of a special device"""

    def get(self, device_id):
        # pylint: disable=too-many-return-statements
        """Path to get values of a special device"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        try:
            component_id = int(request.args.get("component").strip('"'))
            sensor_id = int(request.args.get("sensor").strip('"'))
            measurand_id = int(request.args.get("measurand").strip('"'))
        except (IndexError, AttributeError):
            logger.warning("Get recent values request without proper attributes.")
            status = Status.ATTRIBUTE_ERROR
            notification = "Requires component, sensor, measurand."
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": notification,
            }
        logger.info(
            "Request value %d/%d/%d of %s",
            component_id,
            sensor_id,
            measurand_id,
            device_id,
        )
        device_state = get_device_status(registrar_actor, device_id)
        if (
            (device_state == {})
            or (transport_technology(device_id) not in ["local"])
            or ("sarad-dacm" not in device_id)
        ):
            logger.error("Request only supported for local DACM instruments.")
            status = Status.NOT_FOUND
            notification = "Only supported for local DACM instruments"
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": notification,
            }
        # send GetRecentValueMsg to device actor
        device_actor = get_actor(registrar_actor, device_id)
        if device_actor is None:
            status = Status.NOT_FOUND
            return {
                "Error code": status.value,
                "Error": str(status),
            }
        with ActorSystem().private() as value_sys:
            try:
                value_return = value_sys.ask(
                    device_actor,
                    GetRecentValueMsg(component_id, sensor_id, measurand_id),
                    timeout=timedelta(seconds=10),
                )
            except ConnectionResetError:
                status = Status.CRITICAL
                logger.critical("No response from Actor System. -> Emergency shutdown")
                system_shutdown()
                return {
                    "Error code": status.value,
                    "Error": str(status),
                    "Notification": "Registration Server going down for restart.",
                    "Requester": "Emergency shutdown",
                }
        reply_is_corrupted = check_msg(value_return, RecentValueMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        if value_return.status == Status.INDEX_ERROR:
            return {
                "Error code": value_return.status.value,
                "Error": str(value_return.status),
                "Notification": "The requested measurand is not available.",
            }
        timestamp = (
            value_return.timestamp.isoformat(timespec="seconds") + "Z"
            if value_return.timestamp is not None
            else None
        )
        return {
            "Device Id": device_id,
            "Component name": value_return.component_name,
            "Sensor name": value_return.sensor_name,
            "Measurand name": value_return.measurand_name,
            "Measurand": value_return.measurand,
            "Operator": value_return.operator,
            "Value": value_return.value,
            "Unit": value_return.unit,
            "Timestamp": timestamp,
            "Fetched": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "GPS": {
                "Valid": value_return.gps.valid,
                "Latitude": value_return.gps.latitude,
                "Longitude": value_return.gps.longitude,
                "Altitude": value_return.gps.altitude,
                "Deviation": value_return.gps.deviation,
            },
        }


@api.route("/ports", "/ports/")
class GetLocalPorts(Resource):
    """Lists Local Ports, Used for Testing atm"""

    def get(self):
        """Lists Local Ports, Used for Testing atm"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(registrar_actor, "cluster")
        with ActorSystem().private() as get_local_ports:
            try:
                reply = get_local_ports.ask(
                    cluster_actor, GetLocalPortsMsg(), timeout=timedelta(seconds=10)
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnLocalPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@api.route("/ports/<int:port>/loop")
class GetLoopPort(Resource):
    """Loops Local Ports, Used for Testing"""

    def get(self, port):
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(registrar_actor, "cluster")
        with ActorSystem().private() as get_loop_port:
            try:
                reply = get_loop_port.ask(
                    cluster_actor,
                    AddPortToLoopMsg(port),
                    timeout=timedelta(seconds=10),
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnLoopPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@api.route("/ports/<int:port>/stop")
class GetStopPort(Resource):
    """Loops Local Ports, Used for Testing"""

    def get(self, port):
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(registrar_actor, "cluster")
        with ActorSystem().private() as get_stop_port:
            try:
                reply = get_stop_port.ask(
                    cluster_actor,
                    RemovePortFromLoopMsg(port),
                    timeout=timedelta(seconds=10),
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnLoopPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@api.route("/ports/list-usb")
class GetUsbPorts(Resource):
    """Loops Local Ports, Used for Testing"""

    def get(self):
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(registrar_actor, "cluster")
        with ActorSystem().private() as get_usb_ports:
            try:
                reply = get_usb_ports.ask(
                    cluster_actor, GetUsbPortsMsg(), timeout=timedelta(seconds=10)
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnUsbPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@api.route("/ports/list-native")
class GetNativePorts(Resource):
    """Loops Local Ports, Used for Testing"""

    def get(self):
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(registrar_actor, "cluster")
        with ActorSystem().private() as get_native_ports:
            try:
                reply = get_native_ports.ask(
                    cluster_actor,
                    GetNativePortsMsg(),
                    timeout=timedelta(seconds=10),
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnNativePortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@api.route("/status/<string:actor_id>")
class GetStatus(Resource):
    """Ask actor system to output actor status to debug log"""

    def get(self, actor_id):
        """Ask actor system to output actor status to debug log"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        actor_address = get_actor(registrar_actor, actor_id)
        with ActorSystem().private() as get_status:
            try:
                reply = get_status.ask(
                    actorAddr=actor_address,
                    msg=Thespian_StatusReq(),
                    timeout=timedelta(seconds=10),
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, Thespian_ActorStatus)
        if reply_is_corrupted:
            return reply_is_corrupted

        class Temp:
            # pylint: disable=too-few-public-methods
            """Needed for formatStatus"""

            write = logger.debug

        formatStatus(reply, tofd=Temp())
        status = Status.OK
        return {"Error code": status.value, "Error": str(status)}


def run(port=None):
    """Start the API"""
    success = False
    retry_interval = mqtt_config.get("RETRY_INTERVAL", 60)
    while not success:
        try:
            logger.info("Starting API at port %d", port)
            std = sys.stdout
            sys.stdout = Dummy
            # self.api.run(host=host, port=port)
            serve(app, listen=f"*:{port}", threads=12)
            sys.stdout = std
            success = True
        except OSError as exception:
            logger.critical(exception)
            time.sleep(retry_interval)
