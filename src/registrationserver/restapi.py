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

from flask import Flask, Response, json, request
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import Thespian_ActorStatus
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)
from waitress import serve

from registrationserver.actor_messages import (AddPortToLoopMsg, FreeDeviceMsg,
                                               GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetRecentValueMsg,
                                               GetUsbPortsMsg, RecentValueMsg,
                                               RemovePortFromLoopMsg,
                                               RescanFinishedMsg, RescanMsg,
                                               ReservationStatusMsg,
                                               ReserveDeviceMsg,
                                               ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg, Status)
from registrationserver.config import mqtt_config
from registrationserver.helpers import (get_actor, get_device_status,
                                        get_device_statuses,
                                        get_registrar_actor, sanitize_hn,
                                        transport_technology)
from registrationserver.logger import logger  # type: ignore
from registrationserver.shutdown import system_shutdown

# logger.debug("%s -> %s", __package__, __file__)

STARTTIME = datetime.utcnow()


def check_msg(return_message, message_object_type):
    """Check whether the returned message is of the expected type.

    Args:
        return_message: Actor message object from the last ask.
        message_object_type: The expected object type for this request.

    Returns: Either a response to be published by Flask or False.
    """
    logger.debug("Returned with %s", return_message)
    if not isinstance(return_message, message_object_type):
        logger.critical("Got message object of unexpected type")
        logger.critical("-> Stop and shutdown system")
        status = Status.CRITICAL
        answer = {"Error code": status.value, "Error": str(status)}
        system_shutdown()
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )
    return False


