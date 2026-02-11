# RegServer 2.5.11
Date: Wed, 11 Feb 2026 10:16:12 +0100

## Fixed bugs

- Hostnames in LAN backend (regression introduced in 2.5.0)
- Critical error in the LAN backend, which occasionally causes a restart when
  a remote device is disconnected.
- UTC offsets between -12 and +13 are valid. If utc_offset > 13 in the
  config.toml, the local computer time will be used to set the RTC.
- Handle LED status during shutdown.


# RegServer 2.5.9
Date: Tue, 10 Feb 2026 15:56:24 +0100

## Fixed bugs

- LED does not start to blink if all instruments are removed and only the LAN
  frontend is active.


# RegServer 2.5.8
Date: Tue, 10 Feb 2026 16:26:26 +0100

## Fixed bugs

- Disappearing instrument when working with LAN backend.
- Aranea and Radon Scout Everywhere don't shutdown properly without Internet
  connection.

## Features

- Make LED blinking more discriminable, distinguish disconnected instr. from
  MQTT offline.

| Wait for modem | Wait for NTP | Offline | No instrument |
| --- | --- | --- | --- |
| blink(0.6, 1) | blink(1, 0.6) | blink(0.5, 0.15) | blink(0.25, 0.07) |


# RegServer 2.5.7
Date: Tue, 10 Feb 2026 15:56:53 +0100

## Fixed bugs

- Fix monitoring mode that was defective in 2.5.6 due to a regression.


# RegServer 2.5.6
Date: Tue, 10 Feb 2026 15:55:02 +0100

## Known bugs introduced in this version

- Monitoring mode does not work at all.

## Fixed bugs

- Serial interface was blocked by Regserver.
- Ignore WLAN instruments that are not fully functional.


# RegServer 2.5.3
Date: Thu, 21 Aug 2025 15:15:35 +0200

## Fixed bugs

- Various errors related to the monitoring mode, which is being used by Wismut
  GmbH for the first time.
- Allow fast requests of values from multiple requesters---required by ROOMS!

## Features

- Automatic uninstallation of the old version during software updates.

## Changes

- Automatic device time setting is now the default setting. The clock is set
  to the PC time.


# RegServer 2.5.1
Date: Tue, 10 Jun 2025 14:05:07 +0200

## Fixed bugs

- Reservation of remote instruments was often only possible with the second
  attempt.
- Increased reliability, reduction in the number of restarts due to critical
  errors.
- Allow instruments with the serial number 0.
- Allow the PC on which the IS1 backend is running not to be a member of the
  domain.
- Handle defective WLAN devices delivering wrong family info gracefully.
- The LAN backend could be terminated unnoticed in the event of an internal
  error, so that a manual restart of the RegServer was necessary.

## Features

- Make opening the firewall optional. For security reasons, it may be
  undesirable for the REST API to be accessible to everyone in the local
  network.


# RegServer 2.5.0
Date: Mon, 28 Apr 2025 13:29:38 +0200

## Fixed bugs

- Encreased timeout for reservation to support slow Windows PCs.
- Correct handling of persistent MQTT connections.
- Improved behaviour on resume of Monitoring Mode.
- Correct an error where devices connected via MQTT were not reachable.
- The timeout message from RegServer to the SARAD app didn't work for the LAN
  backend.

## Features

- Make gateway functionality (forwarding from LAN to MQTT or from MQTT to LAN
  resp.) configurable.

## Changes

- Default for setup of device RTC is now "PC time" instead of UTC.
- Changed vairable names in configuration file (mdns -> lan, usb -> local).


# RegServer 2.4.7
Date: Fri, 21 Mar 2025 10:46:59 +0100

## Fixed bugs

- Increased roundtrip timeout for MQTT backend

## Features

- Use computer time to set RTC of instrument, if utc_offset > 13.


# RegServer 2.4.6
Date: Wed, 05 Feb 2025 09:24:18 +0100

## Fixed bugs

- improve reliability of shutdown
- support for very old and slow Windows PCs


# Improvements
- use only one MQTT client in backend
- accept binary commands only if the instrument was reserved before


# RegServer 2.4.5
Date: Mon, 27 Jan 2025 13:38:43 +0100

## Features

- Support for Radon Scout Everywhere
- Support for LED at Orange Pi Zero
- List of automatically detected serial ports can be overriden by whitelist in
  poll_serial_ports
- Extend the range of allowed Python versions

## Fixed bugs

- Make inner watchdog more reliable to avoid random restarts
- Handle unknown devices being announced via mDNS


