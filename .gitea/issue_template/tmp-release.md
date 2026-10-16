---

name: "Release"
about: "Vorlage für die Arbeitsschritte beim Release"
title: "Release von Version "
ref: "master"
assignees: ["mstrey"]

---

## Bauen, Testen, intern Veröffentlichen
Im Arbeitsverzeichnis:
- [ ] `./doc/changelog.md` bearbeiten
- [ ] Versionsnummer heraufsetzen
  - `pyproject.toml`
  - `InnoSetup/setup-regserver_service.iss`
  - `InnoSetup/msi_config.xml`
  - `src/regserver/version.py`
- [ ] Pull, Commit, Push

Auf _WS01_ in Powershell im Arbeitsverzeichnis:
- [ ] Pull
- [ ] `pdm run pyinstaller.exe .\src\regserver-service.spec --noconfirm`

Auf _WS01_ in InnoSetup:
- [ ] bauen
- [ ] Installation testen aus `Z:\GERÄTESOFTWARE\RegServer_Service\`

In Gitea:
- [ ] Release anlegen
- [ ] Text aus `./doc/changelog.md` kopieren
- [ ] Exe- und MSI-Datei als Anhang

## Extern Veröffentlichen
Auf _WS01_ in Powershell im Arbeitsverzeichnis:
- [ ] `scp .\dist\setup-regserver_service-* sarad.de:/home/strey/`

Auf sarad.de:
- [ ] `sudo mv setup-* /var/www/saradhp/web/cms/media/docs/software/`

Im CMS:
- [ ] Versionsnummer in Beschreibung anpassen
