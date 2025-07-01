import asyncio
import os
import platform
import re
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

import can

from defs.common import strtoint

from ..protocol_settings import Registry_Type, protocol_settings, registry_map_entry
from .transport_base import transport_base

if TYPE_CHECKING:
    from configparser import SectionProxy

class canbus(transport_base):
    ''' canbus is a more passive protocol; todo to include active commands to trigger canbus responses '''

    interface : str = "socketcan"
    ''' bustype / interface for canbus device '''

    port : str = ""
    ''' 'can0' '''

    baudrate : int = 500000

    bus : can.BusABC = None
    ''' holds canbus interface'''

    reader = can.AsyncBufferedReader()

    thread : threading.Thread
    ''' main thread for async loop'''

    #lock : threading.Lock = threading.Lock()
    lock : threading.Lock = None
    loop : asyncio.AbstractEventLoop = None

    cache : OrderedDict [int,(bytes, float)] = None
    ''' cache, key is id, value is touple (data, timestamp)'''

    cacheTimeout : int = 120
    ''' seconds to keep message in cache '''

    emptyTime : float = None
    ''' the last time values were read for watchdog'''

    watchDogTime : float = 120
    ''' number of seconds of empty cache before restarting'''

    linux : bool = True


    def __init__(self, settings : "SectionProxy", protocolSettings : "protocol_settings" = None):
        super().__init__(settings)

        #check if running on windows or linux
        self.linux = platform.system() != "Windows"


        self.port = settings.get(["port", "channel"], "")
        if not self.port:
            raise ValueError("Port/Channel is not set")

        #get default baud from protocol settings
        if "baud" in self.protocolSettings.settings:
            self.baudrate = strtoint(self.protocolSettings.settings["baud"])

        self.baudrate = settings.getint(["baudrate", "bitrate"], self.baudrate)
        self.interface = settings.get(["interface", "bustype"], self.interface).lower()
        self.cacheTimeout = settings.getint(["cacheTimeout", "cache_timeout"], self.cacheTimeout)

        #setup / configure socketcan
        if self.interface == "socketcan":
            self.setup_socketcan()
            self.port = self.port.lower()

        self.bus = can.interface.Bus(interface=self.interface, channel=self.port, bitrate=self.baudrate)
        self.reader = can.AsyncBufferedReader()
        self.lock = threading.Lock()
        with self.lock:
            self.cache = OrderedDict()


        # Set up an event loop and run the async function
        #self.loop = asyncio.get_event_loop()

        #notifier = can.Notifier(self.bus, [self.reader], loop=self.loop)


        thread = threading.Thread(target=self.start_loop)
        thread.daemon = True
        thread.start()

        self.connected = True
        self.emptyTime =time.time()

        self.init_after_connect()

    def setup_socketcan(self):
        ''' ensures socketcan interface is up and applies some common hotfixes '''
        if not self.linux:
            print("socketcan setup not implemented for windows")
            return

        # ruff: noqa: S605, S607
        self._log.info("restart and configure socketcan")
        os.system("ip link set can0 down")
        os.system("ip link set can0 type can restart-ms 100")
        os.system("ip link set can0 up type can bitrate " + str(self.baudrate))

    def is_socketcan_up(self) -> bool:
        if not self.linux:
            self._log.error("socketcan status not implemented for windows")
            return True

        try:
            with open(f"/sys/class/net/{self.port}/operstate", "r") as f:
                state = f.read().strip()
        except FileNotFoundError:
            return False
        else:
            return state == "up"

    def start_loop(self):
        self.read_bus(self.bus)

    def read_bus(self, bus : can.BusABC):
        ''' read canbus asynco and store results in cache'''
        msg = None #fix scope bug

        while True:
            try:
                msg = self.bus.recv()  # This will be non-blocking with asyncio

            except can.CanError as e:
                # Handle specific CAN errors
                self._log.error(f"CAN error: {e}")
            except asyncio.CancelledError:
                # Handle the case where the task is cancelled
                self._log.error("Read bus task was cancelled.")
                break
            except Exception as e:
                # Handle unexpected errors
                self._log.error(f"An unexpected error occurred: {e}")


            if msg:
                self._log.info(f"Received message: {msg.arbitration_id:X}, data: {msg.data}")

                with self.lock:
                    #convert bytearray to bytes; were working with bytes.
                    self.cache[msg.arbitration_id] = (bytes(msg.data), time.time())

                #time.sleep(1) no need for sleep because recv is blocking


    def clean_cache(self):
        current_time = time.time()

        with self.lock:
            # Create a list of keys to remove (don't remove while iterating)
            keys_to_delete = [msg_id for msg_id, (_, timestamp) in self.cache.items() if current_time - timestamp > self.cacheTimeout]

            # Remove old messages from the dictionary
            for key in keys_to_delete:
                del self.cache[key]

    def init_after_connect(self):
        return True

        ''' todo, a startup phase to get serial number'''
        #from transport_base settings
        if self.write_enabled:
            self.enable_write()

        #if sn is empty, attempt to autoread it
        if not self.device_serial_number:
            self.device_serial_number = self.read_serial_number()

    def read_serial_number(self) -> str:
        ''' not so simple in canbus'''
        return ""
        serial_number = str(self.read_variable("Serial Number", Registry_Type.HOLDING))
        print("read SN: " +serial_number)
        if serial_number:
            return serial_number

        sn2 = ""
        sn3 = ""
        fields = ["Serial No 1", "Serial No 2", "Serial No 3", "Serial No 4", "Serial No 5"]
        for field in fields:
            self._log.info("Reading " + field)
            registry_entry = self.protocolSettings.get_holding_registry_entry(field)
            if registry_entry is not None:
                self._log.info("Reading " + field + "("+str(registry_entry.register)+")")
                data = self.read_modbus_registers(registry_entry.register, registry_type=Registry_Type.HOLDING)
                if not hasattr(data, "registers") or data.registers is None:
                    self._log.critical("Failed to get serial number register ("+field+") ; exiting")
                    exit()

                serial_number = serial_number  + str(data.registers[0])

                data_bytes = data.registers[0].to_bytes((data.registers[0].bit_length() + 7) // 8, byteorder="big")
                sn2 = sn2 + str(data_bytes.decode("utf-8"))
                sn3 = str(data_bytes.decode("utf-8")) + sn3

            time.sleep(self.modbus_delay*2) #sleep inbetween requests so modbus can rest

        print(sn2)
        print(sn3)

        if not re.search(r"[^a-zA-Z0-9\_]", sn2) :
            serial_number = sn2

        return serial_number

    def enable_write(self):
        self.write_enabled = True
        self._log.warning("enable write - validation on the todo")

    def write_data(self, data : dict[str, str], from_transport : transport_base) -> None:
        if not self.write_enabled:
            return

    def read_data(self) -> dict[str, str]:
        ''' because canbus is passive / broadcast, were just going to read from the cache '''

        info = {}

        #remove timestamp for processing
        with self.lock:
            registry = {key: value[0] for key, value in self.cache.items()}

        new_info = self.protocolSettings.process_registery(registry, self.protocolSettings.get_registry_map(Registry_Type.ZERO))

        info.update(new_info)

        currentTime = time.time()

        if not info:
            self._log.info("Register/Cache is Empty; no new information reported.")
            if currentTime - self.emptyTime > self.watchDogTime:
                self._log.error("Register/Cache has been empty for over " + str(self.watchDogTime) + "seconds. watchdog qutting application. ")
                quit() #quit application, service should be configured to restart

        else:
            self.emptyTime = currentTime

        self.clean_cache() #clean cache of old data

        return info

    def read_variable(self, variable_name : str, registry_type : Registry_Type, entry : registry_map_entry = None):
        ''' read's variable from cache'''
        ##clean for convinecne
        if variable_name:
            variable_name = variable_name.strip().lower().replace(" ", "_")

        registry_map = self.protocolSettings.get_registry_map(registry_type)

        if entry is None:
            for e in registry_map:
                if e.variable_name == variable_name:
                    entry = e
                    break

        if entry:
            #no concat for canbus or concat on todo
            with self.lock:
                if entry.register in self.cache:
                    results = self.protocolSettings.process_register_bytes(self.cache, entry)
                    return results[entry.variable_name]
                else:
                    return None #empty
