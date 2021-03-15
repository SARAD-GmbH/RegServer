==============
Actor Messages
==============

General
-------

The general format for messages between defined actor is a python dict with the
following properties:

CMD
    contains the message type

RETURN
    for response message, contains True if no error happened, False in any other case

ERROR
    Contains an error message (for display or translation input)

ERRORCODE
    To unique identify the error, for machine processing.

DeviceBaseActor
---------------

* SEND

  * Request to a Device Actor (implimenting DeviceBaseActor)

    * DATA: Contains the DATA so be send
    * HOST: Host requesting the DATA to be send ( for reservation checks )

  * Response:

    * DATA: Contains DATA that the device send back, not set in case there is no
      reponse

* SEND_RESERVE

  * Request to reserve an instrument

    * HOST : Host requesting the reservation
    * USER : Username requesting the reservation
    * APP : Application requesting the reservation

* SEND_FREE

  * Request to free an instrument

    * HOST : Host requesting the reservation
    * USER : Username requesting the reservation
    * APP : Application requesting the reservation

DeviceActorManager
------------------

* CREATE

  * Request to create an actor for a specific device and class, send when a new
    device is detected

    * NAME: Device ID
    * CLASS: Class for the Instrument Actor (i.e. Rfc2217Actor), must implement
      DeviceBaseActor

* KILL

  * Request the termination of an actor, send when a device gets disconnected
    from the accessable network

    * NAME: Device ID

Misc (all)
----------

* ECHO

  * Responds with the message send, used for debugging of actors
