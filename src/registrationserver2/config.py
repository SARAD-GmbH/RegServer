'''
Created on 30.09.2020

@author: rfoerster
'''

import registrationserver2

if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	exit
	
from logging import DEBUG

config = {
		'MDNS_TIMEOUT':		3000,
		'TYPE':				'_rfc2217._tcp.local.',
		#'FOLDER':			r'D:\test\rfc2217',
		'LEVEL':			DEBUG,
	}
		