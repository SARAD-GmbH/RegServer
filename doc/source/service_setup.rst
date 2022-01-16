========================
Setup of Windows service
========================

Packaging into a directory with EXE file
========================================

Initially::

	pyinstaller -D --collect-all sarad --hidden-import=thespian.system.multiprocTCPBase .\sarad_registration_server.py
	pyinstaller -D --collect-all sarad --hidden-import=thespian.system.multiprocTCPBase --hidden-import=win32timezone .\regserver-service.py

For every following run::

	pyinstaller .\sarad_registration_server.spec
	pyinstaller .\regserver-service.spec

Steps for installation
======================

The following steps are to be made in `setup-rss.bat`::

	.\regserver-service.exe install
	sc.exe config SaradRegistrationServer start= delayed-auto type=own obj= "NT AUTHORITY\LocalService" password= "0123_Kennwort"
	sc.exe failure SaradRegistrationServer reset= 60 actions= restart/5000
  sc.exe failureflag SaradRegistrationServer 1
	.\regserver-service.exe start

The ``startstop.file`` has to be placed into a folder where the *Local Service* user has read/write access.
