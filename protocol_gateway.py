#!/usr/bin/env python3
"""
Main module for Growatt / Inverters ModBus RTU data to MQTT
"""


import importlib
import sys
import time
import threading

# Check if Python version is greater than 3.9
if sys.version_info < (3, 9):
    print("==================================================")
    print("WARNING: python version 3.9 or higher is recommended")
    print("Current version: " + sys.version)
    print("Please upgrade your python version to 3.9")
    print("==================================================")
    time.sleep(4)


import argparse
import logging
import os
import sys
import traceback
from configparser import ConfigParser, NoOptionError

from classes.protocol_settings import protocol_settings, registry_map_entry
from classes.transports.transport_base import transport_base

__logo = """

██████╗ ██╗   ██╗████████╗██╗  ██╗ ██████╗ ███╗   ██╗
██╔══██╗╚██╗ ██╔╝╚══██╔══╝██║  ██║██╔═══██╗████╗  ██║
██████╔╝ ╚████╔╝    ██║   ███████║██║   ██║██╔██╗ ██║
██╔═══╝   ╚██╔╝     ██║   ██╔══██║██║   ██║██║╚██╗██║
██║        ██║      ██║   ██║  ██║╚██████╔╝██║ ╚████║
╚═╝        ╚═╝      ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝

██████╗ ██████╗  ██████╗ ████████╗ ██████╗  ██████╗ ██████╗ ██╗          ██████╗  █████╗ ████████╗███████╗██╗    ██╗ █████╗ ██╗   ██╗
██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝██╔═══██╗██╔════╝██╔═══██╗██║         ██╔════╝ ██╔══██╗╚══██╔══╝██╔════╝██║    ██║██╔══██╗╚██╗ ██╔╝
██████╔╝██████╔╝██║   ██║   ██║   ██║   ██║██║     ██║   ██║██║         ██║  ███╗███████║   ██║   █████╗  ██║ █╗ ██║███████║ ╚████╔╝
██╔═══╝ ██╔══██╗██║   ██║   ██║   ██║   ██║██║     ██║   ██║██║         ██║   ██║██╔══██║   ██║   ██╔══╝  ██║███╗██║██╔══██║  ╚██╔╝
██║     ██║  ██║╚██████╔╝   ██║   ╚██████╔╝╚██████╗╚██████╔╝███████╗    ╚██████╔╝██║  ██║   ██║   ███████╗╚███╔███╔╝██║  ██║   ██║
╚═╝     ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝  ╚═════╝ ╚═════╝ ╚══════╝     ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝

"""  # noqa: W291


class CustomConfigParser(ConfigParser):
    def get(self, section, option, *args, **kwargs):
        if isinstance(option, list):
            fallback = None

            if "fallback" in kwargs: #override kwargs fallback, for manually handling here
                fallback = kwargs["fallback"]
                kwargs["fallback"] = None

            for name in option:
                try:
                    value = super().get(section, name, *args, **kwargs)
                except NoOptionError:
                    value = None

                if value:
                    break

            if not value:
                value = fallback

            if value is None:
                raise NoOptionError(option[0], section)
        else:
            value = super().get(section, option, *args, **kwargs)

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return value

        return value.strip() if value is not None else value

    def getint(self, section, option, *args, **kwargs): #bypass fallback bug
        value = self.get(section, option, *args, **kwargs)
        return int(value) if value is not None else None

    def getfloat(self, section, option, *args, **kwargs): #bypass fallback bug
        value = self.get(section, option, *args, **kwargs)
        return float(value) if value is not None else None


