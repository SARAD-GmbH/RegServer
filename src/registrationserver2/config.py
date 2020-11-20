'''
Created on 30.09.2020

@author: rfoerster
'''

import registrationserver2

'''
	Executes the main python file if this file is called directly
'''

if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	exit
	
from logging import DEBUG

'''
	Configuration Object
	TODO: Load from yaml file instead of a 'executable' file format 
'''

config = {
		'MDNS_TIMEOUT':		3000,
		'TYPE':				['_sarad-1688._rfc2217._tcp.local.','_rfc2217._tcp.local.'],
		#'FOLDER':			r'D:\test\rfc2217',
		'LEVEL':			DEBUG,
	}
		