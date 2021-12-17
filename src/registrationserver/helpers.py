"""Little helper functions that can be used in other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import fnmatch
import os


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
    for root, dirs, files in os.walk(path):
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
