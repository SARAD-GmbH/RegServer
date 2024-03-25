========================
Setup of Windows service
========================

Step by step instruction to create the setup EXE file
=====================================================

1. Clone the project into a project file on a Windows PC.
2. ``pdm install --dev``
3. Test with ``pdm run python sarad_registration_server.py``.
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
