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
from thespian.actors import Actor, ActorSystem, PoisonMessage
from thespian.system.messages.status import Thespian_StatusReq, formatStatus

from registrationserver.config import mqtt_config
from registrationserver.logger import logger  # type: ignore
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.shutdown import system_shutdown

logger.debug("%s -> %s", __package__, __file__)

MATCHID = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")
RESERVE_KEYWORD = "reserve"
FREE_KEYWORD = "free"


def get_device_status(device_id: str) -> dict:
    """Read the device status from the device actor.

    Args:
        device_id: The device id is used as well as file name as
                   as global name for the device actor

    Returns:
        A dictionary containing additional information
        for the *Identification* of the instrument and it's *Reservation* state

    """
    device_db_actor = ActorSystem().createActor(Actor, globalName="device_db")
    try:
        with ActorSystem().private() as db_sys:
            device_db = db_sys.ask(device_db_actor, {"CMD": "READ"})["RESULT"]
    except KeyError:
        logger.critical("Cannot get appropriate response from DeviceDb actor")
        raise
    try:
        device_actor = device_db[device_id]
    except KeyError:
        logger.warning("%s not in %s", device_id, device_db)
        return {}
    with ActorSystem().private() as device_sys:
        result = device_sys.ask(device_actor, {"CMD": "READ"})["RESULT"]
    return result


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
        answer = {}
        device_db_actor = ActorSystem().createActor(Actor, globalName="device_db")
        try:
            device_db = ActorSystem().ask(device_db_actor, {"CMD": "READ"})["RESULT"]
        except KeyError:
            logger.critical("Cannot get appropriate response from DeviceDb actor")
            raise
        for device_id in device_db:
            answer[device_id] = get_device_status(device_id)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list/<did>", methods=["GET"])
    @api.route("/list/<did>/", methods=["GET"])
    def get_device(did):
        """Path for getting information for a single active device"""
        if not MATCHID.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        answer[did] = get_device_status(did)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/list/<did>/{RESERVE_KEYWORD}", methods=["GET"])
    def reserve_device(did):
        """Path for reserving a single active device"""
        # Collect information about who sent the request.
        try:
            attribute_who = request.args.get("who").strip('"')
            app = attribute_who.split(" - ")[0]
            user = attribute_who.split(" - ")[1]
        except (IndexError, AttributeError):
            logger.error("Reserve request without proper who attribute.")
            answer = {
                "Error code": "13",
                "Error": "No or incomplete attributes.",
                did: {},
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
            "Request reservation of %s for %s@%s", did, attribute_who, request_host
        )
        if not MATCHID.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        device_state = get_device_status(did)
        if (
            not "_rfc2217" in did and not "mqtt" in did and not "local" in did
        ) or device_state == {}:
            logger.error("Requested service not supported by actor system.")
            answer = {"Error code": "11", "Error": "Device not found", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        # send RESERVE message to device actor
        device_actor = ActorSystem().createActor(Actor, globalName=did)
        msg = {
            "CMD": "RESERVE",
            "PAR": {"HOST": request_host, "USER": user, "APP": app},
        }
        logger.debug("Ask device actor %s", msg)
        with ActorSystem().private() as reserve_sys:
            reserve_return = reserve_sys.ask(device_actor, msg)
        if isinstance(reserve_return, PoisonMessage):
            logger.critical("Critical error in device actor. Stop and shutdown system.")
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        logger.debug("returned with %s", reserve_return)
        return_error = reserve_return["ERROR_CODE"]
        if return_error in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            answer = {"Error code": return_error, "Error": "OK"}
            answer[did] = get_device_status(did)
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        if return_error is RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"]:
            answer = {
                "Error code": return_error,
                "Error": "Already reserved by other party",
            }
            answer[did] = get_device_status(did)
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        answer = {"Error code": 99, "Error": "Unexpected error", did: {}}
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/list/<did>/{FREE_KEYWORD}", methods=["GET"])
    def free_device(did):
        """Path for freeing a single active device"""
        device_state = get_device_status(did)
        if device_state == {}:
            answer = {"Error code": 11, "Error": "Device not found", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        if device_state.get("Reservation", None) is None:
            answer = {
                "Error code": 10,
                "Error": "No reservation found",
                did: device_state,
            }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        if device_state["Reservation"].get("Active") is False:
            answer = {
                "Error code": 10,
                "Error": "No reservation found",
                did: device_state,
            }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )

        device_actor = ActorSystem().createActor(Actor, globalName=did)
        logger.debug("Ask device actor to FREE...")
        free_return = ActorSystem().ask(device_actor, {"CMD": "FREE"})
        if isinstance(free_return, PoisonMessage):
            logger.critical("Critical error in device actor. Stop and shutdown system.")
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        logger.debug("returned with %s", free_return)
        return_error = free_return["ERROR_CODE"]
        if return_error == RETURN_MESSAGES["OK"]["ERROR_CODE"]:
            answer = {"Error code": 0, "Error": "OK", did: {}}
            answer[did] = get_device_status(did)
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        if return_error is RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"]:
            answer = {
                "Error code": return_error,
                "Error": "Already reserved by other party",
            }
            answer[did] = get_device_status(did)
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        answer = {"Error code": 99, "Error": "Unexpected error", did: {}}
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/ports", methods=["GET"])
    @api.route("/ports/", methods=["GET"])
    def getlocalports():
        """Lists Local Ports, Used for Testing atm"""
        cluster = ActorSystem().createActor(Actor, globalName="cluster")
        reply = ActorSystem().ask(cluster, {"CMD": "LIST-PORTS"})
        if isinstance(reply, PoisonMessage):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error"}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply

    @staticmethod
    @api.route("/ports/<port>/loop", methods=["GET"])
    def getloopport(port):
        """Loops Local Ports, Used for Testing"""
        cluster = ActorSystem().createActor(Actor, globalName="cluster")
        reply = ActorSystem().ask(cluster, {"CMD": "LOOP", "PAR": {"PORT": port}})
        if isinstance(reply, PoisonMessage):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error"}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply

    @staticmethod
    @api.route("/ports/<port>/stop", methods=["GET"])
    def getstopport(port):
        """Loops Local Ports, Used for Testing"""
        cluster = ActorSystem().createActor(Actor, globalName="cluster")
        reply = ActorSystem().ask(
            cluster, {"CMD": "LOOP-REMOVE", "PAR": {"PORT": port}}
        )
        if isinstance(reply, PoisonMessage):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error"}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply

    @staticmethod
    @api.route("/ports/list-usb", methods=["GET"])
    def getusbports():
        """Loops Local Ports, Used for Testing"""
        cluster = ActorSystem().createActor(Actor, globalName="cluster")
        reply = ActorSystem().ask(cluster, {"CMD": "LIST-USB"})
        if isinstance(reply, PoisonMessage):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error"}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply

    @staticmethod
    @api.route("/ports/list-native", methods=["GET"])
    def getnativeports():
        """Loops Local Ports, Used for Testing"""
        cluster = ActorSystem().createActor(Actor, globalName="cluster")
        reply = ActorSystem().ask(cluster, {"CMD": "LIST-NATIVE"})
        if isinstance(reply, PoisonMessage):
            logger.critical(
                "Critical error in cluster actor. Stop and shutdown system."
            )
            system_shutdown()
            answer = {"Error code": 99, "Error": "Unexpected error"}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        return reply

    @staticmethod
    @api.route("/status", methods=["GET"])
    def getstatus():
        """Ask actor system to output actor status to debug log"""
        cluster = ActorSystem().createActor(Actor, globalName="cluster")
        reply = ActorSystem().ask(
            actorAddr=cluster,
            msg=Thespian_StatusReq(),
        )

        class Temp:
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
