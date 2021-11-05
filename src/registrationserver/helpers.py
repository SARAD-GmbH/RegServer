"""Little helper functions that can be used in other modules

Created
    2021-11-03

Authors
    Michael Strey <strey@sarad.de>
"""
import fnmatch
import os


def short_id(global_name: str) -> str:
    return global_name.split(".")[0]


def find(pattern, path):
    result = []
    for root, dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                result.append(os.path.join(root, name))
    return result
