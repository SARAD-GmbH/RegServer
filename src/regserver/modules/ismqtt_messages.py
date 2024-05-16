"""Contains functions and classes for converting SARAD Network MQTT messages and topic names

Created:
    2021-06-22

Author:
    Riccardo Förster <riccardo.foerster@sarad.de>
"""

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum, auto
from typing import List, Tuple, Union

from regserver.actor_messages import Status
from regserver.logger import logger


@dataclass
class InstrumentServerMeta:  # pylint: disable=too-many-instance-attributes
    """Data class for storing Instrument Server meta information"""

    state: int
    host: str
    is_id: str
    description: str
    place: str
    latitude: Decimal
    longitude: Decimal
    height: Decimal
    version: str
    running_since: datetime


@dataclass
class InstrumentMeta:
    """Data class for storing SARAD Instrument meta information"""

    state: int
    host: str
    family: int
    instrument_type: int
    name: str
    serial: int


@dataclass
class Reservation:
    """Data class for storing instrument reservation information"""

    timestamp: float
    active: bool = False
    app: str = ""
    host: str = ""
    user: str = ""
    status: Status = Status.OK

    def __eq__(self, other):
        return (
            self.active == other.active
            and self.app == other.app
            and self.host == other.host
            and self.user == other.user
            and self.status == other.status
        )


@dataclass
class ValueRequest:
    """Data class for storing instrument reservation information"""

    component: int
    sensor: int
    measurand: int
    app: str = ""
    host: str = ""
    user: str = ""


@dataclass
class ConfigRequest:
    """Data class for storing instrument reservation information"""

    cycle: int
    values: List[Tuple[int]]


class ControlType(Enum):
    """Types of control messages"""

    UNKNOWN = 0
    FREE = auto()
    RESERVE = auto()
    VALUE = auto()
    MONITOR = auto()
    CONFIG = auto()


@dataclass
class Control:
    """Data class for storing instrument control messages"""

    ctype: ControlType
    data: Union[Reservation, ValueRequest, ConfigRequest, None]


def get_is_meta(data: InstrumentServerMeta) -> str:
    """Converting Instrument Server meta information into MQTT payload"""
    return json.dumps(
        {
            "State": data.state or 0,
            "Host": data.host or "unknown",
            "Descr": data.description or "SARAD Instrument Server2 Mqtt",
            "Place": data.place or "No description given",
            "Lat": data.latitude or 0,
            "Lon": data.longitude or 0,
            "Height": data.height or 0,
            "Ver": data.version or "unknown",
            "Since": data.running_since.isoformat(timespec="seconds") or "",
        },
    )


def get_instr_reservation(data: Reservation) -> str:
    """Converting reservation information into MQTT payload"""
    return json.dumps(
        {
            "Active": data.active,
            "App": data.app,
            "Host": data.host,
            "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "User": data.user,
        }
    )


def get_instr_control(json_data, old_reservation) -> Control:
    """Converting received MQTT payload into Control object"""
    nodata = Reservation(0, False, "", "", "")
    try:
        data = json.loads(json_data.payload)
    except (TypeError, json.decoder.JSONDecodeError):
        logger.warning("Cannot decode %s", json_data.payload)
        return Control(ControlType.UNKNOWN, nodata)
    if not "Req" in data:
        logger.error("No 'Req' in payload.")
        return Control(ctype=ControlType.UNKNOWN, data=nodata)
    req_type = data.get("Req", "")
    if req_type == "free":
        logger.debug("[FREE] request")
        if old_reservation is None:
            logger.debug("[FREE] not reserved, nothing to do")
            return Control(
                ctype=ControlType.FREE,
                data=nodata,
            )
        new_reservation = replace(old_reservation, active=False, timestamp=time.time())
        return Control(
            ctype=ControlType.FREE,
            data=new_reservation,
        )
    if req_type == "reserve":
        logger.debug("[RESERVE] request")
        return Control(
            ctype=ControlType.RESERVE,
            data=Reservation(
                active=True,
                app=data.get("App", "unknown"),
                host=data.get("Host", "unknown"),
                user=data.get("User", "unknown"),
                timestamp=time.time(),
            ),
        )
    if req_type == "value":
        pass
    if req_type == "monitor":
        pass
    if req_type == "config":
        pass

    logger.error("Unknown control message received. %s", data)
    return Control(ControlType.UNKNOWN, nodata)
