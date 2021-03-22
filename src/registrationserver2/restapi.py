"""
Created on 02.10.2020

@author: rfoerster
"""

import os
import socket
import sys
import traceback

from flask import Flask, Response, json, request
from thespian.actors import Actor  # type: ignore

import registrationserver2
from registrationserver2 import (FOLDER_AVAILABLE, FOLDER_HISTORY,
                                 FREE_KEYWORD, PATH_AVAILABLE, PATH_HISTORY,
                                 RESERVE_KEYWORD, theLogger)
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from registrationserver2.modules.rfc2217.rfc2217_actor import Rfc2217Actor

theLogger.info("%s -> %s", __package__, __file__)


class RestApi(Actor):
    """
    Rest API
    delivers lists and info for devices
    relays reservation / free requests towards the Instrument Server 2
    for the devices.
    Information is taken from the device info folder defined
    in both config.py (settings) and __init__.py (defaults).

    .. uml:: uml-restapi.puml
    """

    api = Flask(__name__)

    class Dummy:
        """Dummy Output which just ignored messages"""

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
                theLogger.debug(file)
                if os.path.isfile(file):
                    theLogger.debug(file)
                    answer[dir_entry] = {
                        "Identification": json.load(open(file)).get(
                            "Identification", None
                        )
                    }
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
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
        if not registrationserver2.matchid.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        try:
            if os.path.isfile(f"{FOLDER_AVAILABLE}{os.path.sep}{did}"):
                answer[did] = {
                    "Identification": json.load(
                        open(f"{FOLDER_AVAILABLE}{os.path.sep}{did}")
                    ).get("Identification", None)
                }
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
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
                if os.path.isfile(f"{FOLDER_HISTORY}{os.path.sep}{dir_entry}"):
                    answer[dir_entry] = {
                        "Identification": json.load(
                            open(f"{FOLDER_HISTORY}{os.path.sep}{dir_entry}")
                        ).get("Identification", None)
                    }
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
        return Response(
            response=json.dumps(answer), status=200, mimetype="application/json"
        )

    @staticmethod
    @api.route(f"/{PATH_HISTORY}/<did>", methods=["GET"])
    @api.route(f"/{PATH_HISTORY}/<did>/", methods=["GET"])
    def get_device_old(did):
        """Path for getting information about a single
        previously or currently detected device"""
        if not registrationserver2.matchid.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        answer = {}
        try:
            if os.path.isfile(f"{FOLDER_HISTORY}{os.path.sep}{did}"):
                answer[did] = {
                    "Identification": json.load(
                        open(f"{FOLDER_HISTORY}{os.path.sep}{did}")
                    ).get("Identification", None)
                }
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
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
        attribute_who = request.args.get("who").strip('"')
        app = attribute_who.split(" - ")[0]
        user = attribute_who.split(" - ")[1]
        try:
            request_host = socket.gethostbyaddr(request.environ["REMOTE_ADDR"])[0]
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
        else:
            request_host = request.environ["REMOTE_ADDR"]
        theLogger.info("%s: %s --> %s", did, attribute_who, request_host)
        if not registrationserver2.matchid.fullmatch(did):
            return json.dumps({"Error": "Wronly formated ID"})
        # SEND_RESERVE message to device actor
        if "_rfc2217" in did:
            device_actor = registrationserver2.actor_system.createActor(
                Rfc2217Actor, globalName=did
            )
        elif "mqtt" in did:
            device_actor = registrationserver2.actor_system.createActor(
                MqttActor, globalName=did
            )
        else:
            theLogger.error("Requested service not supported by actor system.")
            answer = {"Error code": "11", "Error": "Device not found", did: {}}
            return Response(
                response=json.dumps(answer), status=200, mimetype="application/json"
            )
        reserve_return = registrationserver2.actor_system.ask(
            device_actor,
            {"CMD": "SEND_RESERVE", "HOST": request_host, "USER": user, "APP": app},
        )
        theLogger.info(reserve_return)

        answer = {}
        reservation = {
            "Active": True,
            "Host": request_host,
            "App": app,
            "User": user,
            "Timestamp": "2020-10-09T08:22:43Z",
            "IP": "123.123.123.123",
            "Port": 2345,
        }

        try:
            if os.path.isfile(f"{FOLDER_HISTORY}{os.path.sep}{did}"):
                answer[did] = {
                    "Identification": json.load(
                        open(f"{FOLDER_HISTORY}{os.path.sep}{did}")
                    ).get("Identification", None)
                }
        except Exception as error:  # pylint: disable=broad-except
            theLogger.error(
                "! %s\t%s\t%s\t%s",
                type(error),
                error,
                vars(error) if isinstance(error, dict) else "-",
                traceback.format_exc(),
            )
        answer[did]["Reservation"] = reservation
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
        return json.dumps(f"{did}")

    def run(self, host=None, port=None, debug=None, load_dotenv=True):
        """Start the API"""
        theLogger.info("Starting API at %s:%d", host, port)
        std = sys.stdout
        sys.stdout = RestApi.Dummy
        self.api.run(host=host, port=port, debug=debug, load_dotenv=load_dotenv)
        sys.stdout = std