class Protocol_Gateway:
    """
    Main class, implementing the Growatt / Inverters to MQTT functionality
    """
    __log = None
    # log level, available log levels are CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG
    __log_level = "DEBUG"

    __running : bool = False
    ''' controls main loop'''

    __transports : list[transport_base] = []
    ''' transport_base is for type hinting. this can be any transport'''

    config_file : str
    
    # Simple read completion tracking
    __read_completion_tracker : dict[str, bool] = {}
    ''' Track which transports have completed their current read cycle '''
    __read_tracker_lock : threading.Lock = None
    
    # Concurrency control
    __disable_concurrency : bool = True
    ''' When true, transports read sequentially instead of concurrently '''
    
    # Transport timing control
    __transport_delay_offset : float = 0.5
    ''' Additional delay between different transports to prevent conflicts '''

    def __init__(self, config_file : str):
        self.__log = logging.getLogger("invertermodbustomqqt_log")
        handler = logging.StreamHandler(sys.stdout)
        #self.__log.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(asctime)s]  {%(filename)s:%(lineno)d}  %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        self.__log.addHandler(handler)

        self.config_file = os.path.dirname(os.path.realpath(__file__)) + "/growatt2mqtt.cfg"
        newcfg = os.path.dirname(os.path.realpath(__file__)) + "/"+ config_file
        if os.path.isfile(newcfg):
            self.config_file = newcfg

        #logging.basicConfig()
        #pymodbus_log = logging.getLogger('pymodbus')
        #pymodbus_log.setLevel(logging.DEBUG)
        #pymodbus_log.addHandler(handler)

        self.__log.info("Loading...")

        self.__settings = CustomConfigParser()
        self.__settings.read(self.config_file)

        ##[general]
        self.__log_level = self.__settings.get("general","log_level", fallback="INFO")
        
        # Read concurrency setting
        self.__disable_concurrency = self.__settings.getboolean("general", "disable_concurrency", fallback=True)
        self.__log.info(f"Concurrency mode: {'Sequential' if self.__disable_concurrency else 'Concurrent'}")

        log_level = getattr(logging, self.__log_level, logging.INFO)
        self.__log.setLevel(log_level)
        logging.basicConfig(level=log_level)

        for section in self.__settings.sections():
            transport_cfg = self.__settings[section]
            transport_type      = transport_cfg.get("transport", fallback="")
            protocol_version    = transport_cfg.get("protocol_version", fallback="")

            # Process sections that either start with "transport" OR have a transport field
            if section.startswith("transport") or transport_type:
                if not transport_type and not protocol_version:
                    raise ValueError("Missing Transport / Protocol Version")

                if not transport_type and protocol_version: #get transport from protocol settings...  todo need to make a quick function instead of this

                    protocolSettings : protocol_settings = protocol_settings(protocol_version)

                    if not transport_type and not protocolSettings.transport:
                        raise ValueError("Missing Transport")

                    if not transport_type:
                        transport_type = protocolSettings.transport


                # Import the module
                module = importlib.import_module("classes.transports."+transport_type)
                # Get the class from the module
                cls = getattr(module, transport_type)
                transport : transport_base = cls(transport_cfg)

                transport.on_message = self.on_message
                self.__transports.append(transport)

        #connect first
        for transport in self.__transports:
            self.__log.info("Connecting to "+str(transport.type)+":" +str(transport.transport_name)+"...")
            transport.connect()

        time.sleep(0.7)
        #apply links
        for to_transport in self.__transports:
            for from_transport in self.__transports:
                if to_transport.bridge == from_transport.transport_name:
                    to_transport.init_bridge(from_transport)
                    from_transport.init_bridge(to_transport)
        
        # Initialize read completion tracking
        self.__read_tracker_lock = threading.Lock()
        for transport in self.__transports:
            if transport.read_interval > 0:
                self.__read_completion_tracker[transport.transport_name] = False

    def on_message(self, transport : transport_base, entry : registry_map_entry, data : str):
        ''' message recieved from a transport! '''
        for to_transport in self.__transports:
            if to_transport.transport_name != transport.transport_name:
                if to_transport.transport_name == transport.bridge or transport.transport_name == to_transport.bridge:
                    to_transport.write_data({entry.variable_name : data}, transport)
                    break

    def _process_transport_read(self, transport):
        """Process a single transport read operation"""
        try:
            if not transport.connected:
                transport.connect() #reconnect
            else: #transport is connected
                self.__log.debug(f"Starting read cycle for {transport.transport_name}")
                info = transport.read_data()

                if not info:
                    self.__log.warning(f"Transport {transport.transport_name} completed read cycle with NO DATA - this may indicate a device issue")
                    self._mark_read_complete(transport)
                    return

                self.__log.debug(f"Transport {transport.transport_name} completed read cycle with {len(info)} fields")
                
                # Write to output transports immediately (as before)
                if transport.bridge:
                    for to_transport in self.__transports:
                        if to_transport.transport_name == transport.bridge:
                            to_transport.write_data(info, transport)
                            break
                
                self._mark_read_complete(transport)
                
        except Exception as err:
            self.__log.error(f"Error processing transport {transport.transport_name}: {err}")
            traceback.print_exc()
            self._mark_read_complete(transport)

    def _mark_read_complete(self, transport):
        """Mark a transport as having completed its read cycle"""
        with self.__read_tracker_lock:
            self.__read_completion_tracker[transport.transport_name] = True
            self.__log.debug(f"Marked {transport.transport_name} read cycle as complete")

    def _reset_read_completion_tracker(self):
        """Reset the read completion tracker for the next cycle"""
        with self.__read_tracker_lock:
            for transport_name in self.__read_completion_tracker:
                self.__read_completion_tracker[transport_name] = False

    def _get_read_completion_status(self):
        """Get the current read completion status for debugging"""
        with self.__read_tracker_lock:
            return self.__read_completion_tracker.copy()

    def run(self):
        """
        run method, starts ModBus connection and mqtt connection
        """

        self.__running = True

        if False:
            self.enable_write()

        while self.__running:
            try:
                now = time.time()
                ready_transports = []
                
                # Find all transports that are ready to read
                for transport in self.__transports:
                    if transport.read_interval > 0 and now - transport.last_read_time > transport.read_interval:
                        transport.last_read_time = now
                        ready_transports.append(transport)
                
                # Reset read completion tracker for this cycle
                if ready_transports:
                    self._reset_read_completion_tracker()
                    self.__log.debug(f"Starting read cycle for {len(ready_transports)} transports: {[t.transport_name for t in ready_transports]}")
                
                # Process transports based on concurrency setting
                if self.__disable_concurrency:
                    # Sequential processing - process transports one by one
                    for i, transport in enumerate(ready_transports):
                        self.__log.debug(f"Processing {transport.transport_name} sequentially ({i+1}/{len(ready_transports)})")
                        self._process_transport_read(transport)
                    
                    # Log completion status for sequential mode
                    completion_status = self._get_read_completion_status()
                    completed = [name for name, status in completion_status.items() if status]
                    self.__log.debug(f"Sequential read cycle completed. Completed transports: {completed}")
                    
                else:
                    # Concurrent processing - process transports in parallel
                    if len(ready_transports) > 1:
                        threads = []
                        for transport in ready_transports:
                            thread = threading.Thread(target=self._process_transport_read, args=(transport,))
                            thread.daemon = True
                            thread.start()
                            threads.append(thread)
                        
                        # Wait for all threads to complete
                        for thread in threads:
                            thread.join()
                        
                        # Log completion status
                        completion_status = self._get_read_completion_status()
                        completed = [name for name, status in completion_status.items() if status]
                        self.__log.debug(f"Concurrent read cycle completed. Completed transports: {completed}")
                        
                    elif len(ready_transports) == 1:
                        # Single transport - process directly
                        self._process_transport_read(ready_transports[0])

            except Exception as err:
                traceback.print_exc()
                self.__log.error(err)

            time.sleep(0.07) #change this in future. probably reduce to allow faster reads.






def main(args=None):
    """
    main method
    """

    # Create ArgumentParser object
    parser = argparse.ArgumentParser(description="Python Protocol Gateway")

    # Add arguments
    parser.add_argument("--config", "-c", type=str, help="Specify Config File")

    # Add a positional argument with default
    parser.add_argument("positional_config", type=str, help="Specify Config File", nargs="?", default="config.cfg")

    # Parse arguments
    args = parser.parse_args()

    # If '--config' is provided, use it; otherwise, fall back to the positional or default.
    args.config = args.config if args.config else args.positional_config

    print(__logo)

    ppg = Protocol_Gateway(args.config)
    ppg.run()


if __name__ == "__main__":
    main()
