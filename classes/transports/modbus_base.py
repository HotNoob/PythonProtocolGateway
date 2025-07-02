import glob
import json
import os
import re
import time
import threading
from typing import TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime, timedelta

from pymodbus.exceptions import ModbusIOException
from pymodbus.pdu import ExceptionResponse  # Import for exception code constants

from defs.common import strtobool

# Modbus function codes for exception interpretation
MODBUS_FUNCTION_CODES = {
    0x01: "Read Coils",
    0x02: "Read Discrete Inputs", 
    0x03: "Read Holding Registers",
    0x04: "Read Input Registers",
    0x05: "Write Single Coil",
    0x06: "Write Single Register",
    0x0F: "Write Multiple Coils",
    0x10: "Write Multiple Registers",
    0x14: "Read File Record",
    0x15: "Write File Record",
    0x16: "Mask Write Register",
    0x17: "Read/Write Multiple Registers",
    0x2B: "Read Device Identification"
}

# Modbus exception codes for exception interpretation (from pymodbus.pdu.ExceptionResponse)
MODBUS_EXCEPTION_CODES = {
    ExceptionResponse.ILLEGAL_FUNCTION: "ILLEGAL_FUNCTION",
    ExceptionResponse.ILLEGAL_ADDRESS: "ILLEGAL_ADDRESS",
    ExceptionResponse.ILLEGAL_VALUE: "ILLEGAL_VALUE",
    ExceptionResponse.SLAVE_FAILURE: "SLAVE_FAILURE",
    ExceptionResponse.ACKNOWLEDGE: "ACKNOWLEDGE",
    ExceptionResponse.SLAVE_BUSY: "SLAVE_BUSY",
    ExceptionResponse.NEGATIVE_ACKNOWLEDGE: "NEGATIVE_ACKNOWLEDGE",
    ExceptionResponse.MEMORY_PARITY_ERROR: "MEMORY_PARITY_ERROR",
    ExceptionResponse.GATEWAY_PATH_UNAVIABLE: "GATEWAY_PATH_UNAVAILABLE",
    ExceptionResponse.GATEWAY_NO_RESPONSE: "GATEWAY_NO_RESPONSE"
}

# Descriptions for Modbus exception codes (using ExceptionResponse constants as keys)
MODBUS_EXCEPTION_DESCRIPTIONS = {
    ExceptionResponse.ILLEGAL_FUNCTION: "The function code received in the query is not an allowable action for the slave",
    ExceptionResponse.ILLEGAL_ADDRESS: "The data address received in the query is not an allowable address for the slave",
    ExceptionResponse.ILLEGAL_VALUE: "A value contained in the query data field is not an allowable value for the slave",
    ExceptionResponse.SLAVE_FAILURE: "An unrecoverable error occurred while the slave was attempting to perform the requested action",
    ExceptionResponse.ACKNOWLEDGE: "The slave has accepted the request and is processing it, but a long duration of time will be required",
    ExceptionResponse.SLAVE_BUSY: "The slave is engaged in processing a long-duration program command",
    ExceptionResponse.NEGATIVE_ACKNOWLEDGE: "The slave cannot perform the program function received in the query",
    ExceptionResponse.MEMORY_PARITY_ERROR: "The slave attempted to read record file, but detected a parity error in the memory",
    ExceptionResponse.GATEWAY_PATH_UNAVIABLE: "The gateway path is not available",
    ExceptionResponse.GATEWAY_NO_RESPONSE: "The gateway target device failed to respond"
}

def interpret_modbus_exception_code(code):
    """
    Interpret a Modbus exception response code and return human-readable information.
    
    Args:
        code (int): The exception response code (e.g., 132)
        
    Returns:
        str: Human-readable description of the exception
    """
    # Extract function code (lower 7 bits)
    function_code = code & 0x7F
    
    # Check if this is an exception response (upper bit set)
    if code & 0x80:
        # This is an exception response
        exception_code = code & 0x7F  # The exception code is in the lower 7 bits
        function_name = MODBUS_FUNCTION_CODES.get(function_code, f"Unknown Function ({function_code})")
        exception_name = MODBUS_EXCEPTION_CODES.get(exception_code, f"Unknown Exception ({exception_code})")
        description = MODBUS_EXCEPTION_DESCRIPTIONS.get(exception_code, "Unknown exception code")
        return f"Modbus Exception: {function_name} failed with {exception_name} - {description}"
    else:
        # This is not an exception response
        function_name = MODBUS_FUNCTION_CODES.get(function_code, f"Unknown Function ({function_code})")
        return f"Modbus Function: {function_name} (not an exception response)"

from ..protocol_settings import (
    Data_Type,
    Registry_Type,
    WriteMode,
    protocol_settings,
    registry_map_entry,
)
from .transport_base import TransportWriteMode, transport_base

if TYPE_CHECKING:
    from configparser import SectionProxy
    try:
        from pymodbus.client.sync import BaseModbusClient
    except ImportError:
        from pymodbus.client import BaseModbusClient


