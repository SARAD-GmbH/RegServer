"""Little helper functions that can be used in other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import fnmatch
import os

from thespian.actors import Actor, ActorSystem  # type: ignore

from registrationserver.actor_messages import (GetActorDictMsg,
                                               GetDeviceStatusMsg,
                                               UpdateActorDictMsg,
                                               UpdateDeviceStatusMsg)
from registrationserver.logger import logger
from registrationserver.shutdown import system_shutdown


def short_id(global_name: str) -> str:
    """Get the short_id of a connected instrument from its global_name.
    The short_id is a hash created from instrument family, type and serial number.
    The global_name consists of short_id, protocol type and service type
    devided by dots.

    Args:
        global_name (str): long id of the instrument that is used
        as globalName of device actor

    Returns:
        str: the short id, that is the first element of the global_name
    """
    return global_name.split(".")[0]


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


def get_device_actor(device_id: str):
    """Find the actor address of a device actor with a given device_id.

    Args:
        device_id: The device id identifies the device actor

    Returns:
        Actor address of the device actor
    """
    registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
    with ActorSystem().private() as db_sys:
        result = db_sys.ask(registrar_actor, GetActorDictMsg(), 10)
        if not isinstance(result, UpdateActorDictMsg):
            logger.critical(
                "Emergency shutdown. Ask to Registrar took more than 10 sec."
            )
            system_shutdown()
            return None
        actor_dict = result.actor_dict
    try:
        return actor_dict[device_id]["address"]
    except KeyError:
        logger.warning("%s not in %s", device_id, actor_dict)
        return None


def get_device_status(device_id: str) -> dict:
    """Read the device status from the device actor.

    Args:
        device_id: The device id is used as well as file name as
                   as global name for the device actor

    Returns:
        A dictionary containing additional information
        for the *Identification* of the instrument and it's *Reservation* state

    """
    device_actor = get_device_actor(device_id)
    if device_actor is None:
        return {}
    with ActorSystem().private() as device_sys:
        result = device_sys.ask(device_actor, GetDeviceStatusMsg(), 10)
        if not isinstance(result, UpdateDeviceStatusMsg):
            logger.critical(
                "Emergency shutdown. Ask to device_actor took more than 10 sec."
            )
            system_shutdown()
            return {}
    return result.device_status


def get_device_statuses():
    """Return a list of all device ids together with the device status"""
    registrar_actor = ActorSystem().createActor(Actor, globalName="registrar")
    with ActorSystem().private() as db_sys:
        result = db_sys.ask(registrar_actor, GetActorDictMsg(), 10)
        if not isinstance(result, UpdateActorDictMsg):
            logger.critical(
                "Emergency shutdown. Ask to Registrar took more than 10 sec."
            )
            system_shutdown()
            return None
        actor_dict = result.actor_dict
    device_actor_dict = {
        id: dict["address"]
        for id, dict in actor_dict.items()
        if dict["is_device_actor"]
    }
    device_statuses = {}
    for _id, device_actor in device_actor_dict.items():
        reply = ActorSystem().ask(device_actor, GetDeviceStatusMsg())
        device_statuses[reply.device_id] = reply.device_status
    return device_statuses
