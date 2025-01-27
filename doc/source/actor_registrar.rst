Actor system, registrar and watchdog
====================================

Startup
-------

The actor system shall be started with a single actor, the *Registrar Actor*.
The *Registrar* starts all essential actors, that may start there own child actors,
and keeps track of all actors that have been created.

It therefor keeps a dictionary with a list of actor addresses, actor ids, the
address of its parent actor, and the actor state.

Data structure (*Actor Dictionary*): ::

  {actor_id:
      {
       "address": <actor address>,
       "parent": <actor_address>,
       "actor_type": <ActorType>,
       "get_updates": <bool>,
       "is_alive": <bool>,
      }
  }

Watchdog
--------

In regular intervals the *Registrar* checks the integrity of the actor system.
Therefor it sends a ``KeepAliveMsg`` to all Actors in its ``actor_dict``.
After receiving the ``KeepAliveMsg``, the actor has to respond with a ``SubscribeMsg`` to the
*Registrar*. When receiving the reply, the Registrar sets the ``is_alive`` flag
for the respective actor.

At a given *timeout* time after starting the round call,
the *Registrar* checks the ``is_alive`` flags in its dictionary
and, if it is not complete, starts measures to recover the actor system.
Usually it will just call ``system_shutdown()`` in this case.

Shutdown
--------

The shutdown of the actor system is initiated with a ``KillMsg`` to the *Registrar*.
Then every actor receiving the ``KillMsg`` forwards it to all of its children.
After the exit of all child actors has be confirmed with the last ``ChildActorExited`` message
and the list of child actors is empty,
the parent actor sends itself the ``ActorExitRequest()``.

Base Actor
----------

Actors created in the actor system

- have to know the actor address of the *Registrar*
- have to subscribe at the *Registrar* on startup
- can subscribe to updates of the *Actor Dictionary* from the *Registrar*
- can receive updates of the *Actor Dictionary*
- have to unsubscribe at the *Registrar* on their ``ActorExitRequest()`` handler
- have to keep a list of the actor addresses of their child actors
- have to respond with a ``SubscribeMsg`` to the *Registrar* after receiving a ``KeepAliveMsg``
- when receiving a ``KillMsg``: forward the message to all child actors

This basic functionality of every actor is implemented in the *BaseActor* object
defined in module ``base_actor.py``.

Functions of the Registrar Actor
--------------------------------

- keep the *Actor Dictionary*
- on ``SubscribeMsg``: register new actors in the Actor Dictionary
- mark actors as device actors in the Actor Dictionary
- on ``UnsubscribeMsg``: remove actors from the Actor Dictionary
- mark actors that have subscribed to get updates of the Actor Dictionary
- on every change of the Actor Dictionary, send this dict to all marked subscribers
- send ``KeepAliveMsg`` to all registered Actors on a regular basis
- create the Cluster Actor

Additionally for Instrument Server MQTT:

- create the MQTT Scheduler Actor
