""" Simple dataclass to store properties of a serial device

Created
    2021-06-09

Author
    Riccardo Foerster <rfoerster@sarad.de>

"""
from dataclasses import dataclass


@dataclass
class USBSerial:
    """Simple dataclass to store properties of a serial device"""

    deviceid: str
    path: str

    def __hash__(self):
        return hash(self.deviceid)

    def __eq__(self, other):
        if isinstance(other, USBSerial):
            return self.deviceid == other.deviceid

        if isinstance(other, str):
            return other == self.deviceid

        return False

    def __str__(self):
        return f"{self.__class__.__name__}({self.deviceid})"
