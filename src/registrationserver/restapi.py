"""REST API -- the interface to the SARAD app

:Created:
    2020-10-02

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-restapi.puml

"""

import re
import socket
import sys
import time

from flask import Flask, Response, json, request
from thespian.actors import (Actor, ActorSystem,  # type: ignore
                             Thespian_ActorStatus)
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)

from registrationserver.actor_messages import (AddPortToLoopMsg, FreeDeviceMsg,
                                               GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetUsbPortsMsg,
                                               RemovePortFromLoopMsg,
                                               RescanMsg, ReservationStatusMsg,
                                               ReserveDeviceMsg,
                                               ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg, Status)
from registrationserver.config import mqtt_config
from registrationserver.helpers import (get_actor, get_device_status,
                                        get_device_statuses)
from registrationserver.logger import logger  # type: ignore
from registrationserver.shutdown import system_shutdown

logger.debug("%s -> %s", __package__, __file__)

MATCHID = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")


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
    @api.route("/shutdown", methods=["GET"])
    def shutdown():
        """Allows to shutdown the Registration Server."""
        system_shutdown()
        return "Registration Server going down for restart..."

    @staticmethod
    @api.route("/list", methods=["GET"])
    @api.route("/list/", methods=["GET"])
    def get_list():
        """Path for getting the list of active devices"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        return Response(
            response=json.dumps(get_device_statuses(registrar_actor)),
            status=200,
            mimetype="application/json",
        )

    @staticmethod
    @api.route("/scan", methods=["GET"])
    @api.route("/scan/", methods=["GET"])
    def scan_for_new_instr():
        """Refresh the list of active devices"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        cluster_actor = get_actor(registrar_actor, "cluster")
        ActorSystem().tell(cluster_actor, RescanMsg())
        status = Status.OK
        answer = {
            "Error code": status.value,
            "Error": str(status),
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
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        if not MATCHID.fullmatch(device_id):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        answer[device_id] = get_device_status(registrar_actor, device_id)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list/<device_id>/reserve", methods=["GET"])
    def reserve_device(device_id):
        """Path for reserving a single active device"""
        # Collect information about who sent the request.
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        try:
            attribute_who = request.args.get("who").strip('"')
            app = attribute_who.split(" - ")[0]
            user = attribute_who.split(" - ")[1]
        except (IndexError, AttributeError):
            logger.error("Reserve request without proper who attribute.")
            status = Status.ATTRIBUTE_ERROR
            answer = {
                "Error code": status.value,
                "Error": str(status),
                device_id: {},
            }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        try:
            logger.debug(request.environ["REMOTE_ADDR"])
            request_host = socket.gethostbyaddr(request.environ["REMOTE_ADDR"])[0]
        except socket.herror:
            request_host = request.environ["REMOTE_ADDR"]
        logger.info(
            "Request reservation of %s for %s@%s",
            device_id,
            attribute_who,
            request_host,
        )
        if not MATCHID.fullmatch(device_id):
            return json.dumps({"Error": "Wronly formated ID"})
        device_state = get_device_status(registrar_actor, device_id)
        if (
            not "_rfc2217" in device_id
            and not "mqtt" in device_id
            and not "local" in device_id
        ) or device_state == {}:
            logger.error("Requested service not supported by actor system.")
            status = Status.NOT_FOUND
            answer = {"Error code": status.value, "Error": str(status), device_id: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        # send RESERVE message to device actor
        device_actor = get_actor(registrar_actor, device_id)
        with ActorSystem().private() as reserve_sys:
            reserve_return = reserve_sys.ask(
                device_actor, ReserveDeviceMsg(request_host, user, app), 10
            )
        reply_is_corrupted = check_msg(reserve_return, ReservationStatusMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        status = reserve_return.status
        if status in (Status.OK, Status.OK_SKIPPED, Status.OK_UPDATED, Status.OCCUPIED):
            answer = {"Error code": status.value, "Error": str(status)}
            answer[device_id] = get_device_status(registrar_actor, device_id)
        else:
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status), device_id: {}}
            system_shutdown()
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list/<device_id>/free", methods=["GET"])
    def free_device(device_id):
        """Path for freeing a single active device"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        device_state = get_device_status(registrar_actor, device_id)
        if device_state == {}:
            status = Status.NOT_FOUND
        elif (device_state.get("Reservation", None) is None) or (
            device_state["Reservation"].get("Active") is False
        ):
            status = Status.OK_SKIPPED
        else:
            device_actor = get_actor(registrar_actor, device_id)
            logger.debug("Ask device actor to FREE...")
            free_return = ActorSystem().ask(device_actor, FreeDeviceMsg(), 10)
            reply_is_corrupted = check_msg(free_return, ReservationStatusMsg)
            if reply_is_corrupted:
                return reply_is_corrupted
            status = free_return.status
        answer = {"Error code": status.value, "Error": str(status), device_id: {}}
        if status in (Status.OK, Status.OCCUPIED):
            answer[device_id] = get_device_status(registrar_actor, device_id)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports", methods=["GET"])
    @api.route("/ports/", methods=["GET"])
    def getlocalports():
        """Lists Local Ports, Used for Testing atm"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, GetLocalPortsMsg(), 10)
        reply_is_corrupted = check_msg(reply, ReturnLocalPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return Response(
            response=json.dumps(reply.ports), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/<port>/loop", methods=["GET"])
    def getloopport(port):
        """Loops Local Ports, Used for Testing"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, AddPortToLoopMsg(port), 10)
        reply_is_corrupted = check_msg(reply, ReturnLoopPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return Response(
            response=json.dumps(reply.ports), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/<port>/stop", methods=["GET"])
    def getstopport(port):
        """Loops Local Ports, Used for Testing"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, RemovePortFromLoopMsg(port), 10)
        reply_is_corrupted = check_msg(reply, ReturnLoopPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return Response(
            response=json.dumps(reply.ports), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/list-usb", methods=["GET"])
    def getusbports():
        """Loops Local Ports, Used for Testing"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, GetUsbPortsMsg(), 10)
        reply_is_corrupted = check_msg(reply, ReturnUsbPortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return Response(
            response=json.dumps(reply.ports), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports/list-native", methods=["GET"])
    def getnativeports():
        """Loops Local Ports, Used for Testing"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, GetNativePortsMsg(), 10)
        reply_is_corrupted = check_msg(reply, ReturnNativePortsMsg)
        if reply_is_corrupted:
            return reply_is_corrupted
        return Response(
            response=json.dumps(reply.ports), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/status/<actor_id>", methods=["GET"])
    def getstatus(actor_id):
        """Ask actor system to output actor status to debug log"""
        registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
        actor_address = get_actor(registrar_actor, actor_id)
        reply = ActorSystem().ask(
            actorAddr=actor_address, msg=Thespian_StatusReq(), timeout=10
        )
        reply_is_corrupted = check_msg(reply, Thespian_ActorStatus)
        if reply_is_corrupted:
            return reply_is_corrupted

        class Temp:
            # pylint: disable=too-few-public-methods
            """Needed for formatStatus"""

            write = logger.debug

        formatStatus(reply, tofd=Temp())
        answer = {"Error code": 0}
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    def run(self, host=None, port=None, debug=None, load_dotenv=True):
        """Start the API"""
        success = False
        retry_interval = mqtt_config.get("RETRY_INTERVAL", 60)
        while not success:
            try:
                logger.info("Starting API at %s:%d", host, port)
                std = sys.stdout
                sys.stdout = RestApi.Dummy
                self.api.run(host=host, port=port, debug=debug, load_dotenv=load_dotenv)
                sys.stdout = std
                success = True
            except OSError as exception:
                logger.critical(exception)
                time.sleep(retry_interval)
