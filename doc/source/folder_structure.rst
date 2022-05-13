================
Folder Structure
================

Project Files
-------------

* Pipfile: Contains Projectinformation as well as required dependencies
* Pipfile.lock: All Dependencies, and dependencies of dependencies with a fixed version
* README.md: General help file
* pylintrc: Lint formatting information (Automatically used by pydev)
* LICENSE: current LICENSE draft

src: Python Source Files
------------------------

* modules: Contains code that is specific to a special implementation of the RegServer

  * modules/frontend: modules pointing into the direction of the app
  * modules/backend: modules pointing into the direction of the instrument

* main.py: code entry point
* config.py: configuration file
* redirect_actor.py: will be created, when a reservation was successful, will manage
  incomming messages from the app, and relay them to the device specific actors
* restapi: rest api endpoint
