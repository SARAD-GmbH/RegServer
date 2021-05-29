"""REST API -- the interface to the SARAD app

Created
    2020-10-02

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml:: uml-restapi.puml

"""

import os
import re
import socket
import sys

from flask import Flask, Response, json, request
from thespian.actors import Actor, ActorSystem, PoisonMessage  # type: ignore

from registrationserver2 import (FOLDER_AVAILABLE, FOLDER_HISTORY,
                                 FREE_KEYWORD, PATH_AVAILABLE, PATH_HISTORY,
                                 RESERVE_KEYWORD, logger)
from registrationserver2.modules.messages import RETURN_MESSAGES

logger.info("%s -> %s", __package__, __file__)

MATCHID = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")


def get_state_from_file(device_id: str, cmd_key: str, hist: bool = False) -> dict:
    """Read the device state from the device file.

    Args:
        device_id: The device id is used as well as file name as
                   as global name for the device actor
        cmd_key: Keyword to denote the state section in the JSON file
                 (either "Reservation" or "Free")
        hist: Indicates whether the information shall be taken from
              FOLDER_HISTORY (True) or from FOLDER_AVAILABLE (False)

    Returns:
        A dictionary containing additional information
        for the *Identification* of the instrument and it's *Reservation* state

    """
    assert cmd_key in ("Reservation", "Free")
    if hist:
        filename = f"{FOLDER_HISTORY}{os.path.sep}{device_id}"
    else:
        filename = f"{FOLDER_AVAILABLE}{os.path.sep}{device_id}"
    try:
        if os.path.isfile(filename):
            answer = {
                "Identification": json.load(open(filename)).get("Identification", None),
            }
            reservation = json.load(open(filename)).get(cmd_key, None)
            if reservation is not None:
                answer["Reservation"] = reservation
            return answer
    except Exception:  # pylint: disable=broad-except
        logger.exception("Fatal error")
        return {}
    return {}


class RestApi:
    """REST API
    delivers lists and info for devices
    relays reservation and free requests to the device actors.
    Information is taken from the device file folder defined
    in both config.py (settings) and __init__.py (defaults).
    """

    api = Flask(__name__)

    class Dummy:
        """Dummy output which just ignored messages"""

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
    @api.route(f"/{PATH_AVAILABLE}", methods=["GET"])
    @api.route(f"/{PATH_AVAILABLE}/", methods=["GET"])
    def get_list():
        """Path for getting the list of active devices"""
        answer = {}
        try:
            for did in os.listdir(FOLDER_AVAILABLE):
                answer[did] = get_state_from_file(did, "Reservation")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route("/list/<did>", methods=["GET"])
    @api.route("/list/<did>/", methods=["GET"])
    @api.route(f"/{PATH_AVAILABLE}/<did>", methods=["GET"])
    @api.route(f"/{PATH_AVAILABLE}/<did>/", methods=["GET"])
    def get_device(did):
        """Path for getting information for a single active device"""
        if not MATCHID.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        answer[did] = get_state_from_file(did, "Reservation")
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/{PATH_HISTORY}", methods=["GET"])
    @api.route(f"/{PATH_HISTORY}/", methods=["GET"])
    def get_history():
        """Path for getting the list of all time detected devices"""
        answer = {}
        try:
            for did in os.listdir(f"{FOLDER_HISTORY}"):
                answer[did] = get_state_from_file(did, "Reservation", hist=True)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/{PATH_HISTORY}/<did>", methods=["GET"])
    @api.route(f"/{PATH_HISTORY}/<did>/", methods=["GET"])
    def get_device_old(did):
        """Path for getting information about a single
        previously or currently detected device"""
        if not MATCHID.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        answer[did] = get_state_from_file(did, "Reservation", hist=True)
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/list/<did>/{RESERVE_KEYWORD}", methods=["GET"])
    @api.route(
        f"/{PATH_AVAILABLE}/<did>/{RESERVE_KEYWORD}",
        methods=["GET"],
    )
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
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
            request_host = request.environ["REMOTE_ADDR"]
        logger.info("%s: %s --> %s", did, attribute_who, request_host)
        if not MATCHID.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        if not "_rfc2217" in did and not "mqtt" in did:
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
        reserve_return = ActorSystem().ask(device_actor, msg, 1)
        if reserve_return is None or isinstance(reserve_return, PoisonMessage):
            answer = {"Error code": 11, "Error": "Device not found", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        logger.debug("returned with %s", reserve_return)
        return_error = reserve_return["ERROR_CODE"]
        if return_error == RETURN_MESSAGES["OK"]["ERROR_CODE"]:
            answer = {"Error code": return_error, "Error": "OK"}
            answer[did] = get_state_from_file(did, "Reservation")
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )

    @staticmethod
    @api.route(f"/list/<did>/{FREE_KEYWORD}", methods=["GET"])
    @api.route(
        f"/{PATH_AVAILABLE}/<did>/{FREE_KEYWORD}",
        methods=["GET"],
    )
    def free_device(did):
        """Path for freeing a single active device"""
        device_actor = ActorSystem().createActor(Actor, globalName=did)
        logger.debug("Ask device actor to FREE...")
        free_return = ActorSystem().ask(device_actor, {"CMD": "FREE"}, 1)
        if free_return is None or isinstance(free_return, PoisonMessage):
            answer = {"Error code": 11, "Error": "Device not found", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        logger.debug("returned with %s", free_return)
        return_error = free_return["ERROR_CODE"]
        if return_error == RETURN_MESSAGES["OK"]["ERROR_CODE"]:
            answer = {}
            answer[did] = get_state_from_file(did, "Free")
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        if return_error is RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"]:
            answer = {
                "Error code": return_error,
                "Error": "Already reserved by other party",
            }
            answer[did] = get_state_from_file(did, "Free")
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        if return_error is RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]:
            answer = {"Error code": return_error, "Error": "No reservation found"}
            answer[did] = get_state_from_file(did, "Free")
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        answer = {"Error code": 99, "Error": "Unexpected error", did: {}}
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    def run(self, host=None, port=None, debug=None, load_dotenv=True):
        """Start the API"""
        logger.info("Starting API at %s:%d", host, port)
        std = sys.stdout
        sys.stdout = RestApi.Dummy
        self.api.run(host=host, port=port, debug=debug, load_dotenv=load_dotenv)
        sys.stdout = std
