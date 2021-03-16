MQTT_ACTOR_ADRs: dict  # A dictionary for storing the addresses of MQTT Actors
"""
Stuture of MQTT_ACTOR_ADRs:
MQTT_ACTOR_ADRs = {
    Actor1_Name : Actor1_ADR,
    Actor2_Name : Actor2_ADR,
    ...
}
"""

# MQTT_CLIENT_RESULTs : dict # A dictionary for storing the work results of the MQTT Client Actor
"""
Structure of MQTT_CLIENT_RESULTs: 
MQTT_CLIENT_RESULTs = {
     Actor1_ADR : {
        'Status' : 'Active', # 'Active' means on-working; 'Deactive' means off work; Default: 'Deactive'
        'Publish' : 'Wait',  # 'Wait' = waiting for the confirmation; 'Default' : 'Idle'
        'Subscribe' : 'Idle', # 'Idle' = No non-confirmed subscription; 'Default' : 'Idle'
        'Unsubscribe' : 'Fail' # 'Fail' or 'Success' means as their words; 'Default' : 'Idle'
        # 'Publish', 'Subscribe' and 'Unsubscribe' are legal receptable work types of the MQTT Client and have same possible values as above.
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
