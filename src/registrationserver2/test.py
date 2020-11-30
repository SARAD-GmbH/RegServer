# pylint: skip-file
try:
	raise BaseException('x')
except NameError as error:
	print('!NE')
except BaseException as error:
	print(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-" }')
except:
	print ('?!?')
finally:
	pass
test = {"CMD":"Test"}
print(test)
print(isinstance(test,dict))
print(test.get("CMD", None))