# RegServer 2.4.4
Date: Mon, 11 Nov 2024 18:14:21 +0100

## Fixed bugs

- Improved behaviour in offline operation and when switching between online
  and offline operation


# RegServer 2.4.3
Date: Wed, 06 Nov 2024 10:02:08 +0100

## Features

- Introduction of whitelist and blacklist for hosts in mDNS backend
- Make number of used log files configurable

## Fixed bugs

- Cleaner shutdown and service restart under Linux
- RegServer doesn't block serial ports for other applications anymore
- Make service restart under Windows more reliable
- Use /var/cache/regserver/ as home directory for the Linux deamon to store
  stop and ping files
- IS1 backend for WLAN instruments presents the host name of the WLAN module
  now instead of its own host name

## Breaking Changes

- Use of 0xf0 instead of 0xc0 for RET_TIMEOUT. This requires Radon Vision >
  8.6.0.


# RegServer 2.4.1
Date: Mon, 08 Jul 2024 10:30:24 +0200

## Features

- Instrument-Ids sind nicht mehr mit HashIds kodiert sondern einfach als
  family_id-type_id-sn gebildet.
- Fallunterscheidung beim Setzen der RTC nach Instrument-Features. Ab
  Firmware-Version 20 werden die Sekunden ebenfalls gestellt und wir müssen beim
  Stellen der Uhr nicht mehr auf die volle Minute warten.

## Fixed bugs

- Einstellen der RS-485-Bus-Adresse am RTM 1688-2 gilt nur für Modbus, nicht
  aber für das SARAD-Protokoll


# RegServer 2.4.0
Date: Tue, 02 Jul 2024 14:49:07 +0200

## Features

- Einführung des Monitoring-Modes
- Geschwindigkeitserhöhung bei MQTT
- Set-RTC-Request
- Einführung einer Abbruch-Antwort für die App

## Fixed bugs

- Zugriff auf mehrere Geräte gleichzeitig unter Windows war kaputt in 2.3.11
  (Regression)
- Key Error "Host" behoben
- "state" in der Host-Liste wird nicht korrekt aktualisiert


# RegServer 2.3.0
Date: Mon, 25 Mar 2024 15:41:20 +0100

## Fixed bugs
- Erhöhung der Geschwindigkeit beim Datendownload bei hohen Baudraten
- Behebung eines Problems beim Datendownload von DOSEman bei vollem
  Ringspeicher

## Features
- Einführung der Value-Funktion in der REST-API für die Radon-Scout-Familie
- Die Value-Funktion in der REST-API funktioniert jetzt auch über die
  Netzwerke
- Support für ZigBee-Geräte

## Improvements
- Vereinfachung und Vereinheitlichung der Konfigurationsdatei. Es gibt nur
  noch eine Datei config.toml und nicht wie bisher eine für Linux und eine für
  Windows. Im einfachsten Fall braucht man gar keine Konfigurationsdatei und bei
  der Installation wird auch keine angelegt. Stattdessen gibt es eine
  ausführlich kommentierte config.example.toml.
- Bei der Neuinstallation bleibt die Konfigurationsdatei erhalten.
- Update der verwendeten Packages (insbesondere Paho MQTT)
- Vorgabewert für MQTT-QoS ist jetzt 1. Damit soll das zu übertragende
  Datenvolumen halbiert werden.
- Projektverzeichnis aufgeräumt, Einführung von PDM zur Paketverwaltung
- Dokumentation teilweise aktualisiert

## Known bugs

- Threading bei Multi-Frame-Messages von DOSEman führt zum Absturz


# RegServer 2.2.0
Date: Tue, 05 Dec 2023 15:14:33 +0100

## Fixed bugs
- Bugfixes in Zhg. mit IS1
- Bugfixes in Zhg. mit MQTT, QOS, Retained Messages, Persistent Sessions
- MQTT-Feedback-Schleife, wenn sowohl MQTT-Frontend als auch
  MQTT-Backend gleichzeitig aktiv sind
- Bugfixes betreffend IS1- und MQTT-Backend
- eindeutige is_id in MQTT-Topics
- Bugfix bei Anzeige von anderen Hosts aus reservierter Geräte
- extended timeout to work around a bug in RS eXpert firmware


## Improvements
- move list of allowed commands to instruments.yaml in data_collector
- increase tolerance for timestamps comming from instrument servers


# RegServer 2.1.0
Date: Thu, 31 Aug 2023 08:19:10 +0200

