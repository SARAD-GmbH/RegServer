================
Folder structure
================

Project files
-------------

We are using `PDM <https://pdm-project.org>`_ as package und dependency manager.

* pyproject.toml: Contains project information as well as required dependencies
* pdm.lock: All dependencies with fixed versions
* README.md: General help file
* LICENSE: current LICENSE draft

systemd: Installation as Systemd service under Linux
----------------------------------------------------

Files and scripts for the installation as Systemd service under Linux.


src: Python source files
------------------------

* modules: Contains code that is specific to a special implementation of the RegServer

  * modules/frontend: modules pointing into the direction of the app
  * modules/backend: modules pointing into the direction of the instrument

* main.py: code entry point
* config.py: configuration file
* redirect_actor.py: will be created, when a reservation was successful, will manage
  incomming messages from the app, and relay them to the device specific actors
* restapi: rest api endpoint
