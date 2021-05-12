# pylint: skip-file

from thespian.actors import ActorSystem
from registrationserver2.modules.rfc2217.rfc2217_actor import Rfc2217Actor
from registrationserver2 import FOLDER_AVAILABLE, FOLDER_HISTORY, logger, config, logdef

if __name__ == '__main__':
    
    mysystem =      ActorSystem(
            systemBase=config["systemBase"],
            capabilities=config["capabilities"],
            logDefs=logdef.logcfg,
        )
    
    some1 = mysystem.createActor(Rfc2217Actor, globalName="someother")
    some2 = ActorSystem().createActor(Rfc2217Actor, globalName="someother2")