## Fixed bugs
- hosts list for IS1 Listener
- Scan und Restart auf je einen Remote-Host beschränken
- forwarding of Scan requests
- reliability of Free requests
- other minor bug fixes
- resurrection of MQTT Device Actors compensating instability of MQTT client
- fix a bug in the handling of FREE commands in the MQTT backend

# RegServer 2.0.4
Date: Fri, 30 Jun 2023 16:59:25 +0200

## Fixed bugs
- Fix incompatibility between ROOMS and MQTT
- Fix several MQTT issues that have been made obvious by ROOMS.
- div. kleinere Fehler
- verschwindende mDNS-Geräte behoben
- Versuch, die CPU-Last zu verringern, um den "Registrar Timeout"-Fehler zu
  beheben
- Diverse Maßnahmen, um die korrekte Weiterleitung von Reservierungsnachrichten
  zu gewährleisten, damit die Doppelabfrage von ROOMS korrekt bearbeitet wird.
- faster download of measuring data
- short times can be used for watchdog
- longer timeouts to support slow computers
- Regression von mDNS-Backend repariert
- Erkennen besetzter Instrumente mit MQTT
- Zulassen von Datenframes ohne CMD in Richtung App -> Instrument
- adapt Pipfile to sys_platform
- proper behaviour on MQTT disconnect
- tolerate multiple add_instr in MQTT listener
- KeyError: "IP"
- Unix Listener doesn't work on Raspberry Pi #309[1]
- correct Host state
- make hosts endpoint work with mDNS frontend and backend

## Improvements
- Einführung von Threading in Aktoren für länger dauernde Vorgänge. Damit können
  die Watchdog-Zeiten erheblich kürzer gewählt werden.
- Make current and last log file accessible in REST API
- Sensible defaults for Windows
- Log entry regarding Endianness of DACM-8 vs. DACM-32
- Scan-Funktion wird an Remote-Hosts weitergereicht
- Logging von MQTT-Fehlern, Entdecken von ausbleibenden PINGRESP

## Known bugs
Bei den umfangreichen Änderungen sind leider wieder zahlreiche neue Fehler
entstanden. Damit die Release einigermaßen stabil funktioniert, sind bei der
Konfiguration zu beachten:

- TCP-Actor-Implementierung wählen
- Watchdog-Zeiten von 1 oder 2 s führen nach wie vor zu Problemen.

- detection of local instruments doesn't work with UDP Actor implementation
- not responding MQTT instrument server can lead to endless loop causing high
  CPU load

## Features

- support for remote devices via virtual COM ports
- automatic setup of RTC at connected instrument
- new DACM commands for DACM32
- changed byteorder for DACM32 added
- REST API 2.0
- Reboot if disconnected from MQTT for long time
- Remote scan for instruments
- Remote restart

## Changes

- multiprocQueueBase as default Actor implementation

# RegServer 2.0.3
Date: Thu, 16 Feb 2023 19:25:30 +0100

## Features

- Firmware version of instrument shown in the REST API
- integrierte Dokumentation der REST API
- Support for DOSEman family
- add version.py to repository
- add version information to REST API
- display Actor system implementation in REST API /ping
- faster detection of local instruments
- better support for detection of DOSEman with automatic polling setup
- polling is configurable via REST API at runtime
- set default values in config
- blacklist toxic serial devices

## Fixed bugs

- Verbesserte Stabilität
- workaround for bugs in Thespian (ChildActorExited is unreliable)
- operation without network under Windows
- improve inner watchdog

## Improvements
- speedup service startup under Windows (experimental)
- improved error handling


# RegServer 2.0.2
Date: Tue, 13 Dec 2022 14:35:30 +0100

So geliefert auf Aranea0003 bis Aranea0006 mit Aer 5400-GS SN 330, 331, 333,
334.
Gegenüber 2.0.1 wurde hauptsächlich das Verhalten des Systemd-Service in Bezug
auf Shutdown und Restart verbessert, sodass die USV auf Basis des StromPi3
zuverlässig das Herunterfahren puffert.

# RegServer 2.0.1
Date: Wed, 07 Dec 2022 17:26:31 +0100

2.0.0 hatte einen fetten Bug: Wenn man ein DACM-Gerät angeschlossen hat, dann
startet der Service fortwährend neu und wird damit unbenutzbar.

Dieser Fehler wurde behoben.

# RegServer 2.0.0
Date: Tue, 06 Dec 2022 14:58:08 +0100

So ausgeliefert mit Radon Vision 8.2

