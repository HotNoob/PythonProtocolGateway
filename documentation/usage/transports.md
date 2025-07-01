# Transports

A transport is configured by creating a configuration section, starting with "transport."
```
[transport.0]
{transport config here}
```
or
```
[transport.growatt]
{transport config here}
```

the section header is dual purpose and acts as naming mechanism for parameters like "bridge"

## Protocol
Transports using ambigious open ended protocols, such as ModBus, Canbus, or register / address based protocols require a map to be defined. this is done so in the /protocols/ folder through csv tables. 

```
protocol = v0.14
```

see [Protocol Wiki](https://github.com/HotNoob/PythonProtocolGateway/wiki/Protocols) for more on this. 

Other transport protocols such as MQTT, do not require this configuration, as the variable names are provided during transmision and therefore do not need interpretation. 

### Reading
Some transports are Event based, such as MQTT, while others are require active reading. 
for protocols that require active reading such as ModBus, the scan interval is set via "read_interval"

```
read_interval = 10
```

### Writing
For ambigious sensitive protocols/transports such as ModBus, a safety mechanism is in place to help prevent "bricking" your devices or causing potentially catostrophic damages.

In order to write, the configuration csv file must be at least 90% verifiable. Alternatively a manual verification method will be implemented in the future. This mainly entails that the current values in the writeable register ( probably holding ), be within the value range specified in the csv. 


#### Write Safety Modes
``` write = false ```
default value; writting is disabled

``` write = true ```
default "write" behaviour; includes all validations / safties.

```write = relaxed ``` ( dangerous - make sure you have the right protocol )
 skips the initial ( score % ) / bulk validation

``` write = unsafe ``` ( very dangerous )
skips all write safties. 


Finally, to write, "read" data on any bridged transport. In most cases this will likely be MQTT. 

### Custom Transport
custom transports can be created by naming them name.custom and creating the appropriate .py file. 
for example a custom mqtt transport:
copy classes/transports/mqtt.py to classes/transports/mqtt.custom.py

to use this custom transport:
```
transport=mqtt.custom
```

naming your transport with .custom will ensure that it won't be overwritten when updating. 

# Base
These are parameters that apply to all transports
```
transport = 
device_name = 
manufacturer = 
model =
serial_number =
bridge = 
write_enabled = False
Interval = 10
```
### transport
Transport is the type or method of reading and writing data
```
transport = modbus_rtu
```


### device_name
device_name is used as an identifier and is passed on where applicable.
if left blank, device_name will be set to manufacturer + model
```
device_name = My Solar Inverter 1
```

### manufacturer 
manufacturer is used as an identifier and is passed on where applicable.
```
manufacturer = Growatt
```

### model
model is used as an identifier and is passed on where applicable.
```
model = SPF 12000T
```

### serial_number
serial_number is used as an identifier and is passed on where applicable.
If left empty, serial number may be automatically fetched if protocol supports it. 
``` 
serial_number = 
```

### bridge
bridge determines which transports to translate data to
this value can be a csv to specify multiple transports
if bridge is set to "broadcast", data will be broadcasted / sent over all configured transports
```
bridge = transport.mqtt
```

### write_enabled 
write_enabled allows writting to this transport if enabled. 
many protocols have this disabled by default and require accurate registry maps to enable writing, as misconfiguration can have fatal unintended consequences. 
by default mqtt allows writing.
```
write_enabled  = True
```

#Interval
Interval ( seconds ), sets the frequency of how often data is actively read from a transport.
If interval is not set, data is only sent passively as events occur. 
```
Interval = 10
```

# MQTT
```
###required
Transport = MQTT
Host
Port 
User
Pass
Base_Topic = 
discovery_enabled = True
discovery_topic = homeassistant
```

```
###optional
Json = False
Error_Topic = /error
holding_register_prefix =
input_register_prefix = 
```

## MQTT Read
mqtt "reads" data via the "write" topic. 
data that is "read" on the mqtt transport is "written" on any bridged transports. 
i know... confusing :P

during the initialization process, MQTT subscribes to "write enabled" variables / topics, based on the bridged transport's protocol. 
the writable topics are given a prefix of "/write/"
```
{base topic}/write/{variable name}
```

## MQTT Write
by default mqtt writes data from the bridged transport. 

# JSON Output
```
###required
transport = json_out
```

```
###optional
output_file = stdout
pretty_print = true
append_mode = false
include_timestamp = true
include_device_info = true
```

## JSON Output Configuration

### output_file
Specifies the output destination. Use `stdout` for console output or provide a file path.
```
output_file = stdout
output_file = /var/log/inverter_data.json
```

### pretty_print
Whether to format JSON with indentation for readability.
```
pretty_print = true
```

### append_mode
Whether to append to file instead of overwriting. Useful for log files.
```
append_mode = false
```

### include_timestamp
Whether to include Unix timestamp in the JSON output.
```
include_timestamp = true
```

### include_device_info
Whether to include device metadata (identifier, name, manufacturer, etc.) in the JSON output.
```
include_device_info = true
```

## JSON Output Format

The JSON output includes the following structure:

```json
{
  "device": {
    "identifier": "device_serial",
    "name": "Device Name",
    "manufacturer": "Manufacturer",
    "model": "Model",
    "serial_number": "Serial Number",
    "transport": "transport_name"
  },
  "timestamp": 1703123456.789,
  "data": {
    "variable_name": "value",
    "another_variable": "another_value"
  }
}
```

## JSON Output Use Cases

1. **Debugging**: Output data to console for real-time monitoring
2. **Logging**: Write data to log files for historical analysis
3. **Integration**: Feed data to other systems that consume JSON
4. **Data Collection**: Collect data for analysis or backup purposes

# InfluxDB Output
```
###required
transport = influxdb_out
host = 
port = 
database = 
```

```
###optional
username = 
password = 
measurement = device_data
include_timestamp = true
include_device_info = true
batch_size = 100
batch_timeout = 10.0
```

## InfluxDB Output Configuration

### host
InfluxDB server hostname or IP address.
```
host = localhost
host = 192.168.1.100
```

### port
InfluxDB server port (default: 8086).
```
port = 8086
```

### database
Database name. Will be created automatically if it doesn't exist.
```
database = solar
database = inverter_data
```

### username
Username for authentication (optional).
```
username = admin
```

### password
Password for authentication (optional).
```
password = your_password
```

### measurement
InfluxDB measurement name for storing data points.
```
measurement = device_data
measurement = inverter_metrics
```

### include_timestamp
Whether to include timestamp in data points.
```
include_timestamp = true
```

### include_device_info
Whether to include device metadata as InfluxDB tags.
```
include_device_info = true
```

### batch_size
Number of data points to batch before writing to InfluxDB.
```
batch_size = 100
```

### batch_timeout
Maximum time (seconds) to wait before flushing batch.
```
batch_timeout = 10.0
```

## InfluxDB Data Structure

The InfluxDB output creates data points with the following structure:

### Tags (if `include_device_info = true`)
- `device_identifier`: Device serial number (lowercase)
- `device_name`: Device name
- `device_manufacturer`: Device manufacturer
- `device_model`: Device model
- `device_serial_number`: Device serial number
- `transport`: Source transport name

### Fields
All device data values are stored as fields. The transport automatically converts:
- Numeric strings to integers or floats
- Non-numeric strings remain as strings

### Time
- Uses current timestamp in nanoseconds (if `include_timestamp = true`)
- Can be disabled for custom timestamp handling

## InfluxDB Output Use Cases

1. **Time-Series Data Storage**: Store historical device data for analysis
2. **Grafana Integration**: Visualize data with Grafana dashboards
3. **Data Analytics**: Perform time-series analysis and trending
4. **Monitoring**: Set up alerts and monitoring based on data thresholds

## Example InfluxDB Queries

```sql
-- Show all measurements
SHOW MEASUREMENTS

-- Query recent data
SELECT * FROM device_data WHERE time > now() - 1h

-- Query specific device
SELECT * FROM device_data WHERE device_identifier = '123456789'

-- Aggregate data
SELECT mean(value) FROM device_data WHERE field_name = 'battery_voltage' GROUP BY time(5m)
```

# ModBus_RTU
```
###required
transport = modbus_rtu
protocol_version =
Port = 
BaudRate = 
Address = 
```
### port
Port is the path to the communications port. on Windows this would be COM#, for Linux /dev/ttyUSB#

these port numbers can change upon restarting, therefore alternatively, the port can be specified via hardware ids (v1.1.2+):
```
port = [0x1a86:0x7523::1-4]
```

The hardware ids format is:
```
[vendor id:product id:serial number:location]
```

for convience the hardware ids are outputted during script startup.
```
Serial Port : COM11 = [0x1a86:0x7523::1-4]
```

### analyze_protocol
needs a lot of work. on the todo to improve. low priority
```
analyze_protocol = true
```

when this mode runs, it attempt to read all of the registers of your inverter and attempt to determine which protocol best fits. 
the higher the value, the more likely that the protocol matches. 

```
=== growatt_2020_v1.24 - 710 ===
input register : 405 of 695
holding register : 305 of 561
=== sigineer_v0.11 - 62 ===
input register : 31 of 150
holding register : 31 of 63
=== v0.14 - 60 ===
input register : 19 of 63
holding register : 41 of 101
```

the results above suggests that "growatt_2020_v1.24" is the most likely protocol for the inverter.

### analyze_protocol_save_load
```
analyze_protocol = true
analyze_protocol_save_load = true
```
When enabled, the analyzer will save dump files containing the raw data found while scanning

# CanBus

```
transport = canbus
protocol_version =

port = 
bustype = socketcan
buadrate = 

```

## Linux / Windows
usb can adapters are a pain with windows, so primary focus is linux. 

## CanBus USB Adapters

there is a bit of a learning curve with canbus usb adapters. 

the main adapter being used to test python protocol gateway: https://github.com/FYSETC/UCAN
these are dime a dozen on aliexpress / ebay / wherever. most of them will be based on the CANable adapters. 

fysetc sells them directly here: https://www.fysetc.com/products/fysetc-ucan-board
this adapter comes with the candlelight ( socketcan ) by default. the board is CANable v1.0 compatible. slcan firmware can be flashed here: https://canable.io/updater/canable1.html

candlelight utilizes socketcan, slcan is can over serial. 

here is some extra reading material to help on using a usb canbus adapter: https://canable.io/getting-started.html

### candlelight / socketcan
This adapter will appear as a gs_usb device, and the can inteface will appear as an ip interface

``` ip link show ```

### slcan
This adapter will appear as a serial device. 

```
bustype = slcan
```
