#from typing import Dict

#MQTT_ACTOR_ADRs: Dict[str, str] = {}  # A dictionary for storing the addresses of MQTT Actors
"""
Struture of MQTT_ACTOR_ADRs:
MQTT_ACTOR_ADRs = {
    Actor1_Name : Actor1_ADR,
    Actor2_Name : Actor2_ADR,
    ...
}
"""

#MQTT_CLIENT_RESULTs: dict = {}  # A dictionary for storing the work results of the MQTT Client Actor
"""
Structure of MQTT_CLIENT_RESULTs:
MQTT_CLIENT_RESULTs = {
     Actor1_ADR : {
        'Status' : 'Active', # 'Active' means on-working; 'Deactive' means off work; Default: 'Deactive'
        'Publish' : 'Wait',  # 'Wait' = waiting for the confirmation; 'Default' : 'Idle'
        'Subscribe' : 'Idle', # 'Idle' = No non-confirmed subscription; 'Default' : 'Idle'
        'Unsubscribe' : 'Fail' # 'Fail' or 'Success' means as their words; 'Default' : 'Idle'
        # 'Publish', 'Subscribe' and 'Unsubscribe' are legal acceptable work types of the MQTT Client and have same possible values as above.
     },
     Actor2_ADR: {...},
     ...

}
"""

"""
    /**
    classdocs
    @startuml
    actor "Service Employee" as user
    entity "Device with Instrument Server MQTT" as is_mqtt
    entity "MQTT Broker" as mqtt_broker
    box "RegistrationServer MQTT"
    entity "SaradMqttClient" as client_actor
    entity "SaradMqttSubscriber" as rs_mqtt
    entity "MQTT Actor" as mqtt_actor
    database "Device List" as list
    end box

    client_actor -> mqtt_broker : connect
    rs_mqtt -> client_actor : ask client to subscribe to a topic "+/connected"
    client_actor -> mqtt_broker : subscribe to a topic "+/connected"
    rs_mqtt -> client_actor : ask client to subscribe to a topic "+/meta"
    client_actor -> mqtt_broker : subscribe to a topic "+/meta"
    rs_mqtt -> client_actor : ask client to subscribe to a topic "+/+/connected"
    client_actor -> mqtt_broker : subscribe to a topic "+/+/connected"
    user -> is_mqtt : connect to local network
    is_mqtt -> mqtt_broker : connect with LWT message "<is_id>/<instrument_id>/connected = 0"
    mqtt_broker -> client_actor : send the connection message of IS MQTT
    client_actor -> rs_mqtt : send the connection message of IS MQTT
    is_mqtt -> mqtt_broker : publish "<is_id>/meta" with retained = true
    client_actor -> rs_mqtt : send the meta message
    client_actor -> rs_mqtt : send the meta message
    is_mqtt -> mqtt_broker : subscribe to a topic "<is_id>/+/control"
    is_mqtt -> mqtt_broker : subscribe to a topic "<is_id>/+/cmd"
    is_mqtt -> mqtt_broker : publish "<is_id>/<instrument_id>/msg" with retained = true
    is_mqtt -> mqtt_broker : publish "<is_id>/<instrument_id/meta>" with retained = true
    is_mqtt -> mqtt_broker : publish "<is_id>/<instrument_id>/connected = 2" with retained = true
    mqtt_broker -> client_actor : send the connection message of the instrument
    client_actor -> rs_mqtt : relay the connection message of the instrument
    rs_mqtt -> list : creates / updates device description file
    rs_mqtt -> list : links device into the available list
    rs_mqtt -> mqtt_actor : create an actor for this instrument
    mqtt_actor -> client_actor : ask the client to subscribe to a topic "<is_id>/<instrument_id>/msg"
    client_actor -> mqtt_broker : subscribe to a topic "<is_id>/<instrument_id>/msg"
    mqtt_actor -> client_actor : ask the client to subscribe to a topic "<is_id>/<instrument_id>/meta"
    client_actor -> mqtt_broker : subscribe to a topic "<is_id>/<instrument_id>/meta"



    skinparam dpi 800
    scale 13500 width
    scale 2200 height
    @enduml

    */

    /*
    classdoc
     @startuml
    actor "Service Employee" as user
    entity "Device with Instrument Server MQTT" as is_mqtt
    entity "MQTT Broker" as mqtt_broker
    box "RegistrationServer MQTT"
    entity "SaradMqttClient" as client_actor
    entity "SaradMqttSubscriber" as rs_mqtt
    entity "MQTT Actor" as mqtt_actor
    database "Device List" as list
    end box


    group reservation
      mqtt_actor -> client_actor : ask the client to publish "<is_id>/<instrument_id>/control" + reservation request
      client_actor -> mqtt_broker : publish "<is_id>/<instrument_id>/control" + reservation request
      mqtt_broker -> is_mqtt : send the reserve request
      is_mqtt -> mqtt_broker : publish the reservation status with "<is_id>/<instrumemt_id>/meta"
      mqtt_broker -> client_actor : send the reservation reply
      client_actor -> mqtt_actor : relay the reservation reply
    end

    group send SARAD CMD
      mqtt_actor -> client_actor : ask the client to publish "<is_id>/<instrument_id>/cmd" + <SARAD CMD byte-string>
      client_actor -> mqtt_broker : publish "<is_id>/<instrument_id>/cmd" + <SARAD CMD byte-string>
      mqtt_broker -> is_mqtt : send the CMD
      is_mqtt -> mqtt_broker : publish the binary reply with "<is_id>/<instrument_id>msg"
      mqtt_broker -> client_actor : send the reply
      client_actor -> mqtt_actor : relay the reply
    end

    group free
      mqtt_actor -> client_actor : ask the client to publish "<is_id>/<instrument_id>/control" + free request
      client_actor -> mqtt_broker : publish "<is_id>/<instrument_id>/control" + free request
      mqtt_broker -> is_mqtt : send the free request
    end

    @enduml
    */
    """
