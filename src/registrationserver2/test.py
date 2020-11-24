try:
	raise "IOError('x')"
except NameError as error:
	print('!NE')
except Exception as error:
	print('!')
except:
	print ('?!?')
finally:
	pass
test = {"CMD":"Test"}
print (test)
print(isinstance(test,dict))
print(test.get("CMD", None))