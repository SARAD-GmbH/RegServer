==============
Actor Messages
==============

General message structure
=========================

The general format for messages between defined actors is a Python dictionary.
We have two types of messages:

* Commands sent to the actor,
* Return messages sent by the actor as reply to a command.

Commands
--------

Commands consist of the keys:

CMD:
    The CMD key indicates that the message is a command that shall trigger the
    receiving actor to do something. The value of the CMD key contains the
    command type.

PAR (optional):
    contains optional parameters that differ from command to command.

Example::

  cmd_dict = {
      "CMD": "RESERVE",
      "PAR": {
          "HOST": request_host,
          "USER": user,
          "APP": app,
      },
  }

Return messages
---------------

Return messages consist of the following keys:

RETURN:
    The RETURN key indicates that this message is a return value belonging to a
    p bbreviously received command. The value contains the command type that caused
    the return message.

ERROR_CODE:
    integer to clearly identify the error.

RESULT (optional):
    contains additional result attributes that differ from command to command.

Examples::

  return_dict = {
      "RETURN": "RESERVE",
      "ERROR_CODE": 0,
      "RESULT": {
          "IP": 127.0.0.1,
          "PORT": 50000,
      },
  }

  return_dict = {
      "ERROR_CODE": 10,
      "RETURN": "RESERVE",
  }

CMDs handled by the DeviceBaseActor
===================================

SETUP
-----

Request to create the device file that is linked to the actor via its file name.

Sent from:
    MdnsListener/MqttSubscriber

Parameters:
    Content of the device file.

Example::

    {"Identification": {
        "Name": "RADON SCOUT HOME",
        "Family": 2,
         "Type": 8,
         "Serial number": 791,
         "Host": "mischka",
         "Protocol": "sarad-1688"},
     "Remote": {
         "Address": "192.168.178.20",
         "Port": 5580,
         "Name": "0ghMF8Y.sarad-1688._rfc2217._tcp.local."}}

Expected RETURN:
    ERROR_CODE:
        expected to be "OK" or "OK_UPDATED"

RESERVE
-------

Request to reserve an instrument.

Sent from:
    RestApi

Parameters:
    HOST:
        Host requesting the reservation
    USER:
        Username requesting the reservation
    APP:
        Application requesting the reservation

Expected RETURN:
    ERROR_CODE:
        expected to be "OK", "OK_SKIPPED", "OCCUPIED"


FREE
----

Request to free an instrument from the reservation.

Sent from:
    RestApi

Expected RETURN:
    ERROR_CODE:
        expected to be "OK", "OK_SKIPPED"

ActorExitRequest
----------------

Request the termination of an actor, sent when a device gets disconnected
from the accessable network.

Sent from:
    MdnsListener/MqttSubscriber

Expected RETURN:
    ERROR_CODE:
        expected to be "OK"


CMDs handled by the DeviceActor
===============================

SEND
----

Request from the Redirector Actor to a Device Actor to send a binary message to
the Instrument Server.

Sent from:
    RedirectorActor

Parameters:
    DATA:
        Contains the DATA so be sent
    HOST:
        Host requesting the DATA to be sent (for reservation checks at the Instrument Server)

Expected RETURN:
    ERROR_CODE:
        expected to be "OK", RESULT

RESULT attributes:
    DATA:
        containing DATA that the device sent back, None if ERROR_CODE is not "OK"


CMDs handled by the Redirector Actor
====================================

SETUP
-----

Request to initialize the Redirector Actor with the globalName of its parent Device Actor.

Sent from:
    BaseDeviceActor

Parameter:
    PARENT_NAME:
        globalName of the Device Actor that created this Redirector Actor

RESULT attributes:
    IP:
        IP address of the listening server socket
    PORT:
        Port number of the listening server socket

ActorExitRequest
----------------

Request the termination of the actor. Sent from the device actor when a the
reservation of a device gets cancelled by the FREE command from the REST API.

Sent from:
    DeviceBaseActor

Expected RETURN:
    ERROR_CODE:
        expected to be "OK"

CONNECT
-------

Request to accept incomming messages at the listening server socket.

Sent from:
    DeviceBaseActor or from self

Expected RETURN:
    No

RECEIVE
-------

Request to start another loop of the _receive_loop function.

Sent from:
    self

Expected RETURN:
    No


CMDs handled by the DeviceDB actor
==================================

CREATE
------

Request to create a new entry to the device database.

Sent from:
    DeviceBaseActor

Parameter:
    GLOBAL_NAME:
        globalName of the Device Actor
    ACTOR_ADDRESS:
        actor address of the Device Actor

Expected RETURN:
    No

Example::

  cmd_dict = {
      "CMD": "CREATE",
      "PAR": {
          "GLOBAL_NAME": <global_name>,
          "ACTOR_ADDRESS": <actor_address>,
      }
  }

REMOVE
------

Request to remove a device actor from the list.

Sent from:
    DeviceBaseActor

Parameter:
    GLOBAL_NAME:
        globalName of the Device Actor

Expected RETURN:
    No

Example::

  cmd_dict = {
      "CMD": "REMOVE",
      "PAR": {
          "GLOBAL_NAME": <global_name>,
      }
  }

READ
----

Request to return the complete list (dictionary) of device actors.

Sent from:
    RestApi, MqttScheduler

Expected RETURN:
    dictionary in the form {global_name: actor_address}

Example::

  cmd_dict = {
      "CMD": "READ",
  }

  return_dict = {
      "RETURN": "READ",
      "ERROR_CODE": 0,
      "RESULT": {
          <global_name>: <actor_address>
      },
  }
