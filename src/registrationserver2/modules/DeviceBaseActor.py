'''
Created on 13.10.2020

@author: rfoerster
'''
from thespian.actors import Actor

class DeviceBaseActor(Actor):
	'''
	classdocs
	/**
	@startuml
	actor "Alice" as user
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
	collections cake
	user->cake:has some 
	@enduml
	*/
	'''
	ILLEGAL_WRONGFORMAT = {"ERROR":"Misformatted or no message sent"}
	ILLEGAL_NOTIMPLEMENTED = {"ERROR":"Not implemented"}
	
	

	ACCEPTED_MESSAGES = {
			"RESERVE" : "__reserve__",	# is being called when the end-user-application wants to reserve the directly or indirectly connected device for exclusive communication, should return if a reservation is currently possible 
			"FREE" : "__free__", # is being called when the end-user-application is done requesting / sending data, should return true as soon the freeing process has been initialized
			"SEND" : "__send__", # is being called when the end-user-application wants to send data, should return the direct or indirect response from the device, None in case the device is not reachable (so the end application can set the timeout itself)  
			"ECHO" : "__echo__" # should returns what is send, main use is for testing purpose at this point
			
		}
	'''
	Defines magic methods that are called when the specific message is received by the actor
	'''


	def receiveMessage(self, msg, sender):
		
		cmd = self.ACCEPTED_MESSAGES.get(msg.get("CMD", None),None)
		
		if not cmd:
			self.send(sender, self.ILLEGAL_WRONGFORMAT)

		if not getattr(self,cmd,None):
			self.send(sender, self.ILLEGAL_NOTIMPLEMENTED)
			
		else:
			self.send(sender,getattr(self,cmd)(msg))
			
	def __echo__(self, msg):
		return msg