![ppg canbus diagram drawio](https://github.com/user-attachments/assets/17d1ea02-2414-4289-b295-cd5099679cba)


### CanBus to MQTT
```
[general]
log_level = DEBUG

[transport.0] #name must be unique, ie: transport.canbus
#canbus device
#protocol config files are located in protocols/
protocol_version = victron_gx_generic_canbus

#canbus port or interface; varies based on usb adapter
port = can0
bustype = socketcan
baudrate = 500000

#the 'transport' that we want to share this with
bridge = transport.1

manufacturer = {{Your device's manufacturer here}}
model = {{Your device's model number here}}
#optional; leave blank to autofetch serial from device. on the todo to autofetch serial for canbus
serial_number = {{random numbers here}}

# canbus is a passive protocol, this is how often information is sent to mqtt. actual data interval is dependant on device
read_interval = 10 


[transport.1]
#connect mqtt
transport=mqtt
host = {{mqtt ip / host}}
port = 1883
user = {{mqtt username here}}
pass = {{mqtt password}}
base_topic = home/inverter/
error_topic = /error
json = false
discovery_enabled = true
discovery_topic = homeassistant
```

