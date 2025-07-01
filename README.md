
![Python 3.9](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/python-3.9.yml/badge.svg)
![Python 3.10](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/python-3.10.yml/badge.svg)
![Python 3.11](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/python-3.11.yml/badge.svg)
![Python 3.12](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/python-3.12.yml/badge.svg)
![Python 3.13](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/python-3.13.yml/badge.svg)

[![PyPI version](https://img.shields.io/pypi/v/python-protocol-gateway.svg)](https://pypi.org/project/python-protocol-gateway/)
[![CodeQL](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/HotNoob/PythonProtocolGateway/actions/workflows/github-code-scanning/codeql)

For advanced configuration help, please checkout the documentation :)
https://github.com/HotNoob/PythonProtocolGateway/tree/main/documentation

# Python Protocol Gateway

Python Protocol Gateway is a python-based service that reads data via Modbus RTU or other protocols and translates the data for MQTT. 
Configuration is handled via a small config files. 
In the long run, Python Protocol Gateway will become a general purpose protocol gateway to translate between more than just modbus and mqtt. 

For specific device installation instructions please checkout the documentation:
Growatt, EG4, Sigineer, SOK, PACE-BMS
https://github.com/HotNoob/PythonProtocolGateway/tree/main/documentation

# General Installation
Connect the USB port on the inverter into your computer / device. This port is essentially modbus usb adapter.
When connected, the device will show up as a serial port. 
 
Alternatively, connect a usb adapter to your rs485 / can port with appropriate wiring. 

### install as homeassistant add-on
checkout:
https://github.com/felipecrs/python-protocol-gateway-hass-addon/tree/master

### install requirements
```
apt install pip python3 -y
pip install -r requirements.txt
```

python 3.9 or greater. python 3.10+ for best compatability. 

### Config file (config.cfg) - copy .example.cfg to .cfg
Edit configuration.
```
cp config.example.cfg  config.cfg
nano config.cfg
```

### inverters / protocols
manually select protocol in .cfg
protocol_version = {{version}}
```
v0.14 = growatt inverters 2020+
sigineer_v0.11 = sigineer inverters
growatt_2020_v1.24 = alt protocol for large growatt inverters - currently untested
srne_v3.9 = SRNE inverters - confirmed working-ish
victron_gx_3.3 = Victron GX Devices - Untested
solark_v1.1 = SolarArk 8/12K Inverters - Untested
hdhk_16ch_ac_module = some chinese current monitoring device :P
srne_2021_v1.96 = SRNE inverters 2021+ (tested at ASF48100S200-H, ok-ish for HF2430U60-100 )

eg4_v58 = eg4 inverters ( EG4-6000XP, EG4-12K, EG4-18K ) - confirmed working
eg4_3000ehv_v1 = eg4 inverters ( EG4_3000EHV )
```

more details on these protocols can be found in the documentation:
https://github.com/HotNoob/PythonProtocolGateway/tree/main/documentation

### run as script
```
python3 -u protocol_gateway.py
```

or

```
python3 -u protocol_gateway.py config.cfg
```

### install as service
ppg can be used as a shorter service name ;)

```
cp protocol_gateway.example.service  /etc/systemd/system/protocol_gateway.service
nano /etc/systemd/system/protocol_gateway.service
```
edit working directory in service file to wherever you put the files
```
nano /etc/systemd/system/protocol_gateway.service
```
reload daemon, enable and start service
```
sudo systemctl daemon-reload
sudo systemctl enable protocol_gateway.service
sudo systemctl start protocol_gateway.service
systemctl status protocol_gateway.service
```

### install mqtt on home assistant
![HA Demo](https://raw.githubusercontent.com/HotNoob/InverterModBusToMQTT/main/images/home%20assistant%20example2.png)

```Settings -> Add-Ons -> Add-On Store -> Mosquitto broker```

setup Mosquitto broker

```Settings -> People -> Users -> Add User -> Can only log in from the local network -> Fill Details ```

once installed; the device should show up on home assistant under mqtt

```Settings -> Devices & Services -> MQTT ```

more docs on setting up mqtt here: https://www.home-assistant.io/integrations/mqtt
i probably might have missed something. ha is new to me.

#### connect mqtt on home assistant with external mqtt broker
[HowTo Connect External MQTT Broker To HomeAssistant](https://www.youtube.com/watch?v=sP2gYLYQat8)

### general update procedure
update files and restart script / service
```
git pull
systemctl restart protocol_gateway.service
```

**if you installed this when it was called growatt2mqtt-hotnoob or invertermodbustomqtt, you'll need to reinstall if you want to update. **

### Unknown Status MQTT Home Assistant 
If all values appear as "Unknown"
This is a bug with home assistant's discovery that some times happens when adding for the first time. just restart the service / script and it will fix itself. 

### variable names
variable names have been modified for greater readability. if it's confusing you can change them via protocols/{version}_input_registry_map.csv
you can also find the original documented variable names there; to use the original names, empty the variable name column
the csvs are using ";" as the delimeter, because that is what open office uses. 

### variable_mask.txt
if you want to only send/get specific variables, put them in variable_mask.txt file. one variable per line. if list is empty all variables will be sent
```
variable1
variable2
```

### variable_screen.txt
if you want to exclude specific variables, put them in the variable_screen.txt file. one variable per line.
```
variable_to_exclude
variable_to_exclude2
```

### Any ModBus RTU Device
As i dive deeper into solar monitoring and general automation, i've come to the realization that ModBus RTU is the "standard" and basically... everything uses it. With how this is setup, it can be used with basically anything running ModBus RTU so long as you have the documentation. 

So... don't mind me as i may add other devices such as battery bms' and... i have a home energy monitor on the way! so i'll be adding that when it arrives.

### donate
this took me a while to make; and i had to make it because there werent any working solutions. 
donations / sponsoring this repo would be appreciated.

### Use Docker
- ```docker build . -t protocol_gateway ```
- ```docker run --device=/dev/ttyUSB0 protocol_gateway```

### Use Docker Image
- ``` docker pull hotn00b/pythonprotocolgateway ``` 
- ```docker run -v $(pwd)/config.cfg:/app/config.cfg --device=/dev/ttyUSB0 hotn00b/pythonprotocolgateway```

See [config.cfg.example](https://github.com/HotNoob/PythonProtocolGateway/blob/main/config.cfg.example)

[Docker Image Repo](https://hub.docker.com/r/hotn00b/pythonprotocolgateway)
