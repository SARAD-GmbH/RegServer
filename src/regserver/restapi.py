"""REST API -- the interface to the SARAD app

:Created:
    2020-10-02

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import os
from datetime import datetime, timedelta, timezone

from flask import Flask, request
from flask_restx import Api, Resource, fields, inputs, reqparse  # type: ignore
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import Thespian_ActorStatus
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)

from regserver.actor_messages import (AddPortToLoopMsg, BaudRateAckMsg,
                                      BaudRateMsg, GetLocalPortsMsg,
                                      GetNativePortsMsg, GetRecentValueMsg,
                                      GetUsbPortsMsg, InstrObj, RecentValueMsg,
                                      RemovePortFromLoopMsg, RescanAckMsg,
                                      RescanMsg, ReturnLocalPortsMsg,
                                      ReturnLoopPortsMsg, ReturnNativePortsMsg,
                                      ReturnUsbPortsMsg, SetRtcAckMsg,
                                      SetRtcMsg, ShutdownAckMsg, ShutdownMsg,
                                      StartMonitoringAckMsg,
                                      StartMonitoringMsg, Status,
                                      StopMonitoringAckMsg, StopMonitoringMsg,
                                      TransportTechnology)
from regserver.config import actor_config, config
from regserver.helpers import (check_msg, get_actor,
                               get_device_status_from_registrar,
                               get_device_statuses, get_hosts,
                               send_free_message, send_reserve_message,
                               short_id, transport_technology)
from regserver.logdef import LOGFILENAME
from regserver.logger import logger  # type: ignore
from regserver.shutdown import system_shutdown
from regserver.version import VERSION

STARTTIME = datetime.now(timezone.utc).replace(microsecond=0)
PASSWORD = "Diev5Pw."
TIMEOUT = timedelta(seconds=20)


app = Flask(__name__)
app.url_map.strict_slashes = False
api = Api(
    app,
    version="2.1",
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
host_model = api.model(
    "Host",
    {
        "host": fields.String(description="The FQDN of the host"),
        "is_id": fields.String(
            description="An alias identifying the Instrument Server."
            + " Given in the remote config."
        ),
        "state": fields.Integer(
            description="0 = offline; 1 = online, no instrument;"
            + " 2 = online, functional; 10 = offline, ungracefully"
        ),
        "transport_technology": fields.Integer(
            description="How is the instrument connected to this RegServer."
            + " 0 = local; 1 = LAN; 2 = MQTT; 3 = WiFi"
        ),
        "description": fields.String(
            description="Free text string describing the host"
        ),
        "place": fields.String(
            description="Name of the place where the host is situated"
        ),
        "latitude": fields.Float(
            description="Latitude of the place. Positive values are north, negatives are south"
        ),
        "longitude": fields.Float(
            description="Longitude of the place. Positive values are east, negatives are west"
        ),
        "altitude": fields.Integer(description="Altitude of the place."),
        "version": fields.String(
            description="Software revision of the SARAD Registration Server"
            + "service running on this host."
        ),
        "running_since": fields.DateTime(
            description="Date and time (UTC) of the latest restart"
            + "of the SARAD Registration Server service.",
            dt_format="iso8601",
        ),
        "link": fields.Url("hosts_host", absolute=True),
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
        "link": fields.Url("instruments_instrument", absolute=True),
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
    help=f"Requires 'age' to be a value between 0 and {config['NR_OF_LOG_FILES'] - 1}.",
    default=0,
    choices=list(range(config["NR_OF_LOG_FILES"])),
    trim=True,
)
start_arguments = reqparse.RequestParser()
start_arguments.add_argument(
    "start_time",
    type=inputs.datetime_from_iso8601,
    required=False,
    help="Datetime string in ISO format giving the time to start the monitoring mode at.\n"
    + "The string must contain the time zone information.",
)
baudrate_arguments = reqparse.RequestParser()
baudrate_arguments.add_argument(
    "rate",
    type=int,
    required=True,
    help="Set the baud rate for the serial interface to the instrument.",
    choices=[9600, 115200, 256000],
    trim=True,
)
ports_arguments = reqparse.RequestParser()
ports_arguments.add_argument("port", type=str, required=False)
values_arguments = reqparse.RequestParser()
values_arguments.add_argument(
    "component",
    type=int,
    required=True,
    help="Index of the component of the instrument containing the sensor.",
    trim=True,
)
values_arguments.add_argument(
    "sensor",
    type=int,
    required=True,
    help="Index of the sensor providing the wanted value.",
    trim=True,
)
values_arguments.add_argument(
    "measurand",
    type=int,
    required=True,
    help="Index of the measurand. The meaning is provided by the instrument description.\n"
    + "(e. g. 0 - recent, 1 - recent error, 2 - average, 3 - average error)",
    choices=[0, 1, 2, 3, 4],
    trim=True,
)

REGISTRAR_ACTOR = None


def set_registrar(registrar):
    """Set Registrar Actor"""
    global REGISTRAR_ACTOR  # pylint: disable=global-statement
    REGISTRAR_ACTOR = registrar
    logger.info("Registrar actor = %s", REGISTRAR_ACTOR)


@root_ns.route("/ping")
class Ping(Resource):
    # pylint: disable=too-few-public-methods
    """Request a sign of life to confirm that the host is online."""

    def post(self):
        """Request a sign of life to confirm that the host is online."""
        logger.debug("Ping received")
        return {
            "service": "SARAD Registration Server",
            "version": VERSION,
            "running_since": STARTTIME.isoformat(timespec="seconds"),
            "system_base": actor_config["systemBase"],
        }


@root_ns.route("/log")
@root_ns.param(
    "age",
    "May be 0 for the current log or 1 for the backup of the log "
    + "from the last run of Registration Server Service.",
)
class Log(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint to show the content of the log file"""

    @api.expect(log_arguments, validate=True)
    def get(self):
        """Show the content of the log file"""
        logger.debug("Log request received")
        attribute_age = log_arguments.parse_args()
        age = attribute_age["age"]
        if age:
            log_file_name = f"{LOGFILENAME}.{age}"
        else:
            log_file_name = LOGFILENAME
        if os.path.isfile(log_file_name):
            with open(log_file_name, encoding="utf8") as log_file:
                lines = log_file.readlines()
            resp = [line.rstrip("\n") for line in lines]
            return resp
        return f"{log_file_name} doesn't exist."


