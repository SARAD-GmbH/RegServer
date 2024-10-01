========================
Setup of Windows service
========================

Folders
=======

Program files
-------------

::

   %ProgramFiles%\SARAD\RegServer-Service

Configuration file
------------------

::

   %ProgramData%\SARAD\RegServer-Service\config.toml

During the installation the setup program will copy ``config.example.toml`` into
this folder. It has to be renamed into or copied to ``config.toml`` in order to
become active.

Keys for MQTT broker
--------------------

::

   %systemroot%\ServiceProfiles\LocalService\AppData\Local\SARAD

Log files
---------

This is configurable in ``config.toml`` in key ``log_folder``. The default is::

   %systemroot%\ServiceProfiles\LocalService\AppData\Local\SARAD\log



Step by step instruction to create the setup EXE file
=====================================================

Requirements:

- Python 3
- PDM (https://pdm-project.org)

Steps:

1. Clone the project into a project file on a Windows PC.
2. ``pdm install --dev``
3. Test with ``pdm run python .\src\sarad_registration_server.py``.
4. ``pdm run pyinstaller.exe .\src\regserver-service.spec --noconfirm``
5. Compile the InnoSetup project in ``.\InnoSetup\setup-regserver_service.iss``.

Toolchain
=========

The required Python-Version and all dependencies are defined in
``pyproject.toml``. *PDM* is used to collect all dependencies in
``__pypackages__`` and to provide the appropriate environment with ``pdm run``.
*PyInstaller* collects all dependencies and builds
``.\dist\regserver-service\regserver-service.exe``.

*InnoSetup* is used to create the setup EXE for the service. It will call
``pre-compile.bat` before compilation. This batch file will call the
*PowerShell* script ``.\copy-distribution.ps1`` in order to copy all required
files to ``Y:\Software\Sarad_dev\regserver-service`` and to sign
``regserver-service.exe`` with SARAD's certificate.

``post-compile.bat`` that is called by *InnoSetup*, finally will copy the setup
EXE to ``Z:\GERÄTESOFTWARE\RegServer_Service``.

During the installation ``setup-rss.bat`` will:

- install the Windows service,
- configure the Windows service,
- start the Windows service,
- set all required firewall rules by calling the *PowerShell* script ``add-firewall-rule.ps1``.

====================================
Setup of Systemd service under Linux
====================================

Folders
=======

Virtual environment for RegServer and executable binary
-------------------------------------------------------

::

  PIPX_HOME=/opt/pipx
  PIPX_BIN_DIR=/usr/local/bin

Configuration file
------------------

::

  /etc/regserver/config.toml

Keys for MQTT broker
--------------------

::

  /etc/regserver/tls_*

Log files
---------

::

   /var/log

Step by step installation
=========================

Requirements
------------

Python 3 and `Pipx <https://github.com/pypa/pipx>`_ must be installed on the
target system.

Installation of RegServer
-------------------------

::

  sudo -H PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install git+http://r2d2.hq.sarad.de:3000/SARAD/RegServer.git

Possible sources for the installation in the command line above are:

http://r2d2.hq.sarad.de:3000/SARAD/RegServer.git

and

https://github.com/SARAD-GmbH/RegServer.git

Setup Systemd service
---------------------

Copy the required files from the Git repository on a remote PC::

  scp ./systemd/regserver.service pi@araneaxxxx:/home/pi/
  scp ./src/config.example.toml pi@araneaxxxx:/home/pi/

In this example, the target is a Linux computer with hostname "araneaxxxx" and user "pi".

On the target system::

  sudo mv regserver.service /etc/systemd/system/
  sudo mkdir /etc/regserver
  sudo cp config.example.toml /etc/regserver/config.toml
  sudo systemctl enable regserver.service
  sudo systemctl start regserver.service

Check the proper function with::

  systemctl status regserver.service

Update of the RegServer
=======================

::

  sudo -H PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx reinstall regserver

Accessory to control the LED on SARAD Aranea
============================================

Copy the required files from the Git repository on a remote PC::

  scp ./systemd/blinking_led.py pi@araneaxxxx:/home/pi/
  scp ./systemd/blinking_led.service pi@araneaxxxx:/home/pi/


On the target system::

  sudo mv blinking_led.service /etc/systemd/system/
  sudo systemctl enable blinking_led.service
  sudo systemctl start blinking_led.service