class RestApi:
    """REST API

    delivers lists and info for devices,
    relays Reservation and Free requests to the device actors.
    """

    api = Flask(__name__)

    class Dummy:
        """Dummy output to ignore stdout"""

        @staticmethod
        def write(arg=None, **kwargs):
            """Does Nothing"""

        @staticmethod
        def flush(arg=None, **kwargs):
            """Does Nothing"""

    @staticmethod
    @api.route("/", methods=["GET"])
    @api.route("/ping", methods=["GET"])
    @api.route("/ping/", methods=["GET"])
    def ping():
        """Send a sign of life to confirm that the host is online."""
        logger.debug("Ping received")
        response = {"service": "SARAD Registration Server", "running_since": STARTTIME}
        return Response(
            response=json.dumps(response), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/shutdown", methods=["GET"])
    @api.route("/shutdown/", methods=["GET"])
    def shutdown():
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
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list", methods=["GET"])
    @api.route("/list/", methods=["GET"])
    def get_list():
        """Path for getting the list of active devices"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
            answer = get_device_statuses(registrar_actor)
        return Response(
            response=json.dumps(answer),
            status=200,
            mimetype="application/json",
        )

    @staticmethod
    @api.route("/scan", methods=["GET"])
    @api.route("/scan/", methods=["GET"])
    def scan_for_new_instr():
        """Refresh the list of active devices"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = {
                "Error code": reply.status.value,
                "Error": str(reply.status),
            }
        return Response(
            response=json.dumps(answer),
            status=200,
            mimetype="application/json",
        )

    @staticmethod
    @api.route("/list/<device_id>", methods=["GET"])
    @api.route("/list/<device_id>/", methods=["GET"])
    def get_device(device_id):
        """Path for getting information for a single active device"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            answer[device_id] = None
        else:
            answer = {}
            answer[device_id] = get_device_status(registrar_actor, device_id)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list/<device_id>/reserve", methods=["GET"])
    @api.route("/list/<device_id>/reserve/", methods=["GET"])
    def reserve_device(device_id):
        """Path for reserving a single active device"""
        # Collect information about who sent the request.
        error = False
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            error = True
        else:
            try:
                attribute_who = request.args.get("who").strip('"')
                app = attribute_who.split(" - ")[0]
                user = attribute_who.split(" - ")[1]
                request_host = sanitize_hn(attribute_who.split(" - ")[2])
            except (IndexError, AttributeError):
                logger.warning("Reserve request without proper who attribute.")
                status = Status.ATTRIBUTE_ERROR
                answer = {
                    "Error code": status.value,
                    "Error": str(status),
                    device_id: {},
                }
                error = True
        if error:
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
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
            answer = {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
            }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        # send RESERVE message to device actor
        device_actor = get_actor(registrar_actor, device_id)
        if device_actor is None:
            status = Status.NOT_FOUND
        else:
            with ActorSystem().private() as reserve_sys:
                try:
                    reserve_return = reserve_sys.ask(
                        device_actor,
                        ReserveDeviceMsg(request_host, user, app),
                        timeout=timedelta(seconds=10),
                    )
                except ConnectionResetError:
                    reserve_return = None
            if reserve_return is None:
                status = Status.CRITICAL
                logger.error("No response from Actor System.")
            else:
                reply_is_corrupted = check_msg(reserve_return, ReservationStatusMsg)
                if reply_is_corrupted:
                    return reply_is_corrupted
                if reserve_return.status in [
                    Status.RESERVE_PENDING,
                    Status.FREE_PENDING,
                ]:
                    status = Status.NOT_FOUND
                else:
                    status = reserve_return.status
        if status in (
            Status.OK,
            Status.OK_SKIPPED,
            Status.OK_UPDATED,
            Status.OCCUPIED,
            Status.NOT_FOUND,
            Status.IS_NOT_FOUND,
        ):
            answer = {"Error code": status.value, "Error": str(status)}
            answer[device_id] = get_device_status(registrar_actor, device_id)
        else:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical(answer)
            system_shutdown()
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list/<device_id>/free", methods=["GET"])
    @api.route("/list/<device_id>/free/", methods=["GET"])
    def free_device(device_id):
        """Path for freeing a single active device"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
        else:
            device_state = get_device_status(registrar_actor, device_id)
            if (device_state == {}) or (
                device_actor := get_actor(registrar_actor, device_id)
            ) is None:
                status = Status.NOT_FOUND
            else:
                logger.info("Ask %s to FREE...", device_id)
                with ActorSystem().private() as free_dev:
                    try:
                        free_return = free_dev.ask(
                            device_actor,
                            FreeDeviceMsg(),
                            timeout=timedelta(seconds=10),
                        )
                    except ConnectionResetError as exception:
                        logger.error(exception)
                        free_return = None
                        status = Status.CRITICAL
                if free_return is not None:
                    reply_is_corrupted = check_msg(free_return, ReservationStatusMsg)
                    if reply_is_corrupted:
                        return reply_is_corrupted
                    if free_return.status in [
                        Status.RESERVE_PENDING,
                        Status.FREE_PENDING,
                    ]:
                        status = Status.NOT_FOUND
                    else:
                        status = free_return.status
        answer = {"Error code": status.value, "Error": str(status), device_id: {}}
        if status in (Status.OK, Status.OCCUPIED, Status.OK_SKIPPED):
            answer[device_id] = get_device_status(registrar_actor, device_id)
        elif status == Status.CRITICAL:
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/values/<device_id>", methods=["GET"])
    @api.route("/values/<device_id>/", methods=["GET"])
    def get_recent_value(device_id):
        """Path to get values of a special device"""
        error = False
        answer = {}
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
            error = True
        else:
            try:
                component_id = int(request.args.get("component").strip('"'))
                sensor_id = int(request.args.get("sensor").strip('"'))
                measurand_id = int(request.args.get("measurand").strip('"'))
            except (IndexError, AttributeError):
                logger.warning("Get recent values request without proper attributes.")
                status = Status.ATTRIBUTE_ERROR
                notification = "Requires component, sensor, measurand."
                answer = {
                    "Error code": status.value,
                    "Error": str(status),
                    "Notification": notification,
                }
                error = True
        if error:
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
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
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": notification,
            }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        # send GetRecentValueMsg to device actor
        device_actor = get_actor(registrar_actor, device_id)
        if device_actor is None:
            status = Status.NOT_FOUND
            answer = {
                "Error code": status.value,
                "Error": str(status),
            }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        with ActorSystem().private() as value_sys:
            try:
                value_return = value_sys.ask(
                    device_actor,
                    GetRecentValueMsg(component_id, sensor_id, measurand_id),
                    timeout=timedelta(seconds=10),
                )
            except ConnectionResetError:
                status = Status.CRITICAL
                answer = {
                    "Error code": status.value,
                    "Error": str(status),
                    "Notification": "Registration Server going down for restart.",
                    "Requester": "Emergency shutdown",
                }
                logger.critical("No response from Actor System. -> Emergency shutdown")
                system_shutdown()
                return Response(
                    response=json.dumps(answer), status=200, mimetype="application/json"
                )
        reply_is_corrupted = check_msg(value_return, RecentValueMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        if value_return.status == Status.INDEX_ERROR:
            answer = {
                "Error code": value_return.status.value,
                "Error": str(value_return.status),
                "Notification": "The requested measurand is not available.",
            }
        else:
            timestamp = (
                value_return.timestamp.isoformat(timespec="seconds") + "Z"
                if value_return.timestamp is not None
                else None
            )
            answer = {
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
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports", methods=["GET"])
    @api.route("/ports/", methods=["GET"])
    def getlocalports():
        """Lists Local Ports, Used for Testing atm"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = reply.ports
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/<port>/loop", methods=["GET"])
    def getloopport(port):
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = reply.ports
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/<port>/stop", methods=["GET"])
    def getstopport(port):
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = reply.ports
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/list-usb", methods=["GET"])
    def getusbports():
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = reply.ports
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/list-native", methods=["GET"])
    def getnativeports():
        """Loops Local Ports, Used for Testing"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = reply.ports
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/status/<actor_id>", methods=["GET"])
    def getstatus(actor_id):
        """Ask actor system to output actor status to debug log"""
        if (registrar_actor := get_registrar_actor()) is None:
            status = Status.CRITICAL
            answer = {
                "Error code": status.value,
                "Error": str(status),
                "Notification": "Registration Server going down for restart.",
                "Requester": "Emergency shutdown",
            }
            logger.critical("No response from Actor System. -> Emergency shutdown")
            system_shutdown()
        else:
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
            answer = {"Error code": status.value, "Error": str(status)}
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    def run(self, port=None):
        """Start the API"""
        success = False
        retry_interval = mqtt_config.get("RETRY_INTERVAL", 60)
        while not success:
            try:
                logger.info("Starting API at port %d", port)
                std = sys.stdout
                sys.stdout = RestApi.Dummy
                # self.api.run(host=host, port=port)
                serve(self.api, listen=f"*:{port}", threads=12)
                sys.stdout = std
                success = True
            except OSError as exception:
                logger.critical(exception)
                time.sleep(retry_interval)
