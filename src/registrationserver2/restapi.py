"""REST API -- the interface to the SARAD app

Created
    2020-10-02

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml:: uml-restapi.puml

Todo:
    * _free: Freigabe fehlgeschlagen -- Aready reserved by other party
    * _free: Freigabe fehlgeschlagen -- No reservation found
"""

import os
import re
import socket
import sys

from flask import Flask, Response, json, request
from thespian.actors import Actor, ActorSystem  # type: ignore

from registrationserver2 import (FOLDER_AVAILABLE, FOLDER_HISTORY,
                                 FREE_KEYWORD, PATH_AVAILABLE, PATH_HISTORY,
                                 RESERVE_KEYWORD, logger)
from registrationserver2.modules.messages import RETURN_MESSAGES

logger.info("%s -> %s", __package__, __file__)

MATCHID = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")


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
    @api.route("/list", methods=["GET"])
    @api.route("/list/", methods=["GET"])
    @api.route(f"/{PATH_AVAILABLE}", methods=["GET"])
    @api.route(f"/{PATH_AVAILABLE}/", methods=["GET"])
    def get_list():
        """Path for getting the list of active devices"""
        answer = {}
        try:
            for dir_entry in os.listdir(FOLDER_AVAILABLE):
                file = fr"{FOLDER_AVAILABLE}{os.path.sep}{dir_entry}"
                if os.path.isfile(file):
                    answer[dir_entry] = {
                        "Identification": json.load(open(file)).get(
                            "Identification", None
                        )
                    }
                    reservation = json.load(open(file)).get("Reservation", None)
                    if reservation is not None:
                        answer[dir_entry]["Reservation"] = reservation
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
        try:
            filename = f"{FOLDER_AVAILABLE}{os.path.sep}{did}"
            if os.path.isfile(filename):
                answer[did] = {
                    "Identification": json.load(open(filename)).get(
                        "Identification", None
                    )
                }
                reservation = json.load(open(filename)).get("Reservation", None)
                if reservation is not None:
                    answer[did]["Reservation"] = reservation
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
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
            for dir_entry in os.listdir(f"{FOLDER_HISTORY}"):
                file = fr"{FOLDER_HISTORY}{os.path.sep}{dir_entry}"
                if os.path.isfile(file):
                    answer[dir_entry] = {
                        "Identification": json.load(open(file)).get(
                            "Identification", None
                        )
                    }
                    reservation = json.load(open(file)).get("Reservation", None)
                    if reservation is not None:
                        answer[dir_entry]["Reservation"] = reservation
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
        try:
            filename = f"{FOLDER_AVAILABLE}{os.path.sep}{did}"
            if os.path.isfile(filename):
                answer[did] = {
                    "Identification": json.load(open(filename)).get(
                        "Identification", None
                    )
                }
                reservation = json.load(open(filename)).get("Reservation", None)
                if reservation is not None:
                    answer[did]["Reservation"] = reservation
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
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
            request_host = socket.gethostbyaddr(request.environ["REMOTE_ADDR"])[0]
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
        else:
            request_host = request.environ["REMOTE_ADDR"]
        logger.info("%s: %s --> %s", did, attribute_who, request_host)
        if not MATCHID.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        # send RESERVE message to device actor
        if ("_rfc2217" in did) or ("mqtt" in did):
            device_actor = ActorSystem().createActor(Actor, globalName=did)
        else:
            logger.error("Requested service not supported by actor system.")
            answer = {"Error code": "11", "Error": "Device not found", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        msg = {
            "CMD": "RESERVE",
            "PAR": {"HOST": request_host, "USER": user, "APP": app},
        }
        logger.debug("Ask device actor %s", msg)
        reserve_return = ActorSystem().ask(device_actor, msg)
        logger.debug("returned with %s", reserve_return)
        answer = {}
        try:
            if os.path.isfile(f"{FOLDER_HISTORY}{os.path.sep}{did}"):
                answer[did] = {
                    "Identification": json.load(
                        open(f"{FOLDER_HISTORY}{os.path.sep}{did}")
                    ).get("Identification", None),
                    "Reservation": json.load(
                        open(f"{FOLDER_HISTORY}{os.path.sep}{did}")
                    ).get("Reservation", None),
                }
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
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
        free_return = ActorSystem().ask(device_actor, {"CMD": "FREE"})
        logger.info("returned with %s", free_return)
        if free_return is RETURN_MESSAGES["OK"] or RETURN_MESSAGES["OK_SKIPPED"]:
            answer = {}
            if os.path.isfile(f"{FOLDER_HISTORY}{os.path.sep}{did}"):
                answer[did] = {
                    "Identification": json.load(
                        open(f"{FOLDER_HISTORY}{os.path.sep}{did}")
                    ).get("Identification", None),
                    "Reservation": json.load(
                        open(f"{FOLDER_HISTORY}{os.path.sep}{did}")
                    ).get("Free", None),
                }
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        answer = {"Error code": 11, "Error": "Device not found", did: {}}
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
