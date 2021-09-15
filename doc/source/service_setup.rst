========================
Setup of Windows service
========================

Packaging into a directory with EXE file
========================================

Initially::

	pyinstaller -D --collect-all sarad --hidden-import=thespian.system.multiprocTCPBase .\sarad_registration_server.py
	pyinstaller -D --collect-all sarad --hidden-import=thespian.system.multiprocTCPBase --hidden-import=win32timezone .\srs-service.py

For every following run::

	pyinstaller .\sarad_registration_server.spec
	pyinstaller .\srs-service.spec

Steps for installation
======================

The following steps are to be made in InnoSetup::

	.\srs-service.exe install
	sc.exe config SaradRegistrationServer start= delayed-auto type=own obj= "NT AUTHORITY\LocalService" password= "0123_Kennwort"
	sc.exe failure SaradRegistrationServer reset= 60 actions= restart/5000
	.\srs-service.exe start

The ``startstop.file`` has to be placed into a folder where the *Local Service* user has read/write access.