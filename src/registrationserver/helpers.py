"""Little helper functions that can be used in other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import fnmatch
import os

from thespian.actors import Actor, ActorSystem

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
    device_db_actor = ActorSystem().createActor(Actor, globalName="device_db")
    try:
        with ActorSystem().private() as db_sys:
            device_db = db_sys.ask(device_db_actor, {"CMD": "READ"}, 10)["RESULT"]
    except KeyError:
        logger.critical(
            "Emergency shutdown. Cannot get appropriate response from DeviceDb actor."
        )
        system_shutdown()
    try:
        return device_db[device_id]
    except KeyError:
        logger.warning("%s not in %s", device_id, device_db)
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
        result = device_sys.ask(device_actor, {"CMD": "READ"}, 10)["RESULT"]
        if result is None:
            logger.critical(
                "Emergency shutdown. Ask to device_actor took more than 10 sec."
            )
            system_shutdown()
            return {}
    return result
