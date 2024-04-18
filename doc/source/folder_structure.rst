================
Folder structure
================

Project files
-------------

We are using `PDM <https://pdm-project.org>`_ as package und dependency manager.

* pyproject.toml: contains project information as well as required dependencies
* pdm.lock: all dependencies with fixed versions
* README.md: general help file
* LICENSE: current LICENSE draft

src: Python source files
------------------------

* regserver:

  * main.py: code entry point
  * config.py: configuration defaults
  * redirect_actor.py: interface between the SARAD app and the RegServer; will
    be created, when a reservation was successful; will manage incomming
    messages from the app, and relay them to the device specific actors
  * restapi.py: REST API endpoint
  * modules: Contains code that is specific to a special implementation of the RegServer

    * modules/frontend: modules pointing into the direction of the app
    * modules/backend: modules pointing into the direction of the instrument

doc: Source files for this documentation
----------------------------------------

This is the documentation for developers made with `Sphinx
<https://www.sphinx-doc.org/en/master/>`_. Make HTML version with ``pdm run make
html``.

manual: The source code of the user manual
------------------------------------------

This is the manual for the end users.
The manual is prepared with `Emacs Org Mode <https://orgmode.org/>`_.

* man-regserver-de: German version
* man-regserver-en: English version

tests: Files for testing
------------------------

* raw-device-browser.py: application for the test of the Zeroconf library

systemd: Installation as Systemd service under Linux
----------------------------------------------------

Files and scripts for the installation as Systemd service under Linux.

InnoSetup: Installation as Windows service
------------------------------------------

This folder contains all files that are required to create the setup EXE file
for the installation of the *SARAD Registration Server* as Windows service.
We are using `InnoSetup <https://jrsoftware.org/isinfo.php>`_.