'''
import os
import time
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem

import registrationserver2
from registrationserver2.modules.mqtt.test_actor import MqttTestActor
from registrationserver2 import logger
from registrationserver2.modules.mqtt.message import \
    RETURN_MESSAGES

def __test__():
    # ActorSystem(
    #    systemBase=config["systemBase"],
    #    capabilities=config["capabilities"],
    # )
    logger.info("Subscriber")
    test_actor = ActorSystem().createActor(
        MqttTestActor, globalName="test_actor_001"
    )
    ask_return = ActorSystem().ask(
        test_actor,
        {
            "CMD": "SETUP",
            "PAR": {
                "Subscriber_Name": "SARAD_Subscriber",
            },
        },
    )
    if ask_return["ERROR_CODE"] in (
        RETURN_MESSAGES["OK"]["ERROR_CODE"],
        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
    ):
        logger.info("Test actor is setup correctly!")
        folder_history = f"{registrationserver2.FOLDER_HISTORY}{os.path.sep}"
        folder_available = f"{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}"
        while True:
            if os.listdir(folder_history) == []:
                logger.info("No files found in the directory.")
                time.sleep(1)
            else:
                f = os.listdir(folder_history)
                logger.info("Some files found in the directory.")
                break
        avail_f = []
        while True:
            for filename in f:
                logger.info("File '%s' exists", filename)
                link = fr"{folder_available}{filename}"
                if os.path.exists(link):
                    logger.info("Link '%s' exists", link)
                    avail_f.append(filename)
            if avail_f != []:
                logger.info("There are some available instruments")
                logger.info(avail_f)
                break
            time.sleep(1)
        for filename in avail_f:
            logger.info("File '%s' exists", filename)
            link = fr"{folder_available}{filename}"
            ask_msg = {
                "CMD": "PREPARE",
                "PAR": {
                    "mqtt_actor_name": filename, 
                },
            }
            ask_return = ActorSystem().ask(test_actor, ask_msg)
            if ask_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.info("To test")
                ask_msg = {"CMD": "TEST"}
                ActorSystem().tell(test_actor, ask_msg)
                #ask_return = ActorSystem().ask(test_actor, ask_msg)
                #logger.info(ask_return)
            else:
                logger.error("Test actor failed to prepare")
            
    else:
        logger.warning("SARAD MQTT Subscriber is not setup!")
        logger.error(ask_return)
        #input("Press Enter to End")
        logger.info("!!")
    input("Press Enter to End")
    ActorSystem().tell(test_actor, ActorExitRequest())
    time.sleep(10)
    ActorSystem().shutdown()


if __name__ == "__main__":
    __test__()
'''
