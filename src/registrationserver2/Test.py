from rx3.subject import Subject

stream = Subject()
stream.on_next(41)

d = stream.subscribe(lambda x: print("Got: %s" % x))

stream.on_next(42)
stream.on_next(stream)

d.dispose()
stream.on_next(43)