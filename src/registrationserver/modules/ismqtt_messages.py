"""Contains functions and classes for converting SARAD Network MQTT messages and topic names

Created:
    2021-06-22

Author:
    Riccardo Förster <riccardo.foerster@sarad.de>
"""
import json
import time
from decimal import Decimal
from enum import Enum, auto
from typing import NamedTuple

from registrationserver.logger import logger


class InstrumentServerMeta(NamedTuple):
    """Data class for storing Instrument Server meta information"""

    state: int
    host: str
    description: str
    place: str
    latitude: Decimal
    longitude: Decimal
    height: Decimal


class InstrumentMeta(NamedTuple):
    """Data class for storing SARAD Instrument meta information"""

    state: int
    host: str
    family: int
    instrumentType: int
    name: str
    serial: int


class Reservation(NamedTuple):
    """Data class for storing instrument reservation information"""

    timestamp: float
    active: bool = False
    app: str = ""
    host: str = ""
    user: str = ""


class ControlType(Enum):
    """Types of control messages"""

    UNKNOWN = 0
    FREE = auto()
    RESERVE = auto()


class Control(NamedTuple):
    """Data class for storing instrument control messages"""

    ctype: ControlType
    data: Reservation


def get_is_meta(data: InstrumentServerMeta) -> str:
    """Converting Instrument Server meta information into MQTT payload"""
    return json.dumps(
        {
            "State": data.state or 0,
            "Host": data.host or "unknown",
            "Description": data.description or "SARAD Instrument Server2 Mqtt",
            "Place": data.place or "No description given",
            "Lat": data.latitude or 0,
            "Lon": data.longitude or 0,
            "Height": data.height or 0,
        }
    )


def get_instr_reservation(data: Reservation) -> str:
    """Converting reservation information into MQTT payload"""
    return json.dumps(
        {
            "Active": data.active,
            "App": data.app,
            "Host": data.host,
            "Timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(data.timestamp)
            ),
            "User": data.user,
        }
    )


def get_instr_control(json_data, old_reservation) -> Control:
    """Converting received MQTT payload into Control object"""
    nodata = Reservation(0, False, "", "", "")
    data = json.loads(json_data.payload)
    logger.debug("Payload: %s", data)
    if not "Req" in data:
        logger.error("No 'Req' in payload.")
        return Control(ctype=ControlType.UNKNOWN, data=nodata)
    # FREE
    if data["Req"] == "free":
        logger.debug("[FREE] request")
        if old_reservation is None:
            logger.debug("[FREE] not reserved, nothing to do")
            return Control(
                ctype=ControlType.FREE,
                data=nodata,
            )
        new_reservation = old_reservation._replace(active=False, timestamp=time.time())
        return Control(
            ctype=ControlType.FREE,
            data=new_reservation,
        )
    # RESERVE
    if data["Req"] == "reserve" and "App" in data and "Host" in data and "User" in data:
        logger.debug("[RESERVE] request")
        return Control(
            ctype=ControlType.RESERVE,
            data=Reservation(
                active=False,
                app=data["App"],
                host=data["Host"],
                user=data["User"],
                timestamp=time.time(),
            ),
        )
    logger.error("Unknown control message received.")
    return Control(ControlType.UNKNOWN, nodata)
