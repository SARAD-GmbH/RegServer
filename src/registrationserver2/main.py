'''
Created on 30.09.2020

@author: rfoerster
'''

from registrationserver2.mdnsListener import SaradMdnsListener
from registrationserver2.restapi import RestApi

import threading 
import signal
import os
import logging
from registrationserver2.config import config

if __name__ == '__main__':
	if isinstance(config['TYPE'], list):
		Test = []
		for __type in config['TYPE']:
			Test.append(SaradMdnsListener(_type = __type))
	else:
		Test = SaradMdnsListener(_type = config['TYPE'])
	Test2 = RestApi()
	#Test2.run(host='localhost',port="8000")
	apithread = threading.Thread(target=Test2.run,args=('0.0.0.0', 8000,))
	apithread.start()
	try: 
		input('Press Enter to End\n')
	finally:
		del(Test)
		os.kill(os.getpid(), signal.SIGTERM)
		