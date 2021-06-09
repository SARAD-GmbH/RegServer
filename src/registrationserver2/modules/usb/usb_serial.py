"""
Created on 09.06.2021

@author: rfoerster
"""
from dataclasses import dataclass


@dataclass
class USBSerial:
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
