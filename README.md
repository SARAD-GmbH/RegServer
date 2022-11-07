# Registration Server 2

## Introduction ##

It's task is to connect the SARAD® App with the Instrument Server 2 ( and over
it indirectly to the device). It unifies how devices are accessed, and makes it
independent of the protocol used by the Instrument Server 2.

```language-plantuml
	@startuml
	actor "Trucy" as user
	control "Sarad App" as app
	box "Registration Server 2" #pink
		entity "rest api" as api
		entity "device Actor" as deviceactor
	end box
	entity "device with Instrument Server" as device
	user->app:Changes Config /\n Requests Data
	group reservation
		app->api:Attempts to Reserve Device
		api->deviceactor:relays request
		deviceactor->device:relays request
		device->deviceactor:accepts request /\n relays port information
		deviceactor->device:connects
		deviceactor->deviceactor:opens port
		deviceactor->api:accepts request /\n relays port information
		api->app:relays port
	end
	note over deviceactor: start timeout
	group Data - repeats on unexpected disconnect
		app->deviceactor:connects
		note over deviceactor: refresh timeout
		group Commands without response
			app->deviceactor:sends data
			note over deviceactor: refresh timeout
			deviceactor->device:relays data
			app->user:"OK"
		end
		group Commands with response
			app->deviceactor:sends data
			note over deviceactor: refresh timeout
			deviceactor->device:relays data
			device->deviceactor:relays answer
			deviceactor->app:relays answer
		end
		app->user:displays answer
		app->deviceactor:disconnects
	end
	group free
		app->api:frees device
		api->deviceactor:relays free
		deviceactor->device:relays free
	end
	group timeout reached
		deviceactor->device:sends free
	end
	@enduml
```

## Installation and usage ##

For test and development, the program is prepared to run in a virtual environment.

### Installation ###

    git clone <bare_repository>

to clone the working directory from the git repository.

    cd src-registrationserver2
    pipenv shell

to create the virtual environment.

    pipenv install --ignore-pipfile

to install all required dependencies.

If you want to do further development and use modules that are only required
during the development (for instance test), use

    pipenv install --dev --ignore-pipfile

### Usage ###

Make sure that port 8008 is not used by any other application.

    cd src
    python sarad_registration_server.py

to start the program.

With Instrument Server 2 running anywhere in the same LAN, you should see log
entries on the command line indicating newly attached or disconnected SARAD
instrument.

With your webbrower pointing to http://localhost:8008/list/, you should see a
JSON list of attached SARAD instruments with identification information like
Family, Type, Serial number.

### Documentation ###
Refer to http://http://intranet.hq.sarad.de/spc-sarad_network.pdf (SARAD
internal) for the specification.

The SPHINX documentation of the implementation details is in the subdirectory
`doc`. Run `make` this directory to compile a document.
http://intranet.hq.sarad.de/regserver/html/index.html (SARAD internal) contains
a compiled HTML version of the documentation.

## TODO:
- [ ] automatic unit test cases
