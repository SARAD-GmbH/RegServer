Actor system, registrar and watchdog
====================================

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
       "is_device_actor": <bool>,
       "is_alive": <bool>,
      }
  }

Actors created in the actor system

- have to know the actor address of the *Registrar*
- have to subscribe at the *Registrar* on startup
- can read the *Actor Dictionary* from the *Registrar*
- have to unsubscribe at the *Registrar* on their ActorExitRequest() handler
- have to keep a list of the actor addresses of their child actors
- have to respond to the *Registrar* after receiving a *keep alive* message

This basic functionality of every actor is implemented in the *BaseActor* object
defined in module `base_actor.py`.

Watchdog
--------

In regular intervals the *Registrar* checks the integrity of the actor system.
Therefor it sends a *keep alive* message to all of its child actors.
If an actor has children it has to forward the *keep alive* message to all of them.
After receiving the *keep alive*, the actor has to respond to the *Registrar*.
When receiving the reply, the Registrar sets the *is_alive* flag for the respective actor.
At a given *timeout* time after starting the round call,
the *Registrar* checks the *is_alive* flags in its dictionary
and, if it is not complete, starts measures to recover the actor system.
Usually it will just call `system_shutdown()` in this case.
