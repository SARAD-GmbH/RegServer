"""This module implements all data classes used as actor messages to transport
commands and data within the actor system

:Created:
    2022-01-19

:Author:
    | Michael Strey <strey@sarad.de>

"""
from dataclasses import dataclass
from enum import Enum, auto, unique
from typing import Any, ByteString, Dict, List, Union

from sarad.sari import FamilyDict  # type: ignore
from thespian.actors import ActorAddress  # type: ignore


@unique
class Status(Enum):
    """Status messages that may be used as part of actor messages.
    They are especially used in messages to the actor system."""

    OK = 0
    OCCUPIED = 6
    OK_SKIPPED = 10
    NOT_FOUND = 11
    ATTRIBUTE_ERROR = 13
    OK_UPDATED = 20
    SUBSCRIBE = 34
    UNSUBSCRIBE = 35
    UNKNOWN_PORT = 40
    CRITICAL = 99

    def __str__(self):
        longform = {
            0: "OK",
            6: "Device occupied",
            10: "OK, skipped",
            11: "Device not found.",
            13: "No or incomplete attributes",
            20: "OK, updated",
            34: "Error when subscribing to an MQTT topic",
            35: "Error when unsubscribing from an MQTT topic",
            40: "Port does not exist.",
            99: "Critical error. Stop and shutdown system.",
        }
        return longform[self.value]


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

    ISMQTT = auto()
    IS2 = auto()
    RS = auto()


@dataclass
class SetupMsg:
    """Message used to send setup information after actor __init__.

    Args:
        actor_id (str): Unique Id of the actor.
                        Can be used to identify the device if the actor is a device actor.
        parent_id (str): Actor Id if the parent is an actor, actor_system else.
    """

    actor_id: str
    parent_id: str
    app_type: AppType


@dataclass
class SetupUsbActorMsg:
    """Message used to send the special setup information required for USB Actors.
    The parameters are required to create the SaradInst object for serial communication
    with the instrument.

    Args:
        port (str): Serial interface port of the instrument.
        family (FamilyDict): Instrument family from instruments.yaml
    """

    port: str
    family: FamilyDict


@dataclass
class SetDeviceStatusMsg:
    """Message used to send setup information about the device status to a Device Actor.

    Args:
        device_status (dict): Dictionary with status information of the instrument.
    """

    device_status: Dict[str, str]


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
        keep_alive (bool): True indicates that this is a follow-up SubscribeMsg.
                           False if this is the initial SubscribeMsg.
    """

    actor_id: str
    parent: ActorAddress
    is_device_actor: bool = False
    get_updates: bool = False
    keep_alive: bool = False


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

    actor_dict: Dict[str, Any]


@dataclass
class GetActorDictMsg:
    """Request to get the Actor Dictionary from Registrar Actor once."""


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
    host: Union[str, None]


@dataclass
class RxBinaryMsg:
    """Message sent to an actor to forward data from the SARAD instrument to the app.

    Args:
        data (ByteString): Binary data to be forwarded.
    """

    data: ByteString


@dataclass
class ReserveDeviceMsg:
    """Request to reserve an instrument. Sent from API to Device Actor.

    Args:
        host (str): Host requesting the reservation.
        user (str): Name of the user requesting the reservation.
        app (str): Application requesting the reservation
    """

    host: str
    user: str
    app: str


@dataclass
class ReservationStatusMsg:
    """Message to inform about the result of the ReserveDeviceMsg.

    Args:
        status: either OK, OK_SKIPPED or OCCUPIED
    """

    status: Status


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
class GetDeviceStatusMsg:
    """Request to get the device status from Device Actor once."""


@dataclass
class UpdateDeviceStatusMsg:
    """Message with updated device status information for an instrument.

    Args:
        device_id (str): Device Id in long form
        device_status (dict): Dictionary with status information of the instrument.
    """

    device_id: str
    device_status: Dict[str, str]


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
    status: Status


@dataclass
class ReceiveMsg:
    """Request to start another loop of the _receive_loop function
    in the Redirector Actor."""


@dataclass
class InstrAddedMsg:
    """Request to add a new instrument."""


@dataclass
class InstrRemovedMsg:
    """Request to remove an instrument."""


@dataclass
class AddPortToLoopMsg:
    """Request to set a serial interface or a list of serial interfaces
    to the list of interfaces for polling."""

    ports: Union[str, List[str]]


@dataclass
class RemovePortFromLoopMsg:
    """Request to remove a serial interface or a list of serial interfaces
    from the list of interfaces for polling."""

    ports: Union[str, List[str]]


@dataclass
class ReturnLoopPortsMsg:
    """Returns the list of serial interfaces included in polling."""

    ports: List[str]


@dataclass
class GetLocalPortsMsg:
    """Request to send a list of all local serial interfaces."""


@dataclass
class ReturnLocalPortsMsg:
    """Returns the list of local serial interfaces."""

    ports: List[Dict[str, str]]


@dataclass
class GetUsbPortsMsg:
    """Request to send a list of all local serial USB interfaces."""


@dataclass
class ReturnUsbPortsMsg:
    """Returns the list of serial USB interfaces."""

    ports: List[str]


@dataclass
class GetNativePortsMsg:
    """Request to send a list of all local RS-232 interfaces."""


@dataclass
class ReturnNativePortsMsg:
    """Returns the list of local RS-232 interfaces."""

    ports: List[str]


@dataclass
class ConnectMsg:
    """Request to start the listening server socket connecting to the app and
    to redirect all incoming binary data to the device actor."""


@dataclass
class PrepareMqttActorMsg:
    """Message with information to setup the MQTT client of the MQTT Actor."""

    is_id: Union[str, None]
    client_id: str


@dataclass
class CreateActorMsg:
    """Request to the Registrar to create a new actor.
    This is usually sent to the Registrar from the surrounding program
    and will be answered by an ActorCreatedMsg."""

    actor_type: Any
    actor_id: str


@dataclass
class ActorCreatedMsg:
    """Message sent by the Registrar to inform the recipient about
    a newly created actor."""

    actor_address: ActorAddress


@dataclass
class GetDeviceActorMsg:
    """Request to the Registrar to send back the address of the Device Actor
    with the given device_id."""

    device_id: str


@dataclass
class ReturnDeviceActorMsg:
    """Message from the Registrar returning the Device Actor address
    requested with GetDeviceActorMsg."""

    actor_address: ActorAddress
