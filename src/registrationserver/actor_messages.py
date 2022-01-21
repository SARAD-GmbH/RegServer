"""This module implements all data classes used as actor messages to transport
commands and data within the actor system

:Created:
    2022-01-19

:Author:
    | Michael Strey <strey@sarad.de>

"""
from dataclasses import dataclass
from enum import Enum
from typing import ByteString

from thespian.actors import ActorAddress  # type: ignore


class AppType(Enum):
    """Indicates the type of the application that shall be implemented
    with the Actor System.

    The program can be started either as Instrument Server (ISMQTT or IS2) or
    as Registration Server (RS).
    There are three main files:

    * main.py for the Registration Server,
    * ismqtt_main.py for Instrument Server MQTT,
    * is2_main.py for Instrument Server 2,

    where `config["APP_TYPE]` will be set with the appropriate AppType.
    """

    ISMQTT = 1
    IS2 = 2
    RS = 3


@dataclass
class SetupMsg:
    """Message used to send setup information after actor __init__.
    The device_status parameter is only used for the setup of Device Actors.

    Args:
        actor_id (str): Unique Id of the actor.
                        Can be used to identify the device if the actor is a device actor.
        parent_id (str): Actor Id if the parent is an actor, actor_system else.
    """

    actor_id: str
    parent_id: str
    app_type: AppType


@dataclass
class SetDeviceStatusMsg:
    """Message used to send setup information about the device status to a Device Actor.

    Args:
        device_status (dict): Dictionary with status information of the instrument.
    """

    device_status: dict


@dataclass
class SubscribeMsg:
    """Message sent from an actor to the Registrar actor to confirm the successful setup.

    Args:
        actor_id (str): Unique Id of the actor.
                        Can be used to identify the device if the actor is a device actor.
        parent (ActorAddress): Address of the parent actor.
        is_device_actor (bool): True if the actor is a Device Actor.
        get_updates (bool): True if the actor shall receive updates
                            of the Actor Dictionary from the Registrar actor.
    """

    actor_id: str
    parent: ActorAddress
    is_device_actor: bool = False
    get_updates: bool = False


@dataclass
class UnsubscribeMsg:
    """Message sent in the ActorExitRequest handler from an actor to the Registrar
    actor to confirm the exit of this actor.

    Args:
        actor_id (str): Unique Id of the actor.
                        Can be used to identify the device if the actor is a device actor.
    """

    actor_id: str


@dataclass
class KeepAliveMsg:
    """Message sent to an actor from its parent actor in order to check
    whether the actor is still existing.

    The actor shall reply with sending a SubscribeMsg to the Registrar."""


@dataclass
class SubscribeToActorDictMsg:
    """Message to subscribe an actor to the Actor Dictionary maintained in the
    Registrar actor.

    Args:
        actor_id (str): Unique Id of the actor that shall receive the updates.
    """

    actor_id: str


@dataclass
class UpdateActorDictMsg:
    """Message containing the updated Actor Dictionary from Registrar Actor.

    Args:
        actor_dict (dict): Actor Dictionary.
    """

    actor_dict: dict


@dataclass
class KillMsg:
    """Message sent to an actor to trigger the exit of this actor. The actor has to
    forward this message to all of its children an finally sends an UnsubscribeMsg
    to the Registrar actor."""


@dataclass
class TxBinaryMsg:
    """Message sent to an actor to forward data from the app to the SARAD instrument.

    Args:
        data (ByteString): Binary data to be forwarded.
        host (str): Host sending the data, to check reservation at the Instrument Server.
    """

    data: ByteString
    host: str


@dataclass
class RxBinaryMsg:
    """Message sent to an actor to forward data from the SARAD instrument to the app.

    Args:
        data (ByteString): Binary data to be forwarded.
    """

    data: ByteString


@dataclass
class ReserveDeviceMsg:
    """Request to reserve an instrument. Sent from API.

    Args:
        host (str): Host requesting the reservation.
        user (str): Name of the user requesting the reservation.
        app (str): Application requesting the reservation
    """

    host: str
    user: str
    app: str


class ReservationStatus(Enum):
    """Indicates the reservation status of the instrument."""

    FREE = 0
    OCCUPIED = 1


@dataclass
class ReservationStatusMsg:
    """Message to inform about the result of the ReserveDeviceMsg.

    Args:
        reservation_status: either FREE or OCCUPIED
    """

    reservation_status: ReservationStatus


@dataclass
class FreeDeviceMsg:
    """Request to free an instrument from the reservation. Sent from API to Device Actor."""


@dataclass
class SubscribeToDeviceStatusMsg:
    """Message to subscribe the sender to updates of the device status information
    collected in the Device Actor.

    Args:
        actor_id (str): Unique Id of the actor that shall receive the updates.
    """

    actor_id: str


@dataclass
class UpdateDeviceStatusMsg:
    """Message with updated device status information for an instrument.

    Args:
        instr_id (str): Instrument id
        device_status (dict): Dictionary with status information of the instrument.
    """

    instr_id: str
    device_status: dict


@dataclass
class SocketMsg:
    """Message sent from the Redirector Actor to the Device Actor after
    establishing a server socket to connect the app.

    Args:
        ip (str): IP address of the listening server socket.
        port (int): Port number of the listening server socket.
    """

    ip_address: str
    port: int


@dataclass
class ReceiveMsg:
    """Request to start another loop of the _receive_loop function
    in the Redirector Actor."""


@dataclass
class InstrAddedMsg:
    """Request to add a new instrument."""


@dataclass
class InstrRemovedMsg:
    """Request to remove a instrument."""


"""
                "FREE": "_on_free_cmd",
                "SEND": "_on_send_cmd",
                "LIST": "_on_list_cmd",
                "LIST-USB": "_on_list_usb_cmd",
                "LIST-NATIVE": "_on_list_natives_cmd",
                "LOOP": "_on_loop_cmd",
                "LOOP-REMOVE": "_on_loop_remove_cmd",
                "LIST-PORTS": "_on_list_ports_cmd",
"""
