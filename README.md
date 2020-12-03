RegistrationServer2 

It's task is to connect the SARAD® App with the InstrumentServer2 ( and over it indirectly to the device).
It unifies how devices are accesses, and makes it independent of the protocol used by the InstrumentServer2

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
	
TODO:
- [ ] fix logging
- [ ] create actors when device connection is detected
- [ ] reservation / freeing of devices
- [ ] automatic unit test cases
	
	