@dataclass
class RegisterFailureTracker:
    """Tracks register read failures and manages soft disabling"""
    register_range: tuple[int, int]  # (start, end) register range
    registry_type: Registry_Type
    failure_count: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    disabled_until: float = 0  # Unix timestamp when disabled until
    _lock: threading.Lock = None
    
    def __post_init__(self):
        if self._lock is None:
            self._lock = threading.Lock()
    
    def record_failure(self, max_failures: int = 5, disable_duration_hours: int = 12):
        """Record a failed read attempt"""
        with self._lock:
            current_time = time.time()
            self.failure_count += 1
            self.last_failure_time = current_time
            
            # If we've had enough failures, disable for specified duration
            if self.failure_count >= max_failures:
                self.disabled_until = current_time + (disable_duration_hours * 3600)
                return True  # Indicates this range should be disabled
            return False
    
    def record_success(self):
        """Record a successful read attempt"""
        with self._lock:
            current_time = time.time()
            self.last_success_time = current_time
            # Reset failure count on success
            self.failure_count = 0
            self.disabled_until = 0
    
    def is_disabled(self) -> bool:
        """Check if this register range is currently disabled"""
        with self._lock:
            if self.disabled_until == 0:
                return False
            return time.time() < self.disabled_until
    
    def get_remaining_disable_time(self) -> float:
        """Get remaining time until re-enabled (0 if not disabled)"""
        with self._lock:
            if self.disabled_until == 0:
                return 0
            remaining = self.disabled_until - time.time()
            return max(0, remaining)


