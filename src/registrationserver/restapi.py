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
from datetime import datetime, timedelta, timezone

from flask import Flask, request
from flask_restx import Api, Resource, reqparse  # type: ignore
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import Thespian_ActorStatus
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)
from waitress import serve

from registrationserver.actor_messages import (GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetRecentValueMsg,
                                               GetUsbPortsMsg, RecentValueMsg,
                                               RescanFinishedMsg, RescanMsg,
                                               ReturnLocalPortsMsg,
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
PASSWORD = "Diev5Pw."


app = Flask(__name__)
app.url_map.strict_slashes = False
api = Api(
    app,
    version="1.0",
    title="RegServer API",
    description="API to get data from and to control the SARAD Registration Server service",
)
api.namespaces.clear()
root_ns = api.namespace("/", description="Administrative functions")
list_ns = api.namespace(
    "list", description="List SARAD instruments, reserve or release them"
)
ports_ns = api.namespace(
    "ports", description="Endpoints to list available serial ports for debugging"
)
status_ns = api.namespace(
    "status", description="Endpoints to show status information for debugging"
)
values_ns = api.namespace("values", description="Show measuring values")
reserve_arguments = reqparse.RequestParser()
reserve_arguments.add_argument("who", type=str, required=True)
shutdown_arguments = reqparse.RequestParser()
shutdown_arguments.add_argument(
    "password",
    type=str,
    required=True,
    choices=[PASSWORD],
)
values_arguments = reqparse.RequestParser()
values_arguments.add_argument("component", type=int, required=True)
values_arguments.add_argument("sensor", type=int, required=True)
values_arguments.add_argument(
    "measurand", type=int, required=True, choices=[0, 1, 2, 3]
)


class Dummy:
    """Dummy output to ignore stdout"""

    @staticmethod
    def write(arg=None, **kwargs):
        """Does Nothing"""

    @staticmethod
    def flush(arg=None, **kwargs):
        """Does Nothing"""


@root_ns.route("/ping")
class Ping(Resource):
    """Request a sign of life to confirm that the host is online."""

    def get(self):
        """Request a sign of life to confirm that the host is online."""
        logger.debug("Ping received")
        return {
            "service": "SARAD Registration Server",
            "running_since": STARTTIME.replace(
                tzinfo=timezone.utc, microsecond=0
            ).isoformat(),
        }


@root_ns.route("/shutdown")
@root_ns.param(
    "password",
    "This is not really a password since it is given here. "
    + "It is only there to prevent shutdown by mistake.",
)
class Shutdown(Resource):
    """Shutdown the SARAD Registration Server."""

    @api.expect(shutdown_arguments, validate=True)
    def get(self):
        """Shutdown the SARAD Registration Server.

        The service will be terminated with error and thus be restarted
        automatically by the Service Manager (Windows) or Systemd (Linux)
        resp.

        """
        remote_addr = request.remote_addr
        remote_user = request.remote_user
        try:
            attribute_password = request.args.get("password").strip('"')
        except (IndexError, AttributeError):
            status = Status.ATTRIBUTE_ERROR
        else:
            if attribute_password == PASSWORD:
                status = Status.OK
            else:
                status = Status.ATTRIBUTE_ERROR
        answer = {}
        if status == Status.OK:
            logger.info(
                "Shutdown by user intervention from %s",
                remote_addr,
            )
            system_shutdown()
            answer = {
                "Notification": "Registration Server going down for restart.",
                "Requester": remote_addr,
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


@list_ns.route("/")
class List(Resource):
    """Endpoint for getting the list of active devices"""

    def get(self):
        """List available SARAD instruments"""
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


@root_ns.route("/scan")
class Scan(Resource):
    """Refresh the list of active devices"""

    def get(self):
        """Refresh the list of active devices.

        This might be required for SARAD instruments that are connected via
        USB/RS-232 adapters like the instruments of the DOSEman family that are
        connected via their IR cradle. The Registration Server is detecting
        instruments by their USB connection or, if configured, by polling. This
        function was implemented as fallback.

        """
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


@list_ns.route("/<string:device_id>")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
class ListDevice(Resource):
    """Endpoint for getting information for a single active device"""

    def get(self, device_id):
        """Get indentifying information for a single available instrument."""
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


@list_ns.route("/<string:device_id>/reserve")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
@list_ns.param(
    "who",
    "String identifying who requested the reservation."
    + "Consists of application, user, and requesting host. "
    + "All three parts are to be devided by ` - `. \n"
    + "Example: `who=RV8 - mstrey - WS01`",
)
class ReserveDevice(Resource):
    """Endpoint for reserving an available instrument"""

    @api.expect(reserve_arguments, validate=True)
    def get(self, device_id):
        """Reserve an available instrument so that nobody else can use it."""
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


@list_ns.route("/<string:device_id>/free")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
class FreeDevice(Resource):
    """Endpoint for freeing a reserved instrument"""

    def get(self, device_id):
        """Free/release a device that was reserved before"""
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


@values_ns.route("/<string:device_id>")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
@list_ns.param(
    "component",
    "Component index found in dVision",
)
@list_ns.param(
    "sensor",
    "Sensor index found in dVision",
)
@list_ns.param(
    "measurand",
    "Measurand index found in dVision. 0 = Recent, 1 = Average, 2 = Minimum, 3 = Maximum",
)
class GetValues(Resource):
    """Endpoint to get measuring values from a SARAD instrument"""

    @api.expect(values_arguments, validate=True)
    def get(self, device_id):
        # pylint: disable=too-many-return-statements
        """Gather a measuring value from a SARAD instrument of DACM family"""
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


@ports_ns.route("/")
class GetLocalPorts(Resource):
    """Lists local serial ports"""

    def get(self):
        """Lists local serial ports"""
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


@ports_ns.route("/list-usb")
class GetUsbPorts(Resource):
    """List local USB devices with virtual serial ports"""

    def get(self):
        """List local USB devices with virtual serial ports"""
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


@ports_ns.route("/list-native")
class GetNativePorts(Resource):
    """List local RS-232 ports"""

    def get(self):
        """List local RS-232 ports"""
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


@status_ns.route("/<string:actor_id>")
@status_ns.param(
    "actor_id",
    "ID of an Actor existing in the Thespian Actor System of the Registration Server",
)
class GetStatus(Resource):
    """Ask Actor System to output Actor status to debug log"""

    def get(self, actor_id):
        """Ask Actor System to output Actor status to debug log"""
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