@root_ns.route("/restart")
@root_ns.param(
    "password",
    "This is not really a password since it is given here. "
    + "It is only there to prevent restart by mistake.",
)
class Shutdown(Resource):
    # pylint: disable=too-few-public-methods
    """Restart the SARAD Registration Server."""

    @api.expect(shutdown_arguments, validate=True)
    def post(self):
        """Restart the SARAD Registration Server.

        The service will be terminated with error and thus be restarted
        automatically by the Service Manager (Windows) or Systemd (Linux)
        resp.

        *WARNING*
        Calling this method from here will forward the Restart command
        to the local host and to all remote hosts! This might affect other users.
        """
        remote_addr = request.remote_addr
        remote_user = request.remote_user
        args = shutdown_arguments.parse_args()
        logger.info(
            "Shutdown by user intervention from %s",
            remote_addr,
        )
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        with ActorSystem().private() as restart_sys:
            try:
                reply = restart_sys.ask(
                    REGISTRAR_ACTOR,
                    ShutdownMsg(password=args["password"], host=None),
                    timeout=timedelta(seconds=60),
                )
            except ConnectionResetError as exception:
                logger.debug(exception)
                reply = None
        reply_is_corrupted = check_msg(reply, ShutdownAckMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return {
            "Error code": reply.status.value,
            "Error": str(reply.status),
            "Notification": "Registration Server going down for restart.",
            "Requesting host": remote_addr,
            "Requesting user": remote_user,
        }


@root_ns.route("/scan")
class Scan(Resource):
    # pylint: disable=too-few-public-methods
    """Refresh the list of active devices"""

    def post(self):
        """Refresh the list of active devices.

        This might be required for SARAD instruments that are connected via
        USB/RS-232 adapters like the instruments of the DOSEman family that are
        connected via their IR cradle. The Registration Server is detecting
        instruments by their USB connection or, if configured, by polling. This
        function was implemented as fallback.

        *WARNING*
        Calling this method from here will forward the Scan command
        to the local host and to all remote hosts! This might affect other users.
        """
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        with ActorSystem().private() as scan_sys:
            try:
                reply = scan_sys.ask(
                    REGISTRAR_ACTOR, RescanMsg(), timeout=timedelta(seconds=60)
                )
            except ConnectionResetError as exception:
                logger.debug(exception)
                reply = None
        reply_is_corrupted = check_msg(reply, RescanAckMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return {
            "Error code": reply.status.value,
            "Error": str(reply.status),
        }


# @api.deprecated
@list_ns.route("/")
class List(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for getting the list of active devices."""

    def get(self):
        """List available SARAD instruments"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        return get_device_statuses(REGISTRAR_ACTOR)


# @api.deprecated
@list_ns.route("/<string:device_id>")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
class ListDevice(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for getting information for a single active device"""

    def get(self, device_id):
        """Get indentifying information for a single available instrument."""
        logger.debug("ListDevice %s", device_id)
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        return {device_id: get_device_status_from_registrar(REGISTRAR_ACTOR, device_id)}


# @api.deprecated
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
    # pylint: disable=too-few-public-methods
    """Endpoint for reserving an available instrument"""

    @api.expect(reserve_arguments, validate=True)
    def get(self, device_id):
        """Reserve an available instrument so that nobody else can use it."""
        # Collect information about who sent the request.
        logger.debug("ReserveDevice %s", device_id)
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
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
            who = {
                "app": attribute_who.split(" - ")[0],
                "user": attribute_who.split(" - ")[1],
                "host": attribute_who.split(" - ")[2],
            }
        except (IndexError, AttributeError):
            logger.warning("Reserve request without proper who attribute.")
            status = Status.ATTRIBUTE_ERROR
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
            }
        return self.reserve_device(device_id, who, True)

    def reserve_device(self, device_id, who, create_redirector):
        """The actual reserve method. It will be called after checking all
        boundary conditions."""
        logger.info(
            "Request reservation of %s for %s",
            device_id,
            who,
        )
        device_state = get_device_status_from_registrar(REGISTRAR_ACTOR, device_id)
        if (
            transport_technology(device_id)
            not in [
                TransportTechnology.LOCAL,
                TransportTechnology.IS1,
                TransportTechnology.LAN,
                TransportTechnology.MQTT,
            ]
        ) or (device_state == {}):
            logger.error("Requested service not supported by actor system.")
            status = Status.NOT_SUPPORTED
        else:
            status = send_reserve_message(
                device_id,
                REGISTRAR_ACTOR,
                who["host"],
                who["user"],
                who["app"],
                create_redirector,
            )
        if status in (
            Status.OK,
            Status.OK_SKIPPED,
            Status.OK_UPDATED,
            Status.OCCUPIED,
        ):
            device_status = get_device_status_from_registrar(REGISTRAR_ACTOR, device_id)
            logger.debug("After RESERVE registrar said: %s", device_status)
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: device_status,
            }
        if status in (
            Status.NOT_FOUND,
            Status.IS_NOT_FOUND,
            Status.UNKNOWN_PORT,
        ):
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
            }
        logger.critical("No response from Device Actor. -> Emergency shutdown")
        system_shutdown()
        return {
            "Error code": status.value,
            "Error": str(status),
            device_id: {},
            "Notification": "Registration Server going down for restart.",
            "Requester": "Emergency shutdown",
        }


# @api.deprecated
@list_ns.route("/<string:device_id>/free")
@list_ns.param(
    "device_id",
    "ID of the connected device as gathered as key from the `/list` endpoint",
)
class FreeDevice(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for freeing a reserved instrument"""

    def get(self, device_id):
        """Free/release a device that was reserved before"""
        logger.debug("FreeDevice %s", device_id)
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
        else:
            is_status = send_free_message(device_id, REGISTRAR_ACTOR)
            if is_status == Status.CRITICAL:
                status = Status.IS_NOT_FOUND
            else:
                status = is_status
        if status == Status.CRITICAL:
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
            device_status = get_device_status_from_registrar(REGISTRAR_ACTOR, device_id)
            logger.debug("After FREE registrar said: %s", device_status)
            return {
                "Error code": status.value,
                "Error": str(status),
                device_id: device_status,
            }
        return {
            "Error code": status.value,
            "Error": str(status),
            device_id: {},
        }


@hosts_ns.route("/")
class Hosts(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for getting the list of active hosts"""

    @api.marshal_list_with(host_model)
    def get(self):
        """List available hosts"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        return get_hosts(REGISTRAR_ACTOR)


@hosts_ns.route("/<string:host>")
@hosts_ns.param(
    "host",
    "FQDN of the host",
)
@hosts_ns.response(404, "Host not found")
class Host(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for one active host"""

    @api.marshal_with(host_model)
    def get(self, host):
        """Get information about one host"""
        if REGISTRAR_ACTOR is None:
            return api.abort(404)
        for host_object in get_hosts(REGISTRAR_ACTOR):
            if host_object.host == host:
                return host_object
        return api.abort(404)


@hosts_ns.route("/<string:host>/restart")
@hosts_ns.param(
    "password",
    "This is not really a password since it is given here. "
    + "It is only there to prevent restart by mistake.",
)
@hosts_ns.response(404, "Host not found")
class ShutdownHost(Resource):
    # pylint: disable=too-few-public-methods
    """Restart the SARAD Registration Server."""

    @api.expect(shutdown_arguments, validate=True)
    def post(self, host):
        """Restart the SARAD Registration Server.

        The service will be terminated with error and thus be restarted
        automatically by the Service Manager (Windows) or Systemd (Linux)
        resp.
        """
        remote_addr = request.remote_addr
        remote_user = request.remote_user
        args = shutdown_arguments.parse_args()
        logger.info(
            "Shutdown by user intervention from %s",
            remote_addr,
        )
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        for host_object in get_hosts(REGISTRAR_ACTOR):
            if host_object.host == host:
                with ActorSystem().private() as restart_sys:
                    try:
                        reply = restart_sys.ask(
                            REGISTRAR_ACTOR,
                            ShutdownMsg(password=args["password"], host=host),
                            timeout=timedelta(seconds=60),
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                reply_is_corrupted = check_msg(reply, ShutdownAckMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                return {
                    "Error code": reply.status.value,
                    "Error": str(reply.status),
                    "Notification": "Registration Server going down for restart.",
                    "Requesting host": remote_addr,
                    "Requesting user": remote_user,
                }
        return api.abort(404)


@hosts_ns.route("/<string:host>/scan")
class ScanHost(Resource):
    # pylint: disable=too-few-public-methods
    """Refresh the list of active devices"""

    def post(self, host):
        """Refresh the list of active devices.

        This might be required for SARAD instruments that are connected via
        USB/RS-232 adapters like the instruments of the DOSEman family that are
        connected via their IR cradle. The Registration Server is detecting
        instruments by their USB connection or, if configured, by polling. This
        function was implemented as fallback.
        """
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        for host_object in get_hosts(REGISTRAR_ACTOR):
            if host_object.host == host:
                with ActorSystem().private() as scan_sys:
                    try:
                        reply = scan_sys.ask(
                            REGISTRAR_ACTOR,
                            RescanMsg(host),
                            timeout=timedelta(seconds=60),
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                reply_is_corrupted = check_msg(reply, RescanAckMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                return {
                    "Error code": reply.status.value,
                    "Error": str(reply.status),
                }
        return api.abort(404)


@instruments_ns.route("/")
class Instruments(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for getting the list of active devices"""

    def _instrument(self, device_id, device_status):
        try:
            instr_id = short_id(device_id)
            serial_number = device_status["Identification"].get("Serial number", 0)
            firmware_version = device_status["Identification"].get(
                "Firmware version", 0
            )
            instr_host = device_status["Identification"].get("Host", "unknown")
        except AttributeError:
            return api.abort(404)
        return InstrObj(
            instr_id=instr_id,
            serial_number=serial_number,
            firmware_version=firmware_version,
            host=instr_host,
        )

    @api.marshal_list_with(instrument)
    def get(self):
        """List available SARAD instruments"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        response = []
        for device_id, device_status in get_device_statuses(REGISTRAR_ACTOR).items():
            response.append(self._instrument(device_id, device_status))
        return response


@instruments_ns.route("/<string:instr_id>")
@instruments_ns.param(
    "instr_id",
    "Id of the instrument",
)
@instruments_ns.response(404, "Instrument not found")
class Instrument(Resource):
    # pylint: disable=too-few-public-methods
    """Endpoint for one active instrument"""

    def _instrument(self, device_id, device_status):
        try:
            instr_id = short_id(device_id)
            serial_number = device_status["Identification"].get("Serial number", 0)
            firmware_version = device_status["Identification"].get(
                "Firmware version", 0
            )
            instr_host = device_status["Identification"].get("Host", "unknown")
        except AttributeError:
            return api.abort(404)
        return InstrObj(
            instr_id=instr_id,
            serial_number=serial_number,
            firmware_version=firmware_version,
            host=instr_host,
        )

    @api.marshal_with(instrument)
    def get(self, instr_id):
        """Get information about one instrument"""
        if REGISTRAR_ACTOR is None:
            return api.abort(404)
        for device_id, device_status in get_device_statuses(REGISTRAR_ACTOR).items():
            if short_id(device_id) == instr_id:
                return self._instrument(device_id, device_status)
        return api.abort(404)


@instruments_ns.route("/<string:instr_id>/start-monitoring")
@instruments_ns.param(
    "start_time",
    "UTC to start the measurement.",
)
class StartMonitoring(Resource):
    # pylint: disable=too-few-public-methods
    """Start the monitoring mode at the given instrument."""

    @api.expect(start_arguments, validate=True)
    def post(self, instr_id):
        """Start the monitoring mode at the given instrument.

        'Offset' in the response body is giving back the time difference
        between now and the time the monitoring mode will take effect. If this
        value is negative, the monitoring mode will be started instantly.

        Use the FREE request to suspend or the STOP-MONITORING request to
        terminate the monitoring mode.

        """
        args = start_arguments.parse_args()
        start_time = args["start_time"]
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        if REGISTRAR_ACTOR is None:
            return api.abort(404)
        for device_id in get_device_statuses(REGISTRAR_ACTOR):
            if short_id(device_id) == instr_id:
                with ActorSystem().private() as start_sys:
                    try:
                        reply = start_sys.ask(
                            REGISTRAR_ACTOR,
                            StartMonitoringMsg(
                                instr_id=instr_id, start_time=start_time
                            ),
                            timeout=timedelta(seconds=60),
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                reply_is_corrupted = check_msg(reply, StartMonitoringAckMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                return {
                    "Error code": reply.status.value,
                    "Error": str(reply.status),
                    "Offset": reply.offset.total_seconds(),
                }
        return api.abort(404)


@instruments_ns.route("/<string:instr_id>/stop-monitoring")
class StopMonitoring(Resource):
    # pylint: disable=too-few-public-methods
    """Stop the monitoring mode at the given instrument."""

    def post(self, instr_id):
        """Terminate the monitoring mode at the given instrument.

        PLEASE NOTE: This won't stop the measuring cycle itself. It only
        terminates the regular publishing of measuring values to the MQTT
        broker. Please use either dVision (for DACM instruments) or Radon
        Vision (for instruments of the Radon Scout family or RTM 1688-2) to
        stop the running cycle resp. the measuring campaign.

        """
        if REGISTRAR_ACTOR is None:
            return api.abort(404)
        for device_id in get_device_statuses(REGISTRAR_ACTOR):
            if short_id(device_id) == instr_id:
                with ActorSystem().private() as stop_sys:
                    try:
                        reply = stop_sys.ask(
                            REGISTRAR_ACTOR,
                            StopMonitoringMsg(instr_id=instr_id),
                            timeout=timedelta(seconds=60),
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                reply_is_corrupted = check_msg(reply, StopMonitoringAckMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                return {
                    "Error code": reply.status.value,
                    "Error": str(reply.status),
                }
        return api.abort(404)


@instruments_ns.route("/<string:instr_id>/baudrate")
@instruments_ns.param(
    "rate",
    "Baud rate of the serial connection to the instrument.",
)
class BaudRate(Resource):
    # pylint: disable=too-few-public-methods
    """Set the baud rate of serial connection."""

    @api.expect(baudrate_arguments, validate=True)
    def put(self, instr_id):
        """Change the baud rate at the given instrument."""
        args = baudrate_arguments.parse_args()
        if REGISTRAR_ACTOR is None:
            return api.abort(404)
        for device_id in get_device_statuses(REGISTRAR_ACTOR):
            if short_id(device_id) == instr_id:
                with ActorSystem().private() as start_sys:
                    try:
                        reply = start_sys.ask(
                            REGISTRAR_ACTOR,
                            BaudRateMsg(baud_rate=args["rate"], instr_id=instr_id),
                            timeout=timedelta(seconds=60),
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                reply_is_corrupted = check_msg(reply, BaudRateAckMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                return {
                    "Error code": reply.status.value,
                    "Error": str(reply.status),
                }
        return api.abort(404)


@instruments_ns.route("/<string:instr_id>/set-rtc")
class SetRtc(Resource):
    # pylint: disable=too-few-public-methods
    """Set the realtime clock on the given instrument."""

    def post(self, instr_id):
        """Set the realtime clock on the given instrument.

        'UTC offset' in the response body is giving back the UTC offset
        (time zone) that was used to set the clock. null = undefined, -13 =
        unknown (not provided by remote host). 'Wait' is the time between now
        and the setup taking effect.

        """
        if REGISTRAR_ACTOR is None:
            return api.abort(404)
        for device_id in get_device_statuses(REGISTRAR_ACTOR):
            if short_id(device_id) == instr_id:
                with ActorSystem().private() as rtc_sys:
                    try:
                        reply = rtc_sys.ask(
                            REGISTRAR_ACTOR,
                            SetRtcMsg(instr_id=instr_id),
                            timeout=timedelta(seconds=60),
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                reply_is_corrupted = check_msg(reply, SetRtcAckMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                return {
                    "Error code": reply.status.value,
                    "Error": str(reply.status),
                    "UTC offset": reply.utc_offset,
                    "Wait": reply.wait,
                }
        return api.abort(404)


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
    # pylint: disable=too-few-public-methods
    """Endpoint to get measuring values from a SARAD instrument"""

    @api.expect(values_arguments, validate=True)
    def get(self, device_id):
        # pylint: disable=too-many-return-statements, too-many-branches
        """Gather a measuring value from a SARAD instrument"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        arguments = values_arguments.parse_args()
        logger.info(
            "Request value %d/%d/%d of %s",
            arguments["component"],
            arguments["sensor"],
            arguments["measurand"],
            device_id,
        )
        device_state = get_device_status_from_registrar(REGISTRAR_ACTOR, device_id)
        if (device_state == {}) or (
            transport_technology(device_id)
            not in [
                TransportTechnology.LOCAL,
                TransportTechnology.IS1,
                TransportTechnology.LAN,
                TransportTechnology.MQTT,
            ]
        ):
            logger.error(
                "Request only supported for local, LAN, IS1, MQTT and ZigBee instruments."
            )
            status = Status.NOT_SUPPORTED
            notification = (
                "Only supported for local, LAN, IS1, MQTT and ZigBee instruments"
            )
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": notification,
            }
        # send GetRecentValueMsg to device actor
        device_actor = get_actor(REGISTRAR_ACTOR, device_id)
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
                    GetRecentValueMsg(
                        arguments["component"],
                        arguments["sensor"],
                        arguments["measurand"],
                    ),
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
        if value_return.status in [Status.INDEX_ERROR, Status.OCCUPIED]:
            if value_return.status == Status.OCCUPIED:
                notification = "The instrument is occupied by somebody else."
            elif value_return.status == Status.INDEX_ERROR:
                notification = "The requested measurand is not available."
            return {
                "Error code": value_return.status.value,
                "Error": str(value_return.status),
                "Notification": notification,
            }
        if value_return.status in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            if value_return.status == Status.NOT_FOUND:
                notification = "The instrument does not reply."
            elif value_return.status == Status.IS_NOT_FOUND:
                notification = (
                    "The instrument server hosting the instrument cannot be reached."
                )
            return {
                "Error code": value_return.status.value,
                "Error": str(value_return.status),
                "Notification": notification,
            }
        if value_return.gps is None:
            gps_dict = None
        else:
            gps_dict = {
                "Valid": value_return.gps.valid,
                "Latitude": value_return.gps.latitude,
                "Longitude": value_return.gps.longitude,
                "Altitude": value_return.gps.altitude,
                "Deviation": value_return.gps.deviation,
            }
        return {
            "Device Id": device_id,
            "Component id": arguments["component"],
            "Component name": value_return.component_name,
            "Sensor id": arguments["sensor"],
            "Sensor name": value_return.sensor_name,
            "Measurand id": arguments["measurand"],
            "Measurand name": value_return.measurand_name,
            "Measurand": value_return.measurand,
            "Operator": value_return.operator,
            "Value": value_return.value,
            "Unit": value_return.unit,
            "Timestamp": value_return.timestamp,
            "UTC offset": value_return.utc_offset,
            "Sample interval": value_return.sample_interval,
            "Fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "GPS": gps_dict,
        }


@ports_ns.route("/")
class GetLocalPorts(Resource):
    # pylint: disable=too-few-public-methods
    """Lists local serial ports"""

    def get(self):
        """Lists local serial ports"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(REGISTRAR_ACTOR, "cluster")
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
    # pylint: disable=too-few-public-methods
    """List local USB devices with virtual serial ports"""

    def get(self):
        """List local USB devices with virtual serial ports"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(REGISTRAR_ACTOR, "cluster")
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
    # pylint: disable=too-few-public-methods
    """List local RS-232 ports"""

    def get(self):
        """List local RS-232 ports"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(REGISTRAR_ACTOR, "cluster")
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
    # pylint: disable=too-few-public-methods
    """Start polling on the given port"""

    @api.expect(ports_arguments, validate=True)
    def get(self):
        """Add the serial port to the list of ports that shall be polled for
        connected SARAD instruments. Usually these are ports with external
        USB/RS-232 adapters.

        For Linux devices, replace slash in string by %2F.
        """
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(REGISTRAR_ACTOR, "cluster")
        try:
            port = request.args.get("port", "").replace("%2F", "/").strip('"')
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
    # pylint: disable=too-few-public-methods
    """Stop polling on the given port"""

    @api.expect(ports_arguments, validate=True)
    def get(self):
        """Remove the serial port from the list of ports that shall be polled for
        connected SARAD instruments.

        For Linux devices, replace slash in string by %2F.
        """
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        cluster_actor = get_actor(REGISTRAR_ACTOR, "cluster")
        try:
            port = request.args.get("port", "").replace("%2F", "/").strip('"')
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
    # pylint: disable=too-few-public-methods
    """Ask Actor System to output Actor status to debug log"""

    def get(self, actor_id):
        """Ask Actor System to output Actor status to debug log"""
        if REGISTRAR_ACTOR is None:
            status = Status.CRITICAL
            return {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
        actor_address = get_actor(REGISTRAR_ACTOR, actor_id)
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
