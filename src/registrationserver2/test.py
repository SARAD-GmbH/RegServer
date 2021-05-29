from thespian.actors import ActorSystem

from registrationserver2 import config, logdef
from registrationserver2.modules.rfc2217.rfc2217_actor import Rfc2217Actor

if __name__ == "__main__":

    mysystem = ActorSystem(
        systemBase=config["systemBase"],
        capabilities=config["capabilities"],
        logDefs=logdef.logcfg,
    )

    some1 = mysystem.createActor(Rfc2217Actor, globalName="someother")
    some2 = ActorSystem().createActor(Rfc2217Actor, globalName="someother2")
