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
from thespian.actors import ActorSystem  # type: ignore
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)

from registrationserver.actor_messages import (AddPortToLoopMsg, AppType,
                                               FreeDeviceMsg, GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetUsbPortsMsg,
                                               RemovePortFromLoopMsg,
                                               ReservationStatusMsg,
                                               ReserveDeviceMsg,
                                               ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg, SetupMsg,
                                               Status)
from registrationserver.config import actor_config, config, mqtt_config
from registrationserver.helpers import (get_actor, get_device_status,
                                        get_device_statuses)
from registrationserver.logdef import logcfg
from registrationserver.logger import logger  # type: ignore
from registrationserver.registrar import Registrar
from registrationserver.shutdown import system_shutdown

logger.debug("%s -> %s", __package__, __file__)

MATCHID = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")
RESERVE_KEYWORD = "reserve"
FREE_KEYWORD = "free"

# =======================
# Initialization of the actor system,
# can be changed to a distributed system here.
# =======================
config["APP_TYPE"] = AppType.RS
system = ActorSystem(
    systemBase=actor_config["systemBase"],
    capabilities=actor_config["capabilities"],
    logDefs=logcfg,
)
registrar_actor = system.createActor(Registrar, globalName="registrar")
system.tell(
    registrar_actor,
    SetupMsg("registrar", "actor_system", AppType.RS),
)
logger.debug("Actor system started.")


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
        """Allows to shutdown the REST API.
        This function is not really needed
        moreover werkzeug.server.shutdown is deprecated."""

        def shutdown_server():
            func = request.environ.get("werkzeug.server.shutdown")
            if func is None:
                raise RuntimeError("Not running with the Werkzeug Server")
            func()

        shutdown_server()
        return "Server shutting down..."

    @staticmethod
    @api.route("/list", methods=["GET"])
    @api.route("/list/", methods=["GET"])
    def get_list():
        """Path for getting the list of active devices"""
        return Response(
            response=json.dumps(get_device_statuses(registrar_actor)),
            status=200,
            mimetype="application/json",
        )

    @staticmethod
    @api.route("/list/<device_id>", methods=["GET"])
    @api.route("/list/<device_id>/", methods=["GET"])
    def get_device(device_id):
        """Path for getting information for a single active device"""
        if not MATCHID.fullmatch(device_id):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        answer[device_id] = get_device_status(registrar_actor, device_id)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/list/<device_id>/{RESERVE_KEYWORD}", methods=["GET"])
    def reserve_device(device_id):
        """Path for reserving a single active device"""
        # Collect information about who sent the request.
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
        if not isinstance(reserve_return, ReservationStatusMsg):
            logger.critical("Critical error in device actor. Stop and shutdown system.")
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status), device_id: {}}
            system_shutdown()
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        logger.debug("returned with %s", reserve_return)
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
    @api.route(f"/list/<device_id>/{FREE_KEYWORD}", methods=["GET"])
    def free_device(device_id):
        """Path for freeing a single active device"""
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
            if not isinstance(free_return, ReservationStatusMsg):
                logger.critical(
                    "Critical error in device actor. Stop and shutdown system."
                )
                status = Status.CRITICAL
                system_shutdown()
            else:
                logger.debug("returned with %s", free_return)
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
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, GetLocalPortsMsg, 10)
        if not isinstance(reply, ReturnLocalPortsMsg):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status)}
            system_shutdown()
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply.ports

    @staticmethod
    @api.route("/ports/<port>/loop", methods=["GET"])
    def getloopport(port):
        """Loops Local Ports, Used for Testing"""
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, AddPortToLoopMsg(port), 10)
        if not isinstance(reply, ReturnLoopPortsMsg):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status)}
            system_shutdown()
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply.ports

    @staticmethod
    @api.route("/ports/<port>/stop", methods=["GET"])
    def getstopport(port):
        """Loops Local Ports, Used for Testing"""
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, RemovePortFromLoopMsg(port), 10)
        if not isinstance(reply, ReturnLoopPortsMsg):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status)}
            system_shutdown()
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply.ports

    @staticmethod
    @api.route("/ports/list-usb", methods=["GET"])
    def getusbports():
        """Loops Local Ports, Used for Testing"""
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, GetUsbPortsMsg(), 10)
        if not isinstance(reply, ReturnUsbPortsMsg):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status)}
            system_shutdown()
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply.ports

    @staticmethod
    @api.route("/ports/list-native", methods=["GET"])
    def getnativeports():
        """Loops Local Ports, Used for Testing"""
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(cluster_actor, GetNativePortsMsg(), 10)
        if not isinstance(reply, ReturnNativePortsMsg):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            status = Status.CRITICAL
            answer = {"Error code": status.value, "Error": str(status)}
            system_shutdown()
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply.ports

    @staticmethod
    @api.route("/status", methods=["GET"])
    def getstatus():
        """Ask actor system to output actor status to debug log"""
        cluster_actor = get_actor(registrar_actor, "cluster")
        reply = ActorSystem().ask(
            actorAddr=cluster_actor, msg=Thespian_StatusReq(), timeout=10
        )
        if reply is None:
            logger.critical("Emergency shutdown. Timeout in ask.")
            system_shutdown()

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
