"""Little helper functions that can be used in other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import fnmatch
import os
from collections.abc import MutableMapping
from contextlib import suppress
from datetime import timedelta
from typing import List

from thespian.actors import (Actor, ActorSystem,  # type: ignore
                             ActorSystemFailure)

from registrationserver.actor_messages import (FreeDeviceMsg, GetActorDictMsg,
                                               GetDeviceStatusesMsg,
                                               GetDeviceStatusMsg,
                                               ReservationStatusMsg,
                                               ReserveDeviceMsg, Status,
                                               UpdateActorDictMsg,
                                               UpdateDeviceStatusesMsg,
                                               UpdateDeviceStatusMsg)
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown


def make_command_msg(cmd_data: List[bytes]) -> bytes:
    """Encode the message to be sent to the SARAD instrument.
    Arguments are the one byte long command
    and the data bytes to be sent."""
    cmd: bytes = cmd_data[0]
    data: bytes = cmd_data[1]
    payload: bytes = cmd + data
    control_byte = len(payload) - 1
    if cmd:  # Control message
        control_byte = control_byte | 0x80  # set Bit 7
    neg_control_byte = control_byte ^ 0xFF
    checksum = 0
    for byte in payload:
        checksum = checksum + byte
    checksum_bytes = (checksum).to_bytes(2, byteorder="little")
    output = (
        b"B"
        + bytes([control_byte])
        + bytes([neg_control_byte])
        + payload
        + checksum_bytes
        + b"E"
    )
    return output


def check_message(answer: bytes, multiframe: bool):
    """Returns a dictionary of:
    is_valid: True if answer is valid, False otherwise
    is_control_message: True if control message
    payload: Payload of answer
    number_of_bytes_in_payload
    raw"""
    logger.debug("Checking raw answer: %s", answer)
    if answer.startswith(b"B") and answer.endswith(b"E"):
        control_byte = answer[1]
        control_byte_ok = bool((control_byte ^ 0xFF) == answer[2])
        number_of_bytes_in_payload = (control_byte & 0x7F) + 1
        is_control = bool(control_byte & 0x80)
        status_byte = answer[3]
        logger.debug("Status byte: %s", status_byte)
        payload = answer[3 : 3 + number_of_bytes_in_payload]
        calculated_checksum = 0
        for byte in payload:
            calculated_checksum = calculated_checksum + byte
        received_checksum_bytes = answer[
            3 + number_of_bytes_in_payload : 5 + number_of_bytes_in_payload
        ]
        received_checksum = int.from_bytes(
            received_checksum_bytes, byteorder="little", signed=False
        )
        checksum_ok = bool(received_checksum == calculated_checksum)
        is_valid = bool(control_byte_ok and checksum_ok)
    else:
        logger.debug("Invalid B-E frame")
        is_valid = False
    if not is_valid:
        is_control = False
        payload = b""
        number_of_bytes_in_payload = 0
    # is_rend is True if that this is the last frame of a multiframe reply
    # (DOSEman data download)
    is_rend = bool(is_valid and is_control and (payload == b"\x04"))
    return {
        "is_valid": is_valid,
        "is_control": is_control,
        "is_last_frame": (not multiframe) or is_rend,
        "payload": payload,
        "number_of_bytes_in_payload": number_of_bytes_in_payload,
        "raw": answer,
    }


def short_id(device_id: str, check=True):
    """Get the short instr_id of a connected instrument from its device_id.
    The instr_id is a hash created from instrument family, type and serial number.
    The device_id consists of instr_id, protocol type and service type
    devided by dots.

    Args:
        device_id (str): long ID of the instrument that is used
                         as actor_id of device actor
        check (bool): optional argument. If True,
                      check whether device_id is a valid device id with
                      just 3 elements.

    Returns:
        str: the instr_id, that is the first element of the device_id
    """
    splitted = device_id.split(".")
    if check:
        if len(splitted) == 3:
            return splitted[0]
        return None
    return splitted[0]


def sarad_protocol(device_id: str) -> str:
    """Get the second part of the device_id designating the SARAD protocol.

    Args:
        device_id (str): long ID of the instrument that is used
                         as actor_id of device actor

    Returns:
        str: the id of the SARAD protocol
    """
    return device_id.split(".")[1]


def transport_technology(device_id: str) -> str:
    """Get the last part of the device_id designating the transport technology (tt).
    This is in ["local", "is1", "mdns", "mqtt"].

    Args:
        device_id (str): long ID of the instrument that is used
                         as actor_id of device actor

    Returns:
        str: the id of the transport technology
    """
    return device_id.split(".", 2)[-1]


def is_device_actor(actor_id: str) -> bool:
    """Check whether the actor is an device actor.
    Device actor ids are having the structure instr_id.protocoll.tt

    Args:
        actor_id (str): if it is a device actor, this is the device_id

    Returns:
        bool: True if the actor_id has the structure of a device_id
    """
    return bool(len(actor_id.split(".")) == 3)


def find(pattern, path):
    """Find a file matching a given pattern in a given path.

    Args:
        patter (str): file name pattern
        path (str): path that should be walked through to find the file

    Returns:
        List(str): List of full paths of the files found
    """
    result = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                result.append(os.path.join(root, name))
    return result


def get_key(val, my_dict):
    """Function to return key for any value in a dictionary

    Args:
        val: the value
        my_dict: dictionary to scan for val

    Returns:
        key: the first key matching the given value
    """
    for key, value in my_dict.items():
        if val == value:
            return key
    return None


def get_registrar_actor():
    """Function to return the registrar_actor of the Actor system"""
    try:
        return ActorSystem().createActor(Actor, globalName="registrar")
    except (ActorSystemFailure, RuntimeError):
        logger.critical("No response from Actor System. -> Emergency shutdown")
        system_shutdown()
        return None


def get_actor(registrar_actor, actor_id: str):
    """Find the actor address of an actor with a given actor_id.

    Args:
        registrar_actor: The actor address of the Registrar
        actor_id: The actor id identifies the actor

    Returns:
        Actor address
    """
    with ActorSystem().private() as h_get_actor:
        try:
            result = h_get_actor.ask(
                registrar_actor, GetActorDictMsg(), timeout=timedelta(seconds=1)
            )
        except ConnectionResetError as exception:
            logger.debug(exception)
            result = None
        if result is None:
            logger.critical(
                "Emergency shutdown. Ask to Registrar took more than 1 sec."
            )
            system_shutdown()
            return None
        if not isinstance(result, UpdateActorDictMsg):
            logger.critical(
                "UpdateActorDictMsg expected but % received. -> Emergency shutdown.",
                result,
            )
            system_shutdown()
            return None
        actor_dict = result.actor_dict
    try:
        return actor_dict[actor_id]["address"]
    except KeyError:
        logger.debug("%s not in %s", actor_id, actor_dict)
        return None


def get_device_status(registrar_actor, device_id: str) -> dict:
    """Read the device status from the device actor.

    Args:
        device_id: The device id is used as well as file name as
                   as global name for the device actor

    Returns:
        A dictionary containing additional information
        for the *Identification* of the instrument and it's *Reservation* state

    """
    with ActorSystem().private() as h_get_device_status:
        try:
            result = h_get_device_status.ask(
                get_actor(registrar_actor, device_id),
                GetDeviceStatusMsg(),
                timeout=timedelta(seconds=5),
            )
        except (ConnectionResetError, ValueError) as exception:
            logger.debug(exception)
            result = None
    if result is None:
        logger.debug("Timeout at GetDeviceStatusMsg.")
        return {}
    if not isinstance(result, UpdateDeviceStatusMsg):
        logger.critical(
            "Emergency shutdown. Request to %s delivered: %s instead of UpdateDeviceStatusMsg",
            device_id,
            result,
        )
        system_shutdown()
        return {}
    return result.device_status


def get_device_status_from_registrar(registrar_actor, device_id: str) -> dict:
    """Read the device status from the registrar.

    Args:
        device_id: The device id is used as well as file name as
                   as global name for the device actor

    Returns:
        A dictionary containing additional information
        for the *Identification* of the instrument and it's *Reservation* state

    """
    device_statuses = get_device_statuses(registrar_actor)
    if device_statuses is None:
        return {}
    return device_statuses.get(device_id, None)


def get_device_statuses(registrar_actor):
    """Return a list of all device ids together with the device status"""
    with ActorSystem().private() as h_get_device_statuses:
        try:
            result = h_get_device_statuses.ask(
                registrar_actor, GetDeviceStatusesMsg(), timeout=timedelta(seconds=5)
            )
        except ConnectionResetError as exception:
            logger.debug(exception)
            result = None
        if result is None:
            logger.debug("Timeout at GetDeviceStatusMsg.")
            return None
        if not isinstance(result, UpdateDeviceStatusesMsg):
            logger.critical(
                "Emergency shutdown. Registrar replied %s instead of UpdateDeviceStatusesMsg",
                result,
            )
            system_shutdown()
            return None
    # logger.debug("Device statuses: %s", result.device_statuses)
    return result.device_statuses


def get_instr_id_actor_dict(registrar_actor):
    """Return a dictionary of device actor addresses with instr_id as key."""
    with ActorSystem().private() as iid_sys:
        try:
            result = iid_sys.ask(
                registrar_actor, GetActorDictMsg(), timeout=timedelta(seconds=1)
            )
        except ConnectionResetError as exception:
            logger.debug(exception)
            result = None
        if result is None:
            logger.critical(
                "Emergency shutdown. Ask to Registrar took more than 1 sec."
            )
            system_shutdown()
            return {}
        if not isinstance(result, UpdateActorDictMsg):
            logger.critical(
                "Emergency shutdown. Registrar replied %s instead of UpdateActorDictMsg",
                result,
            )
            system_shutdown()
            return {}
    return {
        short_id(id): dict["address"]
        for id, dict in result.actor_dict.items()
        if dict["is_device_actor"]
    }


def diff_of_dicts(dict1, dict2):
    """Get difference of two dictionaries."""
    set1 = set(dict1.keys())
    set2 = set(dict2.keys())
    diff = set1 - set2
    diff_dict = {}
    for key in diff:
        if key in dict1:
            diff_dict[key] = dict1[key]
    return diff_dict


def delete_keys_from_dict(dictionary, keys):
    """Delete the keys present in keys from the nested dictionary."""
    for key in keys:
        with suppress(KeyError):
            del dictionary[key]
    for value in dictionary.values():
        if isinstance(value, MutableMapping):
            delete_keys_from_dict(value, keys)


def sanitize_hn(hostname: str) -> str:
    """Remove domain and switch to lower case."""
    return hostname.split(".")[0].lower()


def check_msg(return_message, message_object_type):
    """Check whether the returned message is of the expected type.

    Args:
        return_message: Actor message object from the last ask.
        message_object_type: The expected object type for this request.

    Returns: Either a response to be published by Flask or False.
    """
    logger.debug("Returned with %s", return_message)
    if not isinstance(return_message, message_object_type):
        logger.critical("Got %s instead of %s", return_message, message_object_type)
        logger.critical("-> Stop and shutdown system")
        status = Status.CRITICAL
        answer = {"Error code": status.value, "Error": str(status)}
        system_shutdown()
        return answer
    return False


def send_reserve_message(device_id, registrar_actor, request_host, user, app) -> Status:
    """Send a reserve message to the Device Actor associated with device_id
    and give back the status.

    Args:
        device_id: device_id of the device that shall be reserved
        registrar_actor: Actor address of the Registrar Actor
        request_host: Requesting hostname
        user: User requesting the reservation
        app: Requesting application

    Returns: Success status
    """
    device_actor = get_actor(registrar_actor, device_id)
    if device_actor is None:
        return Status.NOT_FOUND
    with ActorSystem().private() as reserve_sys:
        try:
            reserve_return = reserve_sys.ask(
                device_actor,
                ReserveDeviceMsg(request_host, user, app),
                timeout=timedelta(seconds=10),
            )
        except ConnectionResetError as exception:
            logger.debug(exception)
            reserve_return = None
    if reserve_return is None:
        logger.error("No response from Device Actor %s", device_id)
        device_actor = get_actor(registrar_actor, device_id)
        if device_actor is None:
            return Status.NOT_FOUND
        return Status.CRITICAL
    reply_is_corrupted = check_msg(reserve_return, ReservationStatusMsg)
    if reply_is_corrupted:
        return reply_is_corrupted
    if reserve_return.status in [
        Status.RESERVE_PENDING,
        Status.FREE_PENDING,
    ]:
        return Status.NOT_FOUND
    return reserve_return.status


def send_free_message(device_id, registrar_actor) -> Status:
    """Send a free message to the Device Actor associated with the device_id
    and give back the status.

    Args:
        device_id: device_id of the device that shall be reserved
        registrar_actor: Actor address of the Registrar Actor

    Returns: Success status
    """
    device_state = get_device_status(registrar_actor, device_id)
    if (device_state == {}) or (
        device_actor := get_actor(registrar_actor, device_id)
    ) is None:
        return Status.NOT_FOUND
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
    if free_return is None:
        device_actor = get_actor(registrar_actor, device_id)
        if device_actor is None:
            return Status.NOT_FOUND
        return Status.CRITICAL
    reply_is_corrupted = check_msg(free_return, ReservationStatusMsg)
    if reply_is_corrupted:
        return reply_is_corrupted
    if free_return.status in [
        Status.RESERVE_PENDING,
        Status.FREE_PENDING,
    ]:
        return Status.NOT_FOUND
    return free_return.status
