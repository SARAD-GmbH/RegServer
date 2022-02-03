==============
Error Handling
==============

Actor System
============

General Considerations
~~~~~~~~~~~~~~~~~~~~~~

The ActorSystem is special and somewhat problematic when it comes to error
handling. Every Actor is running in its own process and although an
``ActorSystem().shutdown()`` should exit all running Actors and shut down the
Actor System, often enough it keeps several processes running. This is even more
the case, if the program crashes unexpectedly and does not even reach the
``ActorSystem().shutdown()`` command.

That's why we have to be very careful to handle all possible errors to finish
the program gracefully.

The general approach to handle unexpected errors is to shut down and exit the
program with an error state. Since both, Registration Server as well as
Instrument Server, are running as services that are configured to restart, if
they exit with an error state, thus every unexpected error will lead to a
restart of the service program. Please refer to `Emergency System Shutdown`_.

PoisonMessage Handling
~~~~~~~~~~~~~~~~~~~~~~

The ``PoisonMessage`` object is delivered to an Actor or to external code when a
message sent to an Actor has caused the target Actor to fail. This is always an
unexpected error that must be handled with an `Emergency System Shutdown`_.
Within the Actor System the handler for ``PoisonMessage`` objects is implemented
in the ``BaseActor``. In the external program every ``ActorSystem().ask()`` must be
accompanied by a routine checking that the reply is of the expected object type.

DeadEnvelope Handling
~~~~~~~~~~~~~~~~~~~~~

If the ActorSystem is unable to deliver a message to the target Actor (usually
because the target Actor is dead or has otherwise exited), the ActorSystem will
route that message wrapped into a *DeadEnvelope* object to Dead Letter handling.

The Registrar Actor is registered for handling Dead Letter for the whole
ActorSystem. Every Dead Letter will lead to a call of ``saytem_shutdown`` (see
`Emergency System Shutdown`_).

Emergency System Shutdown
=========================

The emergency shutdown is done by function ``system_shutdown()`` defined in
module ``registrationserver.shutdown``. It removes a file that is used as flag
to break the main loop in the main program (``main.py`` for the Registration Server,
``ismqtt_main.py`` for the Instrument Server MQTT.
