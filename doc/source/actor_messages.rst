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

CMD
    contains the message type.

PAR (optional)
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

ERROR_CODE
    integer to clearly identify the error.

RETURN
    contains a text reporting the outcome or error message corresponding with ERROR_CODE

RESULT (optional)
    contains additional result attributes that differ from command to command.

Examples::

  return_dict = {
      "ERROR_CODE": 0,
      "RETURN": "OK",
      "RESULT": {
          "IP": 127.0.0.1,
          "PORT": 50000,
      },
  }

  return_dict = {
      "ERROR_CODE": 10,
      "RETURN": "OK, skipped",
  }

CMDs handled by the DeviceBaseActor
===================================

RESERVE
-------

Request to reserve an instrument.

Parameters:

* HOST: Host requesting the reservation
* USER: Username requesting the reservation
* APP: Application requesting the reservation

RESULT attributes:

* IP: IP address of the listening server socket
* PORT: Port number of the listening server socket

FREE
----

Request to free an instrument from the reservation.


CMDs handled by the DeviceActor
===============================

SEND
----

Request from the Redirector Actor to a Device Actor to send a binary message to
the Instrument Server.

Parameters:

* DATA: Contains the DATA so be sent
* HOST: Host requesting the DATA to be sent (for reservation checks at the Instrument Server)

RESULT attributes:

* DATA: Contains DATA that the device sent back, not set in case there is no
  reponse

CMDs of the DeviceActorManager (???)
====================================

(I'm not sure whether this component is really needed. -- MS, 2021-03-26)

CREATE
------

Request to create an actor for a specific device and class, sent when a new
device is detected.

Parameters:

* NAME: Device ID
* CLASS: Class for the Device Actor (i.e. Rfc2217Actor), must implement
  DeviceBaseActor

KILL
----

Request the termination of an actor, sent when a device gets disconnected
from the accessable network.

Parameter:

* NAME: Device ID

Misc CMDs (all)
===============

ECHO
----

Responds with the message send, used for debugging of actors.
