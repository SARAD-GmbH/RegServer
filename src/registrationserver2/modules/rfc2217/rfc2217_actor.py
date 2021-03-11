'''
Created on 14.10.2020

@author: rfoerster
'''
import traceback
import time
import logging

import serial.rfc2217
import thespian

from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2 import theLogger

from registrationserver2.modules.messages import RETURN_MESSAGES

logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')

class Rfc2217Actor(DeviceBaseActor):
    '''Actor for dealing with RFC2217 Connections, creates and maintains
    a RFC2217Protocol handler and relays messages towards it
    https://pythonhosted.org/pyserial/pyserial_api.html#module-serial.aio'''
    __open = False
    __port_ident: str
    __port: serial.rfc2217.Serial = None

    def __connect(self):
        '''internal Function to connect to instrument server 2 over rfc2217'''
        if self._file:
            address = self._file.get('Remote', {}).get('Address', None)
            port = self._file.get('Remote', {}).get('Port', None)
            if not address or not port:
                return RETURN_MESSAGES.get('ILLEGAL_STATE')
            self.__port_ident = fr'rfc2217://{address}:{port}'

        if self.__port_ident and not (self.__port and self.__port.is_open):
            try:
                self.__port = serial.rfc2217.Serial(
                    self.__port_ident
                )  # move the send ( test if connection is up and if not create)
            except BaseException as error:  # pylint: disable=W0703
                theLogger.error(
                    f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
                )
        if self.__port and self.__port.is_open:
            return RETURN_MESSAGES.get('OK')
        return RETURN_MESSAGES.get('ILLEGAL_STATE')

    def __send__(self, msg: dict):
        if self.__connect() is self.OK:
            theLogger.info(
                f"Actor {self.globalName} Received: {msg.get('DATA')}")
            data = msg.get('DATA', None)
            if data:
                self.__port.write(data)
                _return = b''
                while True:
                    time.sleep(.5)
                    _return_part = self.__port.read_all(
                    ) if self.__port.inWaiting() else ''
                    if _return_part == '':
                        break
                    _return = _return + _return_part
                return {"RETURN": "OK", 'DATA': _return}

            return RETURN_MESSAGES.get('ILLEGAL_WRONGFORMAT')
        return RETURN_MESSAGES.get('ILLEGAL_STATE')

    def __reserve__(self, msg):
        theLogger.info(msg)
        return RETURN_MESSAGES.get('ILLEGAL_NOTIMPLEMENTED')

    def __free__(self, msg):
        theLogger.info(msg)
        if self.__port and self.__port.isOpen():
            self.__port.close()

    def __kill__(self, msg: dict):
        super().__kill__(msg)
        try:
            self.__port.close()
            self.__port = None
        except BaseException as error: # pylint: disable=W0703
            theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')


def __test__():
    sys = thespian.actors.ActorSystem()
    act = sys.createActor(
        Rfc2217Actor,
        globalName='SARAD_0ghMF8Y._sarad-1688._rfc2217._tcp.local')
    sys.ask(act, {'CMD': 'SETUP'})
    print(
        sys.ask(act, {
            "CMD": "SEND",
            "DATA": b'\x42\x80\x7f\x01\x01\x00\x45'
        }))
    print(
        sys.ask(act, {
            "CMD": "FREE",
            "DATA": b'\x42\x80\x7f\x0c\x00\x0c\x45'
        }))
    input('Press Enter to End\n')
    theLogger.info('!')


if __name__ == '__main__':
    __test__()
