import atexit
import json
import random
import time
import warnings
from configparser import SectionProxy

import paho.mqtt.client
import paho.mqtt.packettypes
import paho.mqtt.properties
from paho.mqtt.client import MQTT_ERR_NO_CONN
from paho.mqtt.client import Client as MQTTClient

from defs.common import strtobool

from ..protocol_settings import Registry_Type, WriteMode, registry_map_entry
from .transport_base import transport_base


class mqtt(transport_base):
    ''' for future; this will hold mqtt transport'''
    host : str
    port : int = 1883
    base_topic : str = "home/device"
    error_topic : str = "/error"
    discovery_topic : str = "homeassistant"
    availability_topic : str
    discovery_enabled : bool = False
    json : bool = False
    reconnect_delay : int = 7
    """ seconds """

    reconnect_attempts : int = 21
    #max_precision : int = - 1

    holding_register_prefix : str = ""
    input_register_prefix : str = ""

    client : MQTTClient = None
    mqtt_properties : paho.mqtt.properties.Properties = None

    __first_connection : bool = True
    __reconnecting : bool = False
    connected : bool = False

    def __init__(self, settings : SectionProxy):
        self.host = settings.get("host", fallback="")
        if not self.host:
            raise ValueError("Host is not set")

        self.port = settings.getint("port", fallback=self.port)
        self.base_topic = settings.get("base_topic", fallback=self.base_topic).rstrip("/")
        self.error_topic = settings.get("error_topic", fallback=self.error_topic).rstrip("/")
        self.discovery_topic = settings.get("discovery_topic", fallback=self.discovery_topic)
        self.discovery_enabled = strtobool(settings.get("discovery_enabled", self.discovery_enabled))
        self.json = strtobool(settings.get("json", self.json))
        self.reconnect_delay = settings.getint("reconnect_delay", fallback=7)
        #self.max_precision = settings.getint('max_precision', fallback=self.max_precision)

        if not isinstance( self.reconnect_delay , int) or self.reconnect_delay < 1: #minumum 1 second
            self.reconnect_delay = 1

        self.reconnect_attempts = settings.getint("reconnect_attempts", fallback=21)
        if not isinstance( self.reconnect_attempts , int) or self.reconnect_attempts < 0: #minimum 0
            self.reconnect_attempts = 0

        self.holding_register_prefix = settings.get("holding_register_prefix", fallback="")
        self.input_register_prefix = settings.get("input_register_prefix", fallback="")

        username = settings.get("user", fallback="")
        password = settings.get("pass", fallback="")

        if not username:
            raise ValueError("User is not set")

        if not password:
            warnings.warn("MQTT Password is empty", RuntimeWarning)

        #init client
        #compatability with newer lib
        if hasattr(paho.mqtt.client, "CallbackAPIVersion"):
            self.client = MQTTClient(paho.mqtt.client.CallbackAPIVersion.VERSION1)
        else:
            self.client = MQTTClient()

        self.client.username_pw_set(username=username, password=password)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.client_on_message
        self.client.on_disconnect = self.on_disconnect

        self.mqtt_properties = paho.mqtt.properties.Properties(paho.mqtt.packettypes.PacketTypes.PUBLISH)
        self.mqtt_properties.MessageExpiryInterval = 30  # in seconds

        self.write_enabled = True #set default
        super().__init__(settings)


    def connect(self):
        self._log.info("mqtt connect")
        if self.__first_connection:
            self.__first_connection = False
            self.client.connect(str(self.host), int(self.port), 60)
            self.client.loop_start()
            atexit.register(self.exit_handler)
        else:
            self.mqtt_reconnect() #special reconnect function

    def exit_handler(self):
        '''on exit handler'''
        self._log.warning("MQTT Exiting...")
        self.client.publish(self.availability_topic,"offline",retain=True)
        return

    def mqtt_reconnect(self):
        self._log.info("Disconnected from MQTT Broker!")
        if self.__reconnecting != 0: #stop double calls
            return
        # Attempt to reconnect
        for attempt in range(0, self.reconnect_attempts):
            self.__reconnecting = time.time()
            try:
                self._log.warning("Attempting to reconnect("+str(attempt)+")...")
                if random.randint(0,1): # noqa: S311 alternate between methods because built in reconnect might be unreliable.
                    self.client.reconnect()
                else:
                    self.client.loop_stop()
                    self.client.connect(str(self.host), int(self.port), 60)
                    self.client.loop_start()

                #sleep to give a chance to reconnect.
                time.sleep(self.reconnect_delay)
                if self.connected:
                    self.__reconnecting = 0
                    return
            except Exception:
                self._log.warning("Reconnection failed. Retrying in "+str(self.reconnect_delay)+" second(s)...")
                time.sleep(self.reconnect_delay)

        #failed to reonnect
        self._log.critical("Failed to Reconnect, Too many attempts")
        self.__reconnecting = 0
        quit() #exit, service should restart entire script

    def on_disconnect(self, client, userdata, rc):
       self.connected = False

    def on_connect(self, client, userdata, flags, rc):
        """ The callback for when the client receives a CONNACK response from the server. """
        self._log.info("Connected with result code %s\n",str(rc))
        self.connected = True

    __write_topics : dict[str, registry_map_entry] = {}

    def write_data(self, data : dict[str, str], from_transport : transport_base):
        if not self.write_enabled:
            return

        if self.connected:
            self.connected = self.client.is_connected()

        self._log.info(f"write data from [{from_transport.transport_name}] to mqtt transport")
        self._log.info(data)
        #have to send this every loop, because mqtt doesnt disconnect when HA restarts. HA bug.
        info = self.client.publish(self.availability_topic,"online", qos=0,retain=True)
        if info.rc == MQTT_ERR_NO_CONN:
            self.connected = False

        if(self.json):
            # Serializing json
            json_object = json.dumps(data, indent=4)
            self.client.publish(self.base_topic+"/"+from_transport.device_identifier, json_object, 0, properties=self.mqtt_properties)
        else:
            for entry, val in data.items():
                if isinstance(val, float) and self.max_precision >= 0: #apply max_precision on mqtt transport
                    val = round(val, self.max_precision)

                self.client.publish(str(self.base_topic+"/"+from_transport.device_identifier+"/"+entry).lower(), str(val))

    def client_on_message(self, client, userdata, msg):
        """ The callback for when a PUBLISH message is received from the server. """
        self._log.info("MQTT MSG: " + msg.topic+" "+str(msg.payload.decode("utf-8")))

        #self.protocolSettings.validate_registry_entry
        if msg.topic in self.__write_topics:
            entry = self.__write_topics[msg.topic]
            self.on_message(self, entry, msg.payload.decode("utf-8"))
            #self.write_variable(entry, value=str(msg.payload.decode('utf-8')))

    def init_bridge(self, from_transport : transport_base):

        if from_transport.write_enabled:
            self.__write_topics = {}
            #subscribe to write topics
            for entry in from_transport.protocolSettings.get_registry_map(Registry_Type.HOLDING):
                if entry.write_mode == WriteMode.WRITE or entry.write_mode == WriteMode.WRITEONLY:
                    #__write_topics
                    topic : str = self.base_topic + "/"+ from_transport.device_identifier + "/write/" + entry.variable_name.lower().replace(" ", "_")
                    self.__write_topics[topic] = entry
                    self.client.subscribe(topic)

        if self.discovery_enabled:
            self.mqtt_discovery(from_transport)

    def mqtt_discovery(self, from_transport : transport_base):
        self._log.info("Publishing HA Discovery Topics...")

        self.availability_topic = self.base_topic + "/" + from_transport.device_identifier + "/availability"

        disc_payload = {}
        disc_payload["availability_topic"] = self.availability_topic

        device = {}
        device["manufacturer"] = from_transport.device_manufacturer
        device["model"] = from_transport.device_model
        device["identifiers"] = "hotnoob_" + from_transport.device_model + "_" + from_transport.device_serial_number
        device["name"] = from_transport.device_name

        registry_map : list[registry_map_entry] = []
        for entries in from_transport.protocolSettings.registry_map.values():
            registry_map.extend(entries)

        length = len(registry_map)
        count = 0
        for item in registry_map:
            count = count + 1

            if item.concatenate and item.register != item.concatenate_registers[0]:
                continue #skip all except the first register so no duplicates

            if item.write_mode == WriteMode.READDISABLED: #disabled
                continue


            clean_name = item.variable_name.lower().replace(" ", "_").strip()
            if not clean_name: #if name is empty, skip
                continue

            if False:
                if self.__input_register_prefix and item.registry_type == Registry_Type.INPUT:
                    clean_name = self.__input_register_prefix + clean_name

                if self.__holding_register_prefix and item.registry_type == Registry_Type.HOLDING:
                    clean_name = self.__holding_register_prefix + clean_name


            print(("#Publishing Topic "+str(count)+" of " + str(length) + ' "'+str(clean_name)+'"').ljust(100)+"#", end="\r", flush=True)

            #device['sw_version'] = bms_version
            disc_payload = {}
            disc_payload["availability_topic"] = self.base_topic + "/" + from_transport.device_identifier + "/availability"
            disc_payload["device"] = device
            disc_payload["name"] = item.display_name
            disc_payload["unique_id"] = "hotnoob_" + from_transport.device_serial_number + "_"+clean_name

            writePrefix = ""
            if from_transport.write_enabled and ( item.write_mode == WriteMode.WRITE or item.write_mode == WriteMode.WRITEONLY ):
                writePrefix = "" #home assistant doesnt like write prefix

            disc_payload["state_topic"] = self.base_topic + "/" +from_transport.device_identifier + writePrefix+ "/"+clean_name

            if item.unit:
                disc_payload["unit_of_measurement"] = item.unit


            discovery_topic = self.discovery_topic+"/sensor/HN-" + from_transport.device_serial_number  + writePrefix + "/" + disc_payload["name"].replace(" ", "_") + "/config"

            self.client.publish(discovery_topic,
                                       json.dumps(disc_payload),qos=1, retain=True)

            #send WO message to indicate topic is write only
            if item.write_mode == WriteMode.WRITEONLY:
                self.client.publish(disc_payload["state_topic"], "WRITEONLY")

            time.sleep(0.07) #slow down for better reliability

        self.client.publish(disc_payload["availability_topic"],"online",qos=0, retain=True)
        print()
        self._log.info("Published HA "+str(count)+"x Discovery Topics")
