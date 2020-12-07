'''
Created on 14.10.2020

@author: rfoerster
'''
import traceback
import time

import serial.rfc2217
import thespian

from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2 import theLogger


class Rfc2217Actor(DeviceBaseActor):
	'''
		Actor for dealing with RFC2217 Connections, creates and maintains a RFC2217Protocol handler and relays messages towards it
	https://pythonhosted.org/pyserial/pyserial_api.html#module-serial.aio
	'''
	__open = False
	__port_ident : str
	__port : serial.rfc2217.Serial  = None

	def __connect(self):
		''' internal Function to connect to instrument server 2 over rfc2217'''
		if  self.__file and not self.__port_ident:
			address = self.__file.get('Remote', {}).get('Address', None)
			port = self.__file.get('Remote',{}).get('Port', None)
			if not address or not port:
				return self.ILLEGAL_STATE
			self.__port_ident =  fr'rfc2217://{address}:{port}'

		if self.__port_ident  and not (self.__port and self.__port.is_open):
			try:
				self.__port = serial.rfc2217.Serial(self.__port_ident) # move the send ( test if connection is up and if not create)
			except BaseException as error: #pylint: disable=W0703
				theLogger.info(self._config)
				theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		if self.__port and self.__port.is_open:
			return self.OK
		return self.ILLEGAL_STATE

	def __send__(self, msg : dict):
		if self.__connect() is self.OK:
			theLogger.info(f"{msg.get('DATA')}")
			self.__port.write(msg.get('DATA', b'\x42\x80\x7f\x0c\x00\x0c\x45'))
			self.__port.timeout = 10
			_return = b''
			while True:
				time.sleep(.5)
				_return_part = self.__port.read_all() if self.__port.inWaiting() else ''
				if _return_part == '':
					break
				_return = _return + _return_part
			return _return
		return self.ILLEGAL_STATE

	def __reserve__(self, msg):
		theLogger.info(msg)
		return self.ILLEGAL_NOTIMPLEMENTED

	def __free__(self, msg):
		theLogger.info(msg)
		if self.__port and self.__port.isOpen():
			self.__port.close()

def __test__():
	sys = thespian.actors.ActorSystem()
	act = sys.createActor(Rfc2217Actor, globalName='rfc2217://serviri.hq.sarad.de:5581')
	sys.ask(act, {'CMD':'SETUP', 'PORT': 'rfc2217://serviri.hq.sarad.de:5581'})
	print(sys.ask(act, {"CMD":"SEND", "DATA":b'\x42\x80\x7f\x01\x01\x00\x45'}))
	print(sys.ask(act, {"CMD":"FREE", "DATA":b'\x42\x80\x7f\x0c\x00\x0c\x45'}))
	input('Press Enter to End\n')
	theLogger.info('!')

if __name__ == '__main__':
	__test__()
