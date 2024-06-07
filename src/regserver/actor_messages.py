"""This module implements all data classes used as actor messages to transport
commands and data within the actor system

:Created:
    2022-01-19

:Author:
    | Michael Strey <strey@sarad.de>

"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Tuple, Union

from sarad.sari import FamilyDict, Route  # type: ignore
from thespian.actors import ActorAddress  # type: ignore

from regserver.hostname_functions import compare_hostnames


@unique
class Status(Enum):
    """Status messages that may be used as part of actor messages.
    They are especially used in messages to the actor system."""

    OK = 0
    OCCUPIED = 6
    OK_SKIPPED = 10
    NOT_FOUND = 11
    IS_NOT_FOUND = 12
    ATTRIBUTE_ERROR = 13
    OTHER_APP_USER = 14
    ENDPOINT_NOT_FOUND = 15
    NOT_SUPPORTED = 16
    MQTT_ERROR = 17
    OK_UPDATED = 20
    SUBSCRIBE = 34
    UNSUBSCRIBE = 35
    UNKNOWN_PORT = 40
    RESERVE_PENDING = 95
    FREE_PENDING = 96
    INDEX_ERROR = 97
    ERROR = 98
    CRITICAL = 99

    def __str__(self):
        longform = {
            0: "OK",
            6: "Device occupied",
            10: "OK, skipped",
            11: "Device not found.",
            12: "Instrument server not found",
            13: "No or incomplete attributes",
            14: "Instrument reserved for other app or other user",
            15: "The end point was not found in the REST API of the remote side.",
            16: "This operation is not supported by the system.",
            17: "Monitoring mode failed. MQTT failure.",
            20: "OK, updated",
            34: "Error when subscribing to an MQTT topic",
            35: "Error when unsubscribing from an MQTT topic",
            40: "Port does not exist.",
            97: "Index error",
            98: "Unknown error",
            99: "Critical error. Stop and shutdown system.",
        }
        return longform[self.value]


class Frontend(Enum):
    """One item for every possible frontend of of the RegServer or Instrument Server

    `config["FRONTENDS"]` will contain a list of frontends that are active in
    the application defined by this configuration.
    """

    REST = 1
    MDNS = 2
    MQTT = 4
    MODBUS_RTU = 8


class Backend(Enum):
    """One item for every possible backend of of the RegServer or Instrument Server

    `config["BACKENDS"]` will contain a list of backends that are active in
    the application defined by this configuration.
    """

    USB = 1
    MDNS = 2
    MQTT = 4
    IS1 = 8


class ActorType(Enum):
    """Class to identify the type of an Actor.

    Used in BaseActor."""

    NONE = 0
    DEVICE = 1
    HOST = 2
    NODE = 4


class TransportTechnology(IntEnum):
    """Class to identify the transport technology used to connect an instrument."""

    LOCAL = 0
    LAN = 1
    MQTT = 2
    IS1 = 3
    NONE = 10

    def __str__(self):
        longform = {
            0: "local",
            1: "LAN, advertised by ZeroConf",
            2: "MQTT",
            3: "IS1 via WLAN",
            10: "None",
        }
        return longform[self.value]


class Family(Enum):
    """Class to identify the instrument family."""

    DOSEMAN = 1
    RSC = 2
    DACM = 5

    def __str__(self):
        longform = {
            1: "Doseman family",
            2: "Radon Scout family",
            5: "DACM family",
        }
        return longform[self.value]


@dataclass
class InstrObj:
    """Object containing the properties identifying and describing a SARAD
    instrument within the SARAD network.

    Args:
        instr_id: A unique id identifying every SARAD instrument.
                  Encoding name, family and type.
        serial_number: Serial number of the instrument.
        firmware_version: Version of the firmware on the instrument.
        host: FQDN of the host the instrument is physically connected to.
    """

    instr_id: str
    serial_number: int
    firmware_version: int
    host: str


@dataclass
class HostObj:
    # pylint: disable=too-many-instance-attributes
    """Object containing the properties identifying and describing a host
    within the SARAD network.

    Args:
        host: FQDN of the host the instrument is physically connected to.
        is_id: An alias identifying the Instrument Server.
        transport_technology: How is the instrument connected to this RegServer?
        description: Free text string describing the host.
        place: Name of the place where the host is situated.
        latitude: Latitude of the place. Positive values are north, negatives are south.
        longitude: Longitude of the place. Positive values are east, negatives are west.
        altitude: Altitude of the place.
        state (int): 2 = online, 1 = connected, no instruments, 0 = offline
        version: Software revision of the SARAD Registration Server service
                 running on this host.
        running_since (datetime): Date and time (UTC) of the latest restart
                                  of the SARAD Registration Server service.
    """

    host: str
    is_id: str
    transport_technology: TransportTechnology
    description: str
    place: str
    latitude: float
    longitude: float
    altitude: int
    state: int
    version: str
    running_since: datetime


@dataclass(frozen=True)
class Is1Address:
    """Object containing the address information of an Instrument Server 1

    Args:
        hostname (str): hostname of instrument server
        port (int): IP port number
    """

    hostname: str = field(init=True, repr=True, hash=True, compare=True)
    port: int

    def __eq__(self, other):
        return compare_hostnames(self.hostname, other.hostname)


@dataclass
class SetupMsg:
    """Message used to send setup information after actor __init__.

    Args:
        actor_id (str): Unique Id of the actor.
                        Can be used to identify the device if the actor is a device actor.
        parent_id (str): Actor Id if the parent is an actor, actor_system else.
        registrar (ActorAddress): Actor address of the registrar
        asys_address (ActorAddress): Address of the ActorSystem endpoint
                                     that initiated the creation of this Actor
    """

    actor_id: str
    parent_id: str
    registrar: ActorAddress
    asys_address: ActorAddress


@dataclass
class SetupComActorMsg:
    """Message used to send the special setup information required for ComActors.
    The parameters are required to identify the instr_id for the SaradInst object
    for serial communication with the instrument.

    Args:
        route (Route): Serial interface port, RS-485 bus address and ZigBee
                       address of the instrument.
        loop_interval (int): Polling interval for instrument detection in seconds.
    """

    route: Route
    loop_interval: int


@dataclass
class SetupHostActorMsg:
    """Message used to send the special setup information required for HostActors.

    Args:
        host: Hostname of the host running the instrument server
        port: Port address of the REST API
        scan_interval (int): Polling interval for instrument detection via REST API
                             in seconds. 0 = don't scan!
    """

    host: str
    port: int
    scan_interval: int


@dataclass
class SetupUsbActorMsg:
    """Message used to send the special setup information required for USB Actors.
    The parameters are required to create the SaradInst object for serial communication
    with the instrument.

    Args:
        route (Route): Serial interface port, RS-485 bus address and ZigBee
                       address of the instrument.
        family (FamilyDict): Instrument family from instruments.yaml
        poll (bool): If True, the instrument shall regularly be checked for availability.
                     Important for DOSEman sitting on IR cradle.
    """

    route: Route
    family: FamilyDict
    poll: bool


@dataclass
class SetupMdnsActorMsg:
    """Message used to send the special setup information required for mDNS device Actors.
    The parameters are required to establish the socket connection to the Instrument Server 2.

    Args:
        is_host (str): IP address of IS2.
        api_port (int): Port the REST API of IS2 is on.
        device_id (str): Device Id at the remote host.
    """

    is_host: str
    api_port: int
    device_id: str


@dataclass
class FinishSetupUsbActorMsg:
    """Message from UsbActor indicating that initialization was completed.

    Args:
        success (bool): True, if the setup was successful
    """

    success: bool


@dataclass
class SetupMdnsAdvertiserActorMsg:
    """Message used to send the special setup information required for mDNS Advertiser Actors.
    The parameters are required to advertise the raw socket connection via Zeroconf.

    Args:
        device_actor (ActorAddress): address of the associated device actor
    """

    device_actor: ActorAddress


@dataclass
class SetDeviceStatusMsg:
    """Message used to send setup information about the device status to a Device Actor.

    Args:
        device_status (dict): Dictionary with status information of the instrument.
    """

    device_status: Dict[str, object]


@dataclass
class SubscribeMsg:
    """Message sent from an actor to the Registrar actor to confirm the successful setup.

    Args:
        actor_id (str): Unique Id of the actor.
                        Can be used to identify the device if the actor is a device actor.
        parent (ActorAddress): Address of the parent actor.
        actor_type (ActorType): Used to identify whether this is a Device or Host Actor.
        get_updates (bool): True if the actor shall receive updates
                            of the Actor Dictionary from the Registrar actor.
        keep_alive (bool): True indicates that this is a follow-up SubscribeMsg.
                           False if this is the initial SubscribeMsg.
    """

    actor_id: str
    parent: ActorAddress
    actor_type: ActorType = ActorType.NONE
    get_updates: bool = False
    keep_alive: bool = False


@dataclass
class UnsubscribeMsg:
    """Message sent in the ActorExitRequest handler from an actor to the Registrar
    actor to confirm the exit of this actor.

    Args:
        actor_address (ActorAddress): Address of the Actor that is about to disappear.
    """

    actor_address: ActorAddress


@dataclass
class Parent:
    """Description of the parent actor."""

    parent_id: str
    parent_address: ActorAddress


@dataclass
class KeepAliveMsg:
    """Message sent to an actor from its parent actor in order to check
    whether the actor is still existing.

    The Actor shall send a SubscribeMsg to the Registrar, if `report` is True.

    Args:
        parent (Parent): Actor Id and address of the parent Actor sending the KeepAliveMsg.
        child (str): Actor Id of the child Actor the KeepAliveMsg is addressed to.
        report (bool): True, if the child shall send a SubscribeMsg to Registrar.
    """

    parent: Parent
    child: str
    report: bool


@dataclass
class DeadChildMsg:
    """Message triggering the receiving Actor to check it's list of children
    for the child Actor given in Args.
    If the child is still in the list of children, it shall cause an emergency shutdown.

    Args:
        child: str
    """

    child: str


@dataclass
class SubscribeToActorDictMsg:
    """Message to subscribe an actor to the Actor Dictionary maintained in the
    Registrar actor.

    Args:
        actor_id (str): Unique Id of the actor that shall receive the updates.
    """

    actor_id: str


@dataclass
class UnSubscribeFromActorDictMsg:
    """Message to unsubscribe an actor from the Actor Dictionary maintained in the
    Registrar actor.

    Args:
        actor_id (str): Unique Id of the actor that shall not receive updates anymore.
    """

    actor_id: str


@dataclass
class UpdateActorDictMsg:
    """Message containing the updated Actor Dictionary from Registrar Actor.
    {actor_id: {"is_alive": bool,
                "address": actor address,
                "parent": actor_address,
                "actor_type": ActorType,
                "get_updates": bool,  # actually not used in subscribers!
               }
    }

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
    to the Registrar actor.

    Args:
        register (bool): If True, the receiving actor shall send an UnsubscribeMsg
                         to the Registrar.
    """

    register: bool = True


@dataclass
class TxBinaryMsg:
    """Message sent to an actor to forward data from the app to the SARAD instrument.

    Args:
        data (bytes): Binary data to be forwarded.
    """

    data: bytes


@dataclass
class RxBinaryMsg:
    """Message sent to an actor to forward data from the SARAD instrument to the app.

    Args:
        data (bytes): Binary data to be forwarded.
    """

    data: bytes


@dataclass
class ReserveDeviceMsg:
    """Request to reserve an instrument. Sent from API to Device Actor.

    Args:
        host (str): Host requesting the reservation.
        user (str): Name of the user requesting the reservation.
        app (str): Application requesting the reservation
        create_redirector (bool): True, if the receiving Actor shall create a Redirector Actor
    """

    host: str
    user: str
    app: str
    create_redirector: bool = False


@dataclass
class ReservationStatusMsg:
    """Message to inform the REST API about the result of the ReserveDeviceMsg.

    Args:
        instr_id (str): instrument id
        status: either OK, OK_SKIPPED or OCCUPIED
    """

    instr_id: str
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
class UnSubscribeFromDeviceStatusMsg:
    """Message to unsubscribe the sender from updates of the device status information
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

    This message will be sent by a device actor whenever the status of the
    device has changed or when a ReserveDeviceMsg or FreeDeviceMsg was handled
    completely.

    Args:
        device_id (str): Device Id in long form
        device_status (dict): Dictionary with status information of the instrument.

    """

    device_id: str
    device_status: Dict[str, str]


@dataclass
class GetDeviceStatusesMsg:
    """Request to get the dictionary of device statuses
    for all active connected instruments from Registrar."""


@dataclass
class UpdateDeviceStatusesMsg:
    """Message with updated device status information for all instruments.

    Args:
        device_statuses (dict): Dictionary with status information of all instruments.
    """

    device_statuses: Dict[str, Dict[str, str]]


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
class RescanMsg:
    """Request to rebuild the list of instruments.

    The RescanMsg can be sent to the Cluster Actor, a Host Actor or to the MQTT Listener.

    Args:
       host: FQDN of the host that shall receive the command.
             If None, all availabel hosts will be addressed.
    """

    host: Union[str, None] = None


@dataclass
class RescanAckMsg:
    """Confirmation that the RescanMsg was handled properly."""

    status: Status


@dataclass
class ShutdownMsg:
    """Request to shutdown the Regserver on a given host for a restart.

    The ShutdownMsg can be sent to the Cluster Actor, a Host Actor or to the MQTT Listener.

    Args:
       password: Forward password given on the REST API
       host: FQDN of the host that shall receive the command.
             If None, all availabel hosts will be addressed.
    """

    password: str
    host: Union[str, None] = None


@dataclass
class ShutdownAckMsg:
    """Confirmation that the ShutdownMsg was handled properly."""

    status: Status


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
class PrepareMqttActorMsg:
    """Message with information to setup the MQTT client of the MQTT Actor."""

    client_id: str
    group: str


@dataclass
class MqttConnectMsg:
    """Request to connect the MQTT client of the receiving MQTT Actor."""


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


@dataclass
class GetRecentValueMsg:
    """Message sent from REST API or Modbus Actor to Device Actor in order to
    initiate a get_recent_value command on a DACM instrument.

    Args:
        component (int): Index of the DACM component
        sensor (int): Index of the DACM sensor/actor
        measurand (int): Index of the DACM measurand
    """

    component: int
    sensor: int
    measurand: int


@dataclass
class Gps:
    """GPS data"""

    valid: bool
    latitude: float = 0
    longitude: float = 0
    altitude: float = 0
    deviation: float = 0


@dataclass
class RecentValueMsg:
    # pylint: disable=too-many-instance-attributes
    """Message sent from the Device Actor of an DACM instrument as reply to a GetRecentValueMsg.

    Args:
        status (Status): Error status
        instr_id (str): Instrument id
        component_name (str): Name of the DACM component
        sensor_name (str): Name of the sensor within the DACM component (derived from Result Index)
        measurand_name (str): Name of the measurand delivered by the sensor
                              (derived from Item Index)
        measurand (str): Complete measurand (value and unit) as string
        operator (str): Operator associated (i.e. < or >)
        value (float): Value of the measurand
        unit (str): Measuring unit for this value
        timestamp (float): POSIX timestamp of the measuring (end of integration interval)
        utc_offset (int): Offset of the RTC of the instrument to UTC, None if unknown
        sample_interval (int): Duration of sample interval in seconds
        gps (Gps): Parameters from builtin GPS receiver
    """

    status: Status
    instr_id: str = ""
    component_name: str = ""
    sensor_name: str = ""
    measurand_name: str = ""
    measurand: str = ""
    operator: str = ""
    value: float = 0
    unit: str = ""
    timestamp: Union[float, None] = None
    utc_offset: Union[int, None] = None
    sample_interval: int = 0
    gps: Union[Gps, None] = None


@dataclass
class GetHostInfoMsg:
    """Message that can be sent to any Actor holding host information.

    These might be the Registrar, Host Actors, MQTT Listener, IS1 Listener and Cluster.
    The Actor has to respond with a HostInfoMsg.
    Usually the Registrar will send this message to the
    MQTT Listener and to the Host Actors in its receiveMsg_SubscribeMsg handler.

    Args:
        host (str): FQDN of the host or None.
                    In the latter case the Actor shall give back information
                    about all hosts he is aware about.
    """

    host: Union[str, None] = None


@dataclass
class HostInfoMsg:
    """Message containing information about at least one host.

    Has to be sent from the Registrar, Host Actors, MQTT Listener, IS1 Listener
    or Cluster as reply to a GetHostInfoMsg.
    The MQTT Listener sends HostInfoMsg to the Registrar on every host update.

    Args:
        hosts (List[HostObj]): List of Host objects
    """

    hosts: List[HostObj]


@dataclass
class ResurrectMsg:
    """Message causing a parent actor to get an update about connected
    instruments from the Instrument Server in order to possibly resurrect a
    killed Device Actor.

    Args:
        is_id (str): Id of the Instrument Server

    """

    is_id: str


@dataclass
class MqttPublishMsg:
    """Message instructing the singleton MQTT Client Actor to publish a message.

    Args:
        topic (str): The MQTT topic.
        payload (str): The MQTT payload.
        qos (int): Quality of service.
        retain (bool): True if the message shall be retained by the broker.
    """

    topic: str
    payload: str
    qos: int
    retain: bool


@dataclass
class MqttSubscribeMsg:
    """Message instructing the singleton MQTT Client Actor to subscribe to a topic.

    Args:
        sub_info (List[Tupel[str, int]]): List of tupels of (topic, qos)
        to subscribe to.
    """

    sub_info: List[Tuple[str, int]]


@dataclass
class MqttUnsubscribeMsg:
    """Message instructing the singleton MQTT Client Actor to unsubscribe from a topic.

    Args:
        topics (List[str]): List of topics.
    """

    topics: List[str]


@dataclass
class MqttReceiveMsg:
    """Message forwarding a MQTT message from the singleton MQTT Client Actor
    to the MQTT Device Actor.

    Args:
        topic (str): The MQTT topic
        payload (str): JSON payload
    """

    topic: str
    payload: str


@dataclass
class StartMonitoringMsg:
    """Message instructing the Device Actor to (re-)start the measuring
    at a given time or immediately, respectively.

    Args:
        instr_id (str): Id of the instrument
        start_time (datetime): Date and time to start the measuring on.
                               If None, the measuring shall start immediately.
                               Always given as UTC.
    """

    instr_id: str
    start_time: datetime = datetime.now(timezone.utc)


@dataclass
class StartMonitoringAckMsg:
    """Confirmation that the StartMonitoringMsg was handled properly.

    Args:
        instr_id (str): Id of the instrument
        status (Status): Status of the success of the operation
        offset (timedelta): Time difference between start time and now.
    """

    instr_id: str
    status: Status
    offset: timedelta


@dataclass
class BaudRateMsg:
    """Message instructing the Device Actor to change the baud rate.

    Args:
        instr_id (str): Id of the instrument
        baud_rate (int): Baud rate the serial interface shall use
    """

    instr_id: str
    baud_rate: int


@dataclass
class BaudRateAckMsg:
    """Confirmation that the BaudRateMsg was handled properly."""

    status: Status


@dataclass
class SetRtcMsg:
    """Message instructing the Device Actor to set the RTC of the instrument.

    Args:
        instr_id (str): Id of the instrument
    """

    instr_id: str


@dataclass
class SetRtcAckMsg:
    """Confirmation that the SetRtcMsg was handled properly.

    Args:
        instr_id (str): Id of the instrument
        status (Status): Status of the success of the operation
        utc_offset (float): Offset to UTC that was used to set the RTC, -13 = unknown
        wait (int): Waiting time in seconds before the setup will take effect
    """

    instr_id: str
    status: Status
    utc_offset: float = -13
    wait: int = 0


@dataclass
class ControlFunctionalityMsg:
    """Message that can be sent to the Registrar in order to switch single
    Frontends or Backends on or off.

    Args:
        actor_id (str): Id of the Actor that shall be started or stopped
        on (bool): True, if the Actor shall be switched on; False,
                   if it shall be switched off.
    """

    actor_id: str
    on: bool
