Folder Sctructure:
* / : Project Files 
** Pipfile : Contains Projectinformation as well as required dependencies
** Pipfile.lock: All Dependencies, and dependencies of dependencies with a fixed version
** README.md: General help file
** pylintrc: Lint formatting information (Automatically used by pydev)
** LICENSE: current LICENSE draft

* src : Python Source Files
** modules : Contains all instrument server specific code ( required to connect to specific instrumentserver)
*** modules/device_actor_manager.py: ActorManagers, manages the creation and destruction of instrument specific actors
*** modules/device_base_actor.py: Base Class for Instrument specific Actors
** modules/rfc2217 : module for connecting to the rfc2217gateway
** main.py: code entry point
** config.py: configuraition file
** redirector_actor.py: is created when a reservation is successfull, will manage incomming messages from the app, and relays them to the device specific actors (i.e. RadonVision)
** restapi: rest api endpoint