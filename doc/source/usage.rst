=====
Usage
=====

The SARAD Registration Server can either be used from the command line (under
Linux or under Windows) or as Windows service.

Command Line
============

Starting
--------

To start the programm use the "start" command with the program name::

  > sarad_registration_server.py start

or just::

  > sarad_registration_server.py

Under Windows you will have to call::

  > py.exe sarad_registration_server.py

Stopping
--------

To stop the program under Linux you can use Ctrl+C. In order to stop the program
under Windows you will have to open a second command line and enter::

  > py.exe sarad_registration_server.py stop

Windows Service
===============

We will usually pack the service ``regserver-service.py`` with PyInstaller into
a Windows EXE file.
This file can be installed and started as service in the usual way from the command line::

  > regserver-service.exe install
  > regserver-service.exe start
  > regserver-service.exe stop
  > regserver-service.exe remove

After the installation the service can be started and stopped from the Windows
Service app as well.
