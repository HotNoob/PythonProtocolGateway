![ppg modbus flow drawio](https://github.com/user-attachments/assets/d9d59dc3-2a0a-4b34-8db7-ac054dccc67e)


### ModBus RTU to MQTT
```
[general]
log_level = DEBUG

[transport.0] #name must be unique, ie: transport.modbus
#rs485 / modbus device
#protocol config files are located in protocols/
protocol_version = v0.14
analyze_protocol = false
write = false

#modbus address
address = 1
port = {{serial port, likely /dev/ttyUSB0}}
baudrate = 9600

#modbus tcp/tls/udp example
#host = 192.168.0.7
#port = 502
#override protocol reader
#transport = modbus_tcp

#the 'transport' that we want to share this with
bridge = transport.1

manufacturer = {{Your device's manufacturer here}}
model = {{Your device's model number here}}
#optional; leave blank to autofetch serial from device
serial_number = 

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

