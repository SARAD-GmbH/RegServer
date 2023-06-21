"""REST API -- the interface to the SARAD app

:Created:
    2020-10-02

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-restapi.puml

"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, request
from flask_restx import Api, Resource, fields, reqparse  # type: ignore
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import Thespian_ActorStatus
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)
from version import VERSION
from waitress import serve

from registrationserver.actor_messages import (AddPortToLoopMsg,
                                               GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetRecentValueMsg,
                                               GetUsbPortsMsg, Instrument,
                                               RecentValueMsg,
                                               RemovePortFromLoopMsg,
                                               RescanFinishedMsg, RescanMsg,
                                               ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg, Status)
from registrationserver.config import actor_config, mqtt_config
from registrationserver.helpers import (check_msg, get_actor,
                                        get_device_status_from_registrar,
                                        get_device_statuses, get_hosts,
                                        get_registrar_actor, send_free_message,
                                        send_reserve_message, short_id,
                                        transport_technology)
from registrationserver.logdef import LOGFILENAME
from registrationserver.logger import logger  # type: ignore
from registrationserver.shutdown import system_shutdown

# logger.debug("%s -> %s", __package__, __file__)

STARTTIME = datetime.utcnow()
PASSWORD = "Diev5Pw."
TIMEOUT = timedelta(seconds=20)


app = Flask(__name__)
app.url_map.strict_slashes = False
api = Api(
    app,
    version="2.0",
    title="RegServer API",
    description="API to get data from and to control the SARAD Registration Server service",
)
api.namespaces.clear()
root_ns = api.namespace("/", description="Administrative functions")
list_ns = api.namespace(
    "list",
    description="Collection of SARAD instruments,"
    + " alias of 'instruments' for backward compatibility",
)
hosts_ns = api.namespace(
    "hosts",
    description="Collection of available hosts with SARAD instruments connected",
)
host = api.model(
    "Host",
    {
        "host": fields.String(description="The FQDN of the host"),
        "transport_technology": fields.Integer(
            description="How is the instrument connected to this RegServer"
        ),
        "origin": fields.String(
            description="Alias of the host given as 'is_id' in its configuration"
        ),
        "description": fields.String(
            description="Free text string describing the host"
        ),
        "place": fields.String(
            description="Name of the place where the host is situated"
        ),
        "lat": fields.Float(
            description="Latitude of the place. Positive values are north, negatives are south"
        ),
        "lon": fields.Float(
            description="Longitude of the place. Positive values are east, negatives are west"
        ),
        "height": fields.Integer(description="Height of the place."),
    },
)
instruments_ns = api.namespace(
    "instruments", description="Collection of SARAD instruments"
)
instrument = api.model(
    "Instrument",
    {
        "instr_id": fields.String(description="The instrument unique identifier"),
        "serial_number": fields.Integer(description="The instrument serial number"),
        "firmware_version": fields.Integer(
            description="The number of the firmware version"
        ),
        "host": fields.String(
            description="The FQDN of the host the instrument is connected to"
        ),
    },
)
ports_ns = api.namespace(
    "ports", description="Endpoints to list available serial ports for debugging"
)
status_ns = api.namespace(
    "status", description="Endpoints to show status information for debugging"
)
values_ns = api.namespace("values", description="Show measuring values")
reserve_arguments = reqparse.RequestParser()
reserve_arguments.add_argument(
    "who",
    type=str,
    required=True,
    help="Requires an argument `who` identifying the requester."
    + "Consists of application, user, and requesting host. "
    + "All three parts are to be devided by ` - `. \n"
    + "Example: `who=RV8 - mstrey - WS01`",
    trim=True,
)
shutdown_arguments = reqparse.RequestParser()
shutdown_arguments.add_argument(
    "password",
    type=str,
    required=True,
    help="Requires the correct password as argument.",
    choices=[PASSWORD],
    trim=True,
)
log_arguments = reqparse.RequestParser()
log_arguments.add_argument(
    "age",
    type=int,
    required=False,
    help="Requires 'age' to be either 0 for current or 1 for last log.",
    default=0,
    choices=[0, 1],
    trim=True,
)
ports_arguments = reqparse.RequestParser()
ports_arguments.add_argument("port", type=str, required=False)
values_arguments = reqparse.RequestParser()
values_arguments.add_argument(
    "component",
    type=int,
    required=True,
    help="Requires component, sensor, measurand.",
    trim=True,
)
values_arguments.add_argument(
    "sensor",
    type=int,
    required=True,
    help="Requires component, sensor, measurand.",
    trim=True,
)
values_arguments.add_argument(
    "measurand",
    type=int,
    required=True,
    help="Requires component, sensor, measurand.",
    choices=[0, 1, 2, 3],
    trim=True,
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

    def post(self):
        """Request a sign of life to confirm that the host is online."""
        logger.debug("Ping received")
        return {
            "service": "SARAD Registration Server",
            "version": VERSION,
            "running_since": STARTTIME.replace(
                tzinfo=timezone.utc, microsecond=0
            ).isoformat(),
            "system_base": actor_config["systemBase"],
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
    def post(self):
        """Shutdown the SARAD Registration Server.

        The service will be terminated with error and thus be restarted
        automatically by the Service Manager (Windows) or Systemd (Linux)
        resp.

        """
        remote_addr = request.remote_addr
        remote_user = request.remote_user
        shutdown_arguments.parse_args()
        logger.info(
            "Shutdown by user intervention from %s",
            remote_addr,
        )
        system_shutdown()
        answer = {
            "Notification": "Registration Server going down for restart.",
            "Requester": remote_addr,
        }
        status = Status.OK
        answer["Error code"] = status.value
        answer["Error"] = str(status)
        answer["Remote addr"] = remote_addr
        answer["Remote user"] = remote_user
        return answer


@root_ns.route("/log")
@root_ns.param(
    "age",
    "May be 0 for the current log or 1 for the backup of the log "
    + "from the last run of Registration Server Service.",
)
class Log(Resource):
    """Endpoint to show the content of the log file"""

    @api.expect(log_arguments, validate=True)
    def get(self):
        """Show the content of the log file"""
        logger.debug("Log request received")
        attribute_age = log_arguments.parse_args()
        if attribute_age["age"]:
            log_file_name = f"{LOGFILENAME}.1"
        else:
            log_file_name = LOGFILENAME
        if os.path.isfile(log_file_name):
            with open(log_file_name, "r", encoding="utf8") as log_file:
                lines = log_file.readlines()
            resp = [line.rstrip("\n") for line in lines]
            return resp
        return f"{log_file_name} doesn't exist."


@root_ns.route("/scan")
class Scan(Resource):
    """Refresh the list of active devices"""

    def post(self):
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
        with ActorSystem().private() as scan_sys:
            try:
                reply = scan_sys.ask(
                    registrar_actor, RescanMsg(), timeout=timedelta(seconds=60)
                )
            except ConnectionResetError as exception:
                logger.debug(exception)
                reply = None
        reply_is_corrupted = check_msg(reply, RescanFinishedMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return {
            "Error code": reply.status.value,
            "Error": str(reply.status),
        }


@list_ns.route("/")
class List(Resource):
    """Endpoint for getting the list of active devices.

    This endpoint is deprecated and only for backward compatibility."""

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


@list_ns.route("/<string:device_id>")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
class ListDevice(Resource):
    """Endpoint for getting information for a single active device"""

    def get(self, device_id):
        """Get indentifying information for a single available instrument."""
        logger.debug("ListDevice %s", device_id)
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
        return {device_id: get_device_status_from_registrar(registrar_actor, device_id)}


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
        logger.debug("ReserveDevice %s", device_id)
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
        arguments = reserve_arguments.parse_args()
        try:
            attribute_who = arguments["who"]
            application = attribute_who.split(" - ")[0]
            user = attribute_who.split(" - ")[1]
            request_host = attribute_who.split(" - ")[2]
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
        logger.debug("Before RESERVE operation")
        device_state = get_device_status_from_registrar(registrar_actor, device_id)
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
        ):
            logger.debug("After RESERVE operation")
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: get_device_status_from_registrar(registrar_actor, device_id),
            }
        if status in (
            Status.NOT_FOUND,
            Status.IS_NOT_FOUND,
        ):
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
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
        logger.debug("FreeDevice %s", device_id)
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
        if status in (
            Status.OK,
            Status.OK_SKIPPED,
            Status.OK_UPDATED,
            Status.OCCUPIED,
        ):
            logger.debug("After FREE operation")
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: get_device_status_from_registrar(registrar_actor, device_id),
            }
        return {
            "Error code": status.value,
            "Error": str(status),
            device_id: {},
        }


@hosts_ns.route("/")
class Hosts(Resource):
    """Endpoint for getting the list of active hosts"""

    @api.marshal_list_with(host)
    def get(self):
        """List available hosts"""
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
        return get_hosts(registrar_actor)


@instruments_ns.route("/")
class Instruments(Resource):
    """Endpoint for getting the list of active devices"""

    def _instrument(self, device_id, device_status):
        try:
            instr_id = short_id(device_id)
            serial_number = device_status["Identification"]["Serial number"]
            firmware_version = device_status["Identification"]["Firmware version"]
            instr_host = device_status["Identification"]["Host"]
        except AttributeError:
            return None
        return Instrument(
            instr_id=instr_id,
            serial_number=serial_number,
            firmware_version=firmware_version,
            host=instr_host,
        )

    @api.marshal_list_with(instrument)
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
        response = []
        for device_id, device_status in get_device_statuses(registrar_actor).items():
            response.append(self._instrument(device_id, device_status))
        return response


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
        arguments = values_arguments.parse_args()
        component_id = arguments["component"]
        sensor_id = arguments["sensor"]
        measurand_id = arguments["measurand"]
        logger.info(
            "Request value %d/%d/%d of %s",
            component_id,
            sensor_id,
            measurand_id,
            device_id,
        )
        device_state = get_device_status_from_registrar(registrar_actor, device_id)
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
                    timeout=TIMEOUT,
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
                    cluster_actor, GetLocalPortsMsg(), timeout=TIMEOUT
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
                    cluster_actor, GetUsbPortsMsg(), timeout=TIMEOUT
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
                    timeout=TIMEOUT,
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnNativePortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@ports_ns.route("/loop")
@ports_ns.param("port", "ID of the serial port as gathered from the `/ports` endpoint")
class GetLoopPort(Resource):
    """Start polling on the given port"""

    @api.expect(ports_arguments, validate=True)
    def get(self):
        """Add the serial port to the list of ports that shall be polled for
        connected SARAD instruments. Usually these are ports with external
        USB/RS-232 adapters.

        For Linux devices, replace slash in string by %2F.
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
        try:
            port = request.args.get("port").replace("%2F", "/").strip('"')
        except (IndexError, AttributeError):
            status = Status.ATTRIBUTE_ERROR
        else:
            status = Status.OK
        with ActorSystem().private() as get_loop_port:
            try:
                reply = get_loop_port.ask(
                    cluster_actor,
                    AddPortToLoopMsg(port),
                    timeout=TIMEOUT,
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnLoopPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return reply.ports


@ports_ns.route("/stop")
@ports_ns.param("port", "ID of the serial port as gathered from the `/ports` endpoint")
class GetStopPort(Resource):
    """Stop polling on the given port"""

    @api.expect(ports_arguments, validate=True)
    def get(self):
        """Remove the serial port from the list of ports that shall be polled for
        connected SARAD instruments.

        For Linux devices, replace slash in string by %2F.
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
        try:
            port = request.args.get("port").replace("%2F", "/").strip('"')
        except (IndexError, AttributeError):
            status = Status.ATTRIBUTE_ERROR
        else:
            status = Status.OK
        with ActorSystem().private() as get_stop_port:
            try:
                reply = get_stop_port.ask(
                    cluster_actor,
                    RemovePortFromLoopMsg(port),
                    timeout=TIMEOUT,
                )
            except ConnectionResetError:
                reply = None
        reply_is_corrupted = check_msg(reply, ReturnLoopPortsMsg)
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
                    timeout=TIMEOUT,
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