class modbus_base(transport_base):


    #this is specifically static
    clients : dict[str, "BaseModbusClient"] = {}
    ''' str is identifier, dict of clients when multiple transports use the same ports '''
    
    # Threading locks for concurrency control
    _clients_lock : threading.Lock = threading.Lock()
    ''' Lock for accessing the shared clients dictionary '''
    _client_locks : dict[str, threading.Lock] = {}
    ''' Port-specific locks to allow concurrent access to different ports '''

    def __init__(self, settings : "SectionProxy", protocolSettings : "protocol_settings" = None):
        super().__init__(settings)

        # Initialize instance-specific variables (not class-level)
        self.modbus_delay_increament : float = 0.05
        ''' delay adjustment every error. todo: add a setting for this '''
        
        self.modbus_delay_setting : float = 0.85
        '''time inbetween requests, unmodified'''
        
        self.modbus_delay : float = 0.85
        '''time inbetween requests'''
        
        self.analyze_protocol_enabled : bool = False
        self.analyze_protocol_save_load : bool = False
        self.first_connect : bool = True
        self._needs_reconnection : bool = False
        
        self.send_holding_register : bool = True
        self.send_input_register : bool = True
        
        # Register failure tracking - make instance-specific
        self.enable_register_failure_tracking: bool = True
        self.max_failures_before_disable: int = 5
        self.disable_duration_hours: int = 12
        
        # Initialize transport-specific lock
        self._transport_lock = threading.Lock()
        
        # Initialize instance-specific register failure tracking
        self.register_failure_trackers: dict[str, RegisterFailureTracker] = {}
        self._failure_tracking_lock = threading.Lock()

        self.analyze_protocol_enabled = settings.getboolean("analyze_protocol", fallback=self.analyze_protocol_enabled)
        self.analyze_protocol_save_load = settings.getboolean("analyze_protocol_save_load", fallback=self.analyze_protocol_save_load)

        # Register failure tracking settings
        self.enable_register_failure_tracking = settings.getboolean("enable_register_failure_tracking", fallback=self.enable_register_failure_tracking)
        self.max_failures_before_disable = settings.getint("max_failures_before_disable", fallback=self.max_failures_before_disable)
        self.disable_duration_hours = settings.getint("disable_duration_hours", fallback=self.disable_duration_hours)

        # get defaults from protocol settings
        if "send_input_register" in self.protocolSettings.settings:
            self.send_input_register = strtobool(self.protocolSettings.settings["send_input_register"])

        if "send_holding_register" in self.protocolSettings.settings:
            self.send_holding_register = strtobool(self.protocolSettings.settings["send_holding_register"])

        if "batch_delay" in self.protocolSettings.settings:
            self.modbus_delay = float(self.protocolSettings.settings["batch_delay"])

        # allow enable/disable of which registers to send
        self.send_holding_register = settings.getboolean("send_holding_register", fallback=self.send_holding_register)
        self.send_input_register = settings.getboolean("send_input_register", fallback=self.send_input_register)
        self.modbus_delay = settings.getfloat(["batch_delay", "modbus_delay"], fallback=self.modbus_delay)
        self.modbus_delay_setting = self.modbus_delay

        # Note: Connection and analyze_protocol will be called after subclass initialization is complete

    def _get_port_identifier(self) -> str:
        """Get a unique identifier for this transport's port"""
        if hasattr(self, 'port'):
            return f"{self.port}_{self.baudrate}"
        elif hasattr(self, 'host') and hasattr(self, 'port'):
            return f"{self.host}_{self.port}"
        else:
            return self.transport_name
    
    def _get_port_lock(self) -> threading.Lock:
        """Get or create a lock for this transport's port"""
        port_id = self._get_port_identifier()
        
        with self._clients_lock:
            if port_id not in self._client_locks:
                self._client_locks[port_id] = threading.Lock()
        
        return self._client_locks[port_id]

    def _get_register_range_key(self, register_range: tuple[int, int], registry_type: Registry_Type) -> str:
        """Generate a unique key for a register range"""
        return f"{registry_type.name}_{register_range[0]}_{register_range[1]}"
    
    def _get_or_create_failure_tracker(self, register_range: tuple[int, int], registry_type: Registry_Type) -> RegisterFailureTracker:
        """Get or create a failure tracker for a register range"""
        key = self._get_register_range_key(register_range, registry_type)
        
        with self._failure_tracking_lock:
            if key not in self.register_failure_trackers:
                self.register_failure_trackers[key] = RegisterFailureTracker(
                    register_range=register_range,
                    registry_type=registry_type
                )
            
            return self.register_failure_trackers[key]
    
    def _record_register_read_success(self, register_range: tuple[int, int], registry_type: Registry_Type):
        """Record a successful register read"""
        if not self.enable_register_failure_tracking:
            return
            
        tracker = self._get_or_create_failure_tracker(register_range, registry_type)
        # Only log if the last failure was after the last success (i.e., this is the first success after a failure)
        should_log_recovery = tracker.last_failure_time > tracker.last_success_time
        tracker.record_success()
        
        if should_log_recovery:
            self._log.info(f"Register range {registry_type.name} {register_range[0]}-{register_range[1]} is working again after previous failures")
    
    def _record_register_read_failure(self, register_range: tuple[int, int], registry_type: Registry_Type) -> bool:
        """Record a failed register read, returns True if range should be disabled"""
        if not self.enable_register_failure_tracking:
            return False
            
        tracker = self._get_or_create_failure_tracker(register_range, registry_type)
        should_disable = tracker.record_failure(self.max_failures_before_disable, self.disable_duration_hours)
        
        if should_disable:
            self._log.warning(f"Register range {registry_type.name} {register_range[0]}-{register_range[1]} disabled for {self.disable_duration_hours} hours after {tracker.failure_count} failures")
        else:
            self._log.warning(f"Register range {registry_type.name} {register_range[0]}-{register_range[1]} failed ({tracker.failure_count}/{self.max_failures_before_disable} attempts)")
        
        return should_disable
    
    def _is_register_range_disabled(self, register_range: tuple[int, int], registry_type: Registry_Type) -> bool:
        """Check if a register range is currently disabled"""
        if not self.enable_register_failure_tracking:
            return False
            
        tracker = self._get_or_create_failure_tracker(register_range, registry_type)
        return tracker.is_disabled()
    
    def _get_disabled_ranges_info(self) -> list[str]:
        """Get information about currently disabled register ranges"""
        disabled_info = []
        current_time = time.time()
        
        with self._failure_tracking_lock:
            for tracker in self.register_failure_trackers.values():
                if tracker.is_disabled():
                    remaining_hours = tracker.get_remaining_disable_time() / 3600
                    disabled_info.append(
                        f"{tracker.registry_type.name} {tracker.register_range[0]}-{tracker.register_range[1]} "
                        f"(disabled for {remaining_hours:.1f}h, {tracker.failure_count} failures)"
                    )
        
        return disabled_info
    
    def get_register_failure_status(self) -> dict:
        """Get comprehensive status of register failure tracking"""
        status = {
            "enabled": self.enable_register_failure_tracking,
            "max_failures_before_disable": self.max_failures_before_disable,
            "disable_duration_hours": self.disable_duration_hours,
            "total_tracked_ranges": 0,
            "disabled_ranges": [],
            "failed_ranges": [],
            "successful_ranges": []
        }
        
        with self._failure_tracking_lock:
            status["total_tracked_ranges"] = len(self.register_failure_trackers)
            
            for tracker in self.register_failure_trackers.values():
                range_info = {
                    "registry_type": tracker.registry_type.name,
                    "range": f"{tracker.register_range[0]}-{tracker.register_range[1]}",
                    "failure_count": tracker.failure_count,
                    "last_failure_time": tracker.last_failure_time,
                    "last_success_time": tracker.last_success_time
                }
                
                if tracker.is_disabled():
                    range_info["disabled_until"] = tracker.disabled_until
                    range_info["remaining_hours"] = tracker.get_remaining_disable_time() / 3600
                    status["disabled_ranges"].append(range_info)
                elif tracker.failure_count > 0:
                    status["failed_ranges"].append(range_info)
                else:
                    status["successful_ranges"].append(range_info)
        
        return status
    
    def reset_register_failure_tracking(self, registry_type: Registry_Type = None, register_range: tuple[int, int] = None):
        """Reset register failure tracking for specific ranges or all ranges"""
        with self._failure_tracking_lock:
            if registry_type is None and register_range is None:
                # Reset all tracking
                self.register_failure_trackers.clear()
                self._log.info("Reset all register failure tracking")
                return
            
            if register_range is not None:
                # Reset specific range
                key = self._get_register_range_key(register_range, registry_type or Registry_Type.INPUT)
                if key in self.register_failure_trackers:
                    del self.register_failure_trackers[key]
                    self._log.info(f"Reset failure tracking for {registry_type.name if registry_type else 'INPUT'} range {register_range[0]}-{register_range[1]}")
            else:
                # Reset all ranges for specific registry type
                keys_to_remove = []
                for key, tracker in self.register_failure_trackers.items():
                    if tracker.registry_type == registry_type:
                        keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del self.register_failure_trackers[key]
                
                self._log.info(f"Reset failure tracking for all {registry_type.name} ranges ({len(keys_to_remove)} ranges)")
    
    def enable_register_range(self, register_range: tuple[int, int], registry_type: Registry_Type):
        """Manually enable a disabled register range"""
        tracker = self._get_or_create_failure_tracker(register_range, registry_type)
        with self._failure_tracking_lock:
            tracker.disabled_until = 0
            tracker.failure_count = 0
        self._log.info(f"Manually enabled register range {registry_type.name} {register_range[0]}-{register_range[1]}")

    def init_after_connect(self):
        # Use transport lock to prevent concurrent access during initialization
        with self._transport_lock:
            #from transport_base settings
            if self.write_enabled:
                self.enable_write()

            #if sn is empty, attempt to autoread it
            if not self.device_serial_number:
                self._log.info(f"Reading serial number for transport {self.transport_name} on port {getattr(self, 'port', 'unknown')}")
                self.device_serial_number = self.read_serial_number()
                self._log.info(f"Transport {self.transport_name} serial number: {self.device_serial_number}")
                self.update_identifier()
            else:
                self._log.debug(f"Transport {self.transport_name} already has serial number: {self.device_serial_number}")

    def connect(self):
        """Connect to the Modbus device"""
        # Add debugging information
        port_info = getattr(self, 'port', 'unknown')
        address_info = getattr(self, 'address', 'unknown')
        self._log.info(f"Connecting to Modbus device: address={address_info}, port={port_info}")
        
        # Handle first connection or reconnection
        if self.first_connect:
            self.first_connect = False
            self.init_after_connect()
        elif not self.connected:
            # Reconnection case - reinitialize after connection is established
            self._log.info(f"Reconnecting transport {self.transport_name}")
            # The actual connection is handled by subclasses (e.g., modbus_rtu)
            # We just need to reinitialize after connection
            self.init_after_connect()
        
        # Reset reconnection flag after successful connection
        if self.connected:
            self._needs_reconnection = False

    def cleanup(self):
        """Clean up transport resources and close connections"""
        with self._transport_lock:
            self._log.info(f"Cleaning up transport {self.transport_name}")
            
            # Close the modbus client connection
            port_identifier = self._get_port_identifier()
            if port_identifier in self.clients:
                try:
                    client = self.clients[port_identifier]
                    if hasattr(client, 'close') and callable(client.close):
                        client.close()
                        self._log.info(f"Closed modbus client for {self.transport_name}")
                except Exception as e:
                    self._log.warning(f"Error closing modbus client for {self.transport_name}: {e}")
                
                # Remove from shared clients dict
                with self._clients_lock:
                    if port_identifier in self.clients:
                        del self.clients[port_identifier]
                        self._log.info(f"Removed client from shared dict for {self.transport_name}")
            
            # Mark as disconnected and reset first_connect for reconnection
            self.connected = False
            self.first_connect = False  # Reset so reconnection works properly
            self._needs_reconnection = True  # Flag that this transport needs reconnection
            self._log.info(f"Transport {self.transport_name} cleanup completed")

    def read_serial_number(self) -> str:
        # First try to read "Serial Number" from input registers (for protocols like EG4 v58)
        self._log.info("Looking for serial_number variable in input registers...")
        serial_number = str(self.read_variable("Serial Number", Registry_Type.INPUT))
        self._log.info("read SN from input registers: " + serial_number)
        if serial_number and serial_number != "None":
            return serial_number

        # Then try holding registers (for other protocols)
        self._log.info("Looking for serial_number variable in holding registers...")
        serial_number = str(self.read_variable("Serial Number", Registry_Type.HOLDING))
        self._log.info("read SN from holding registers: " + serial_number)
        if serial_number and serial_number != "None":
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

        self._log.debug(f"Serial number sn2: {sn2}")
        self._log.debug(f"Serial number sn3: {sn3}")

        if not re.search("[^a-zA-Z0-9_]", sn2) :
            serial_number = sn2

        return serial_number

    def enable_write(self):
        if self.write_enabled and self.write_mode == TransportWriteMode.UNSAFE:
            self._log.warning("enable write - WARNING - UNSAFE MODE - validation SKIPPED")
            return

        self._log.info("Validating Protocol for Writing")
        self.write_enabled = False

        # Add a small delay to ensure device is ready, especially during initialization
        time.sleep(self.modbus_delay * 2)

        try:
            score_percent = self.validate_protocol(Registry_Type.HOLDING)
            if(score_percent > 90):
                self.write_enabled = True
                self._log.warning("enable write - validation passed")
            elif self.write_mode == TransportWriteMode.RELAXED:
                self.write_enabled = True
                self._log.warning("enable write - WARNING - RELAXED MODE")
            else:
                self._log.error("enable write FAILED - WRITE DISABLED")
        except Exception as e:
            self._log.error(f"enable write FAILED due to error: {str(e)}")
            if self.write_mode == TransportWriteMode.RELAXED:
                self.write_enabled = True
                self._log.warning("enable write - WARNING - RELAXED MODE (due to validation error)")
            else:
                self._log.error("enable write FAILED - WRITE DISABLED")



    def write_data(self, data : dict[str, str], from_transport : transport_base) -> None:
        # Use transport lock to prevent concurrent access to this transport instance
        with self._transport_lock:
            if not self.write_enabled:
                return

            registry_map = self.protocolSettings.get_registry_map(Registry_Type.HOLDING)

            for variable_name, value in data.items():
                entry = None
                for e in registry_map:
                    if e.variable_name == variable_name:
                        entry = e
                        break

                if entry:
                    self.write_variable(entry, value, Registry_Type.HOLDING)

            time.sleep(self.modbus_delay) #sleep inbetween requests so modbus can rest

    def read_data(self) -> dict[str, str]:
        # Use transport lock to prevent concurrent access to this transport instance
        with self._transport_lock:
            # Add debugging information
            port_info = getattr(self, 'port', 'unknown')
            address_info = getattr(self, 'address', 'unknown')
            self._log.debug(f"Reading data from {self.transport_name}: address={address_info}, port={port_info}")
            
            info = {}
            #modbus - only read input/holding registries
            for registry_type in (Registry_Type.INPUT, Registry_Type.HOLDING):

                #enable / disable input/holding register
                if registry_type == Registry_Type.INPUT and not self.send_input_register:
                    continue

                if registry_type == Registry_Type.HOLDING and not self.send_holding_register:
                    continue

                #calculate ranges dynamically -- for variable read timing
                ranges = self.protocolSettings.calculate_registry_ranges(self.protocolSettings.registry_map[registry_type],
                                                                         self.protocolSettings.registry_map_size[registry_type],
                                                                         timestamp=self.last_read_time)

                self._log.info(f"Reading {registry_type.name} registers for {self.transport_name}: {len(ranges)} ranges")
                registry = self.read_modbus_registers(ranges=ranges, registry_type=registry_type)
                
                if registry:
                    self._log.info(f"Got registry data for {self.transport_name} {registry_type.name}: {len(registry)} registers")
                else:
                    self._log.warning(f"No registry data returned for {self.transport_name} {registry_type.name}")
                
                new_info = self.protocolSettings.process_registery(registry, self.protocolSettings.get_registry_map(registry_type))

                if False:
                    new_info = {self.__input_register_prefix + key: value for key, value in new_info.items()}

                info.update(new_info)

            if not info:
                self._log.info("Register is Empty; transport busy?")

            # Log disabled ranges status periodically (every 10 minutes)
            if self.enable_register_failure_tracking and hasattr(self, '_last_disabled_status_log') and time.time() - self._last_disabled_status_log > 600:
                disabled_ranges = self._get_disabled_ranges_info()
                if disabled_ranges:
                    self._log.info(f"Currently disabled register ranges: {len(disabled_ranges)}")
                    for range_info in disabled_ranges:
                        self._log.info(f"  - {range_info}")
                self._last_disabled_status_log = time.time()
            elif not hasattr(self, '_last_disabled_status_log'):
                self._last_disabled_status_log = time.time()

            return info

    def validate_protocol(self, protocolSettings : "protocol_settings") -> float:
        score_percent = self.validate_registry(Registry_Type.HOLDING)
        return score_percent


    def validate_registry(self, registry_type : Registry_Type = Registry_Type.INPUT) -> float:
        score : float = 0
        info = {}
        registry_map : list[registry_map_entry] = self.protocolSettings.get_registry_map(registry_type)
        info = self.read_registry(registry_type)

        for value in registry_map:
            if value.variable_name in info:
                evaluate = True

                if value.concatenate and value.register != value.concatenate_registers[0]: #only eval concated values once
                    evaluate = False

                if evaluate:
                    score = score + self.protocolSettings.validate_registry_entry(value, info[value.variable_name])

        maxScore = len(registry_map)
        for entry in registry_map: #adjust max score to exclude disabled registers
            if entry.write_mode == WriteMode.WRITEONLY or entry.write_mode == WriteMode.READDISABLED:
                maxScore -= 1

        percent = score*100/maxScore
        self._log.info("validation score: " + str(score) + " of " + str(maxScore) + " : " + str(round(percent)) + "%")
        return percent

    def analyze_protocol(self, settings_dir : str = "protocols"):
        print("=== PROTOCOL ANALYZER ===")
        protocol_names : list[str] = []
        protocols : dict[str,protocol_settings] = {}

        for file in glob.glob(settings_dir + "/*.json"):
            file = file.lower().replace(settings_dir, "").replace("/", "").replace("\\", "").replace("\\", "").replace(".json", "")
            print(file)
            protocol_names.append(file)

        max_input_register : int = 0
        max_holding_register : int = 0

        for name in protocol_names:
            protocols[name] = protocol_settings(name)

            if protocols[name].registry_map_size[Registry_Type.INPUT] > max_input_register:
                max_input_register = protocols[name].registry_map_size[Registry_Type.INPUT]

            if protocols[name].registry_map_size[Registry_Type.HOLDING] > max_holding_register:
                max_holding_register = protocols[name].registry_map_size[Registry_Type.HOLDING]

        print("max input register: ", max_input_register)
        print("max holding register: ", max_holding_register)

        self.modbus_delay = self.modbus_delay #decrease delay because can probably get away with it due to lots of small reads
        print("read INPUT Registers: ")

        input_save_path = "input_registry.json"
        holding_save_path = "holding_registry.json"

        #load previous scan if enabled and exists
        if self.analyze_protocol_save_load and os.path.exists(input_save_path) and os.path.exists(holding_save_path):
            with open(input_save_path, "r") as file:
                input_registry = json.load(file)

            with open(holding_save_path, "r") as file:
                holding_registry = json.load(file)

            # Convert keys to integers
            input_registry = {int(key): value for key, value in input_registry.items()}
            holding_registry = {int(key): value for key, value in holding_registry.items()}
        else:
            #perform registry scan
            ##batch_size = 1, read registers one by one; if out of bound. it just returns error
            input_registry = self.read_modbus_registers(start=0, end=max_input_register, registry_type=Registry_Type.INPUT)
            holding_registry = self.read_modbus_registers(start=0, end=max_holding_register, registry_type=Registry_Type.HOLDING)

            if self.analyze_protocol_save_load: #save results if enabled
                with open(input_save_path, "w") as file:
                    json.dump(input_registry, file)

                with open(holding_save_path, "w") as file:
                    json.dump(holding_registry, file)

        #print results for debug
        self._log.debug("=== START INPUT REGISTER ===")
        if input_registry:
            self._log.debug([(key, value) for key, value in input_registry.items()])
        self._log.debug("=== END INPUT REGISTER ===")
        self._log.debug("=== START HOLDING REGISTER ===")
        if holding_registry:
            self._log.debug([(key, value) for key, value in holding_registry.items()])
        self._log.debug("=== END HOLDING REGISTER ===")

        #very well possible the registers will be incomplete due to different hardware sizes
        #so dont assume they are set / complete
        #we'll see about the behaviour. if it glitches, this could be a way to determine protocol.


        input_register_score : dict[str, int] = {}
        holding_register_score : dict[str, int] = {}

        input_valid_count : dict[str, int] = {}
        holding_valid_count  : dict[str, int] = {}

        def evaluate_score(entry : registry_map_entry, val):
            score = 0
            if entry.data_type == Data_Type.ASCII:
                if val and not re.match("[^a-zA-Z0-9_-]", val): #validate ascii
                    mod = 1
                    if entry.concatenate:
                        mod = len(entry.concatenate_registers)

                    if entry.value_regex: #regex validation
                        if re.match(entry.value_regex, val):
                            mod = mod * 2
                        else:
                            mod = mod * -2 #regex validation failed, double damage!

                    score = score + (2 * mod) #double points for ascii
                pass
            else: #default type
                if isinstance(val, str):
                    #likely to be a code
                    score = score + 2
                elif val != 0:
                    if val >= entry.value_min and val <= entry.value_max:
                        score = score + 1

                        if entry.value_max != 65535: #double points for non-default range
                            score = score + 1

            return score



        for name, protocol in protocols.items():
            input_register_score[name] = 0
            holding_register_score[name] = 0
            #very rough percentage. tood calc max possible score.
            input_valid_count[name] = 0
            holding_valid_count[name] = 0

            #process registry based on protocol
            input_info = protocol.process_registery(input_registry, protocol.registry_map[Registry_Type.INPUT])
            holding_info = protocol.process_registery(input_registry, protocol.registry_map[Registry_Type.HOLDING])


            for entry in protocol.registry_map[Registry_Type.INPUT]:
                if entry.variable_name in input_info:
                    val = input_info[entry.variable_name]
                    score = evaluate_score(entry, val)
                    if score > 0:
                        input_valid_count[name] = input_valid_count[name] + 1

                    input_register_score[name] = input_register_score[name] + score


            for entry in protocol.registry_map[Registry_Type.HOLDING]:
                if entry.variable_name in holding_info:
                    val = holding_info[entry.variable_name]
                    score = evaluate_score(entry, val)

                    if score > 0:
                        holding_valid_count[name] = holding_valid_count[name] + 1

                    holding_register_score[name] = holding_register_score[name] + score


        protocol_scores: dict[str, int] = {}
        #combine scores
        for name, protocol in protocols.items():
            protocol_scores[name] = input_register_score[name] + holding_register_score[name]

        #print scores
        for name in sorted(protocol_scores, key=protocol_scores.get, reverse=True):
            self._log.debug("=== "+str(name)+" - "+str(protocol_scores[name])+" ===")
            self._log.debug("input register score: " + str(input_register_score[name]) + "; valid registers: "+str(input_valid_count[name])+" of " + str(len(protocols[name].get_registry_map(Registry_Type.INPUT))))
            self._log.debug("holding register score : " + str(holding_register_score[name]) + "; valid registers: "+str(holding_valid_count[name])+" of " + str(len(protocols[name].get_registry_map(Registry_Type.HOLDING))))


    def write_variable(self, entry : registry_map_entry, value : str, registry_type : Registry_Type = Registry_Type.HOLDING):
        """ writes a value to a ModBus register; todo: registry_type to handle other write functions"""

        value = value.strip()

        temp_map = [entry]
        ranges = self.protocolSettings.calculate_registry_ranges(temp_map, self.protocolSettings.registry_map_size[registry_type], init=True) #init=True to bypass timechecks
        registry = self.read_modbus_registers( ranges=ranges, registry_type=registry_type)
        info = self.protocolSettings.process_registery(registry, temp_map)
        #read current value
        #current_registers = self.read_modbus_registers(start=entry.register, end=entry.register, registry_type=registry_type)
        #current_value = current_registers[entry.register]
        current_value = info[entry.variable_name]

        if not self.write_mode == TransportWriteMode.UNSAFE:
            if not self.protocolSettings.validate_registry_entry(entry, current_value):
                return self._log.error(f"WRITE_ERROR: Invalid value in register '{current_value}'. Unsafe to write")
                #raise ValueError(err)

            if not (entry.data_type == Data_Type._16BIT_FLAGS or entry.data_type == Data_Type._8BIT_FLAGS or entry.data_type == Data_Type._32BIT_FLAGS): #skip validation for write; validate further down
                if not self.protocolSettings.validate_registry_entry(entry, value):
                    return self._log.error(f"WRITE_ERROR: Invalid new value, '{value}'. Unsafe to write")

        #handle codes
        if entry.variable_name+"_codes" in self.protocolSettings.codes:
            codes = self.protocolSettings.codes[entry.variable_name+"_codes"]
            for key, val in codes.items():
                if val == value: #convert "string" to key value
                    value = key
                    break

        #apply unit_mod before writing.
        if entry.unit_mod != 1:
            value = int(float(value) / entry.unit_mod) # say unitmod is 0.1. 105*0.1 = 10.5. 10.5 / 0.1 = 105.

        #results[entry.variable_name]
        ushortValue : int = None #ushort
        if entry.data_type == Data_Type.USHORT:
            ushortValue = int(value)
            if ushortValue < 0 or ushortValue > 65535:
                 raise ValueError("Invalid value")
        elif entry.data_type.value > 200 or entry.data_type == Data_Type.BYTE: #bit types
            bit_size = Data_Type.getSize(entry.data_type)

            new_val = int(value)
            if 0 > new_val or new_val > (2**bit_size -1): # Calculate max value for n bits: 2^n - 1
                return self._log.error(f"WRITE_ERROR: Invalid new value, '{value}'. Exceeds value range. Unsafe to write")

            bit_index = entry.register_bit
            bit_mask = ((1 << bit_size) - 1) << bit_index  # Create a mask for extracting X bits starting from bit_index
            clear_mask = ~(bit_mask)  # Mask for clearing the bits to be updated

            # Clear the bits to be updated in the current_value
            ushortValue = registry[entry.register] & clear_mask

            # Set the bits according to the new_value at the specified bit position
            ushortValue |= (new_val << bit_index) & bit_mask

            #bit_size = Data_Type.getSize(entry.data_type)
            bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
            bit_index = entry.register_bit
            check_value = (ushortValue >> bit_index) & bit_mask


            if check_value != new_val:
                raise ValueError("something went wrong bitwise")
        elif entry.data_type == Data_Type._16BIT_FLAGS or entry.data_type == Data_Type._8BIT_FLAGS or entry.data_type == Data_Type._32BIT_FLAGS:
            #16 bit flags
            flag_size : int = Data_Type.getSize(entry.data_type)

            if re.match(rf"^[0-1]{{{flag_size}}}$", value): #bitflag string
                #is string of 01... s
                # Convert binary string to an integer
                value = int(value[::-1], 2) #reverse string

                # Ensure it fits within ushort range (0-65535)
                if value > 65535:
                    return self._log.error(f"WRITE_ERROR: '{value}' Exceeds 65535. Unsafe to write")
            else:
                return self._log.error(f"WRITE_ERROR: Invalid new value for bitflags, '{value}'. Unsafe to write")

            #apply bitmasks
            bit_index = entry.register_bit
            bit_mask = ((1 << flag_size) - 1) << bit_index  # Create a mask for extracting X bits starting from bit_index
            clear_mask = ~(bit_mask)  # Mask for clearing the bits to be updated

            # Clear the bits to be updated in the current_value
            ushortValue = registry[entry.register] & clear_mask

            # Set the bits according to the new_value at the specified bit position
            ushortValue |= (value << bit_index) & bit_mask

        else:
            raise TypeError("Unsupported data type")

        if ushortValue is None:
            raise ValueError("Invalid value - None")

        self._log.info(f"WRITE: {current_value} => {value} ( {registry[entry.register]} => {ushortValue} ) to Register {entry.register}")
        self.write_register(entry.register, ushortValue)
        #entry.next_read_timestamp = 0 #ensure is read next interval


    def read_variable(self, variable_name : str, registry_type : Registry_Type, entry : registry_map_entry = None):
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
            start : int = 0
            end : int = 0
            if not entry.concatenate:
                start = entry.register
                end = entry.register
            else:
                start = entry.register
                end = max(entry.concatenate_registers)

            registers = self.read_modbus_registers(start=start, end=end, registry_type=registry_type)
            results = self.protocolSettings.process_registery(registers, registry_map)
            return results[entry.variable_name]

    def read_modbus_registers(self, ranges : list[tuple] = None, start : int = 0, end : int = None, batch_size : int = None, registry_type : Registry_Type = Registry_Type.INPUT ) -> dict:
        ''' maybe move this to transport_base ?'''

        # Get batch_size from protocol settings if not provided
        if batch_size is None:
            if hasattr(self, 'protocolSettings') and self.protocolSettings:
                batch_size = self.protocolSettings.settings.get("batch_size", 45)
                try:
                    batch_size = int(batch_size)
                except (ValueError, TypeError):
                    batch_size = 45
            else:
                batch_size = 45

        if not ranges: #ranges is empty, use min max
            if start == 0 and end is None:
                return {} #empty

            end = end + 1
            ranges = []
            start = start - batch_size
            while( start := start + batch_size ) < end:
                count = batch_size
                if start + batch_size > end:
                    count = end - start + 1
                ranges.append((start, count)) ##APPEND TUPLE

        registry : dict[int,] = {}
        retries = 7
        retry = 0
        total_retries = 0

        index = -1
        while (index := index + 1) < len(ranges) :
            range = ranges[index]
            
            # Check if this register range is currently disabled
            if self._is_register_range_disabled(range, registry_type):
                remaining_hours = self._get_or_create_failure_tracker(range, registry_type).get_remaining_disable_time() / 3600
                self._log.info(f"Skipping disabled register range {registry_type.name} {range[0]}-{range[0]+range[1]-1} (disabled for {remaining_hours:.1f}h)")
                continue

            self._log.info("get registers ("+str(index)+"): " +str(registry_type)+ " - " + str(range[0]) + " to " + str(range[0]+range[1]-1) + " ("+str(range[1])+")")
            time.sleep(self.modbus_delay) #sleep for 1ms to give bus a rest #manual recommends 1s between commands

            isError = False
            register = None  # Initialize register variable
            try:
                register = self.read_registers(range[0], range[1], registry_type=registry_type)

            except ModbusIOException as e:
                self._log.error(f"ModbusIOException for {self.transport_name}: " + str(e))
                # In pymodbus 3.7+, ModbusIOException doesn't have error_code attribute
                # Treat all ModbusIOException as retryable errors
                isError = True


            if register is None or isinstance(register, bytes) or (hasattr(register, 'isError') and register.isError()) or isError: #sometimes weird errors are handled incorrectly and response is a ascii error string
                if register is None:
                    self._log.error("No response received from modbus device")
                elif isinstance(register, bytes):
                    self._log.error(register.decode("utf-8"))
                else:
                    # Enhanced error logging with Modbus exception interpretation
                    error_msg = str(register)
                    
                    # Check if this is an ExceptionResponse and extract the exception code
                    if hasattr(register, 'function_code') and hasattr(register, 'exception_code'):
                        exception_code = register.function_code | 0x80  # Convert to exception response code
                        interpreted_error = interpret_modbus_exception_code(exception_code)
                        self._log.error(f"{error_msg} - {interpreted_error}")
                    else:
                        self._log.error(error_msg)
                
                # Record the failure for this register range
                should_disable = self._record_register_read_failure(range, registry_type)
                
                self.modbus_delay += self.modbus_delay_increament #increase delay, error is likely due to modbus being busy

                if self.modbus_delay > 60: #max delay. 60 seconds between requests should be way over kill if it happens
                    self.modbus_delay = 60

                if retry > retries: #instead of none, attempt to continue to read. but with no retires.
                    continue
                else:
                    #undo step in loop and retry read
                    retry = retry + 1
                    total_retries = total_retries + 1
                    self._log.warning("Retry("+str(retry)+" - ("+str(total_retries)+")) range("+str(index)+")")
                    index = index - 1
                    continue
            elif self.modbus_delay > self.modbus_delay_setting: #no error, decrease delay
                self.modbus_delay -= self.modbus_delay_increament
                if self.modbus_delay < self.modbus_delay_setting:
                    self.modbus_delay = self.modbus_delay_setting

            # Record successful read for this register range
            self._record_register_read_success(range, registry_type)

            retry -= 1
            if retry < 0:
                retry = 0

            # Only process registers if we have a valid response
            if register is not None and hasattr(register, 'registers') and register.registers is not None:
                #combine registers into "registry"
                i = -1
                while(i := i + 1 ) < range[1]:
                    #print(str(i) + " => " + str(i+range[0]))
                    registry[i+range[0]] = register.registers[i]

        return registry

    def read_registry(self, registry_type : Registry_Type = Registry_Type.INPUT) -> dict[str,str]:
        map = self.protocolSettings.get_registry_map(registry_type)
        if not map:
            return {}

        registry = self.read_modbus_registers(self.protocolSettings.get_registry_ranges(registry_type), registry_type=registry_type)
        info = self.protocolSettings.process_registery(registry, map)
        return info
