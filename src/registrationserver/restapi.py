"""REST API -- the interface to the SARAD app

:Created:
    2020-10-02

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-restapi.puml

"""

import re
import sys
import time
from datetime import timedelta

from flask import Flask, Response, json, request
from thespian.actors import (Actor, ActorSystem,  # type: ignore
                             Thespian_ActorStatus)
from thespian.system.messages.status import (  # type: ignore
    Thespian_StatusReq, formatStatus)
from waitress import serve

from registrationserver.actor_messages import (AddPortToLoopMsg, FreeDeviceMsg,
                                               GetLocalPortsMsg,
                                               GetNativePortsMsg,
                                               GetUsbPortsMsg,
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
                                        transport_technology)
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
        logger.debug("Shutdown by user intervention")
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
        with ActorSystem().private() as scan_sys:
            reply = scan_sys.ask(
                cluster_actor, RescanMsg(), timeout=timedelta(seconds=60)
            )
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
            request_host = attribute_who.split(" - ")[2]
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
            transport_technology(device_id) not in ["local", "is1", "mdns", "mqtt"]
        ) or (device_state == {}):
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
                device_actor,
                ReserveDeviceMsg(request_host, user, app),
                timeout=timedelta(seconds=10),
            )
        if reserve_return is None:
            status = Status.NOT_FOUND
        else:
            reply_is_corrupted = check_msg(reserve_return, ReservationStatusMsg)
            if reply_is_corrupted:
                return reply_is_corrupted
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
            answer = {"Error code": status.value, "Error": str(status), device_id: {}}
            logger.critical("%s -> emergency shutdown", answer)
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
        else:
            device_actor = get_actor(registrar_actor, device_id)
            logger.debug("Ask device actor to FREE...")
            with ActorSystem().private() as free_dev:
                free_return = free_dev.ask(
                    device_actor, FreeDeviceMsg(), timeout=timedelta(seconds=10)
                )
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
        with ActorSystem().private() as get_local_ports:
            reply = get_local_ports.ask(
                cluster_actor, GetLocalPortsMsg(), timeout=timedelta(seconds=10)
            )
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
        with ActorSystem().private() as get_loop_port:
            reply = get_loop_port.ask(
                cluster_actor, AddPortToLoopMsg(port), timeout=timedelta(seconds=10)
            )
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
        with ActorSystem().private() as get_stop_port:
            reply = get_stop_port.ask(
                cluster_actor,
                RemovePortFromLoopMsg(port),
                timeout=timedelta(seconds=10),
            )
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
        with ActorSystem().private() as get_usb_ports:
            reply = get_usb_ports.ask(
                cluster_actor, GetUsbPortsMsg(), timeout=timedelta(seconds=10)
            )
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
        with ActorSystem().private() as get_native_ports:
            reply = get_native_ports.ask(
                cluster_actor, GetNativePortsMsg(), timeout=timedelta(seconds=10)
            )
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
        with ActorSystem().private() as get_status:
            reply = get_status.ask(
                actorAddr=actor_address,
                msg=Thespian_StatusReq(),
                timeout=timedelta(seconds=10),
            )
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

    def run(self, host=None, port=None, debug=None, load_dotenv=True):
        """Start the API"""
        success = False
        retry_interval = mqtt_config.get("RETRY_INTERVAL", 60)
        while not success:
            try:
                logger.info("Starting API at %s:%d", host, port)
                std = sys.stdout
                sys.stdout = RestApi.Dummy
                # self.api.run(host=host, port=port, debug=debug, load_dotenv=load_dotenv)
                serve(self.api, listen=f"*:{port}")
                sys.stdout = std
                success = True
            except OSError as exception:
                logger.critical(exception)
                time.sleep(retry_interval)
