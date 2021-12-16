"""Contains functions and classes for converting SARAD Network MQTT messages and topic names

Created:
    2021-06-22

Author:
    Riccardo Förster <riccardo.foerster@sarad.de>
"""
import contextlib
import json
import time
from decimal import Decimal
from enum import Enum
from typing import NamedTuple, Optional

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
    FREE = 1
    RESERVE = 2


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


def get_instr_meta(data: InstrumentMeta) -> str:
    """Converting instrument meta information into MQTT payload"""
    return json.dumps(
        {
            "State": data.state,
            "Identification": {
                "Family": data.family,
                "Host": data.host or "unknown",
                "Name": data.name,
                "Type": data.instrumentType,
                "Serial number": data.serial,
            },
        }
    )


def get_instr_meta_msg(json_data) -> Optional[InstrumentMeta]:
    """Converting MQTT payload containing instrument meta data into InstrumentMeta
    object"""
    with contextlib.suppress(json.decoder.JSONDecodeError):
        data = json.loads(json_data.payload)
        integrity_check = [
            "State" not in data,
            "Identification" not in data,
            "Family" not in data["Identification"],
            "Host" not in data["Identification"],
            "Name" not in data["Identification"],
            "Serial number" not in data["Identification"],
        ]
        if any(integrity_check):
            return None
        return InstrumentMeta(
            state=data["State"],
            host=data["Identification"]["Host"],
            family=data["Identification"]["Family"],
            instrumentType=data["Identification"]["Type"],
            name=data["Identification"]["Name"],
            serial=data["Identification"]["Serial number"],
        )
    return None


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


def add_instr(*, client, is_id: str, instr_id: str, device_status, subscriptions):
    """Helper function to deal with adding/marking an instrument active"""
    # def subscribe(self, topic, qos=0, options=None, properties=None):
    new_subscriptions = [
        (f"{is_id}/{instr_id}/control", 0),
        (f"{is_id}/{instr_id}/cmd", 0),
    ]
    client.subscribe(new_subscriptions)
    for (topic, qos) in new_subscriptions:
        subscriptions[topic] = qos
    identification = device_status["Identification"]
    mypayload = InstrumentMeta(
        state=2,
        host=is_id,
        family=identification.get("Family"),
        instrumentType=identification.get("Type"),
        name=identification.get("Name"),
        serial=identification.get("Serial number"),
    )
    logger.debug("Payload: %s", mypayload)
    # def publish(self, topic, payload=None, qos=0, retain=False, properties=None):
    client.publish(
        retain=True,
        topic=f"{is_id}/{instr_id}/meta",
        payload=get_instr_meta(data=mypayload),
    )


def del_instr(*, client, is_id: str, instr_id: str, subscriptions):
    """Helper function to deal with marking an instrument as removed"""
    # def unsubscribe(self, topic, properties=None):
    gone_subscriptions = [f"{is_id}/{instr_id}/control", f"{is_id}/{instr_id}/cmd"]
    client.unsubscribe(gone_subscriptions)
    for topic in gone_subscriptions:
        subscriptions.pop(topic)
    mypayload = get_instr_meta(
        data=InstrumentMeta(
            state=0,
            host=is_id,
            family=0,
            instrumentType=0,
            name="unknown",
            serial=0,
        )
    )
    # def publish(self, topic, payload=None, qos=0, retain=False, properties=None):
    client.publish(
        retain=True,
        topic=f"{is_id}/{instr_id}/meta",
        payload=mypayload,
    )


def del_is(*, client, is_id: str, is_meta):
    """Helper function to deal with marking the instrument server as removed"""
    # def unsubscribe(self, topic, properties=None):
    client.unsubscribe(topic="+")
    client.publish(
        retain=True,
        topic=f"{is_id}/meta",
        payload=get_is_meta(is_meta),
    )
