'''
Created on 01.12.2020

@author: rfoerster
'''

from thespian.actors import Actor

class RedirectorActor(Actor):
	
	def receive(self):
		pass
	
	def receiveMessage(self, msg, sender):
		self.receive()
		self.send(self.myAddress, msg)
		return 