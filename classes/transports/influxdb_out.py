import sys
import os
import json
import pickle
from configparser import SectionProxy
from typing import TextIO
import time
import logging
import threading

from defs.common import strtobool

from ..protocol_settings import Registry_Type, WriteMode, registry_map_entry, Data_Type
from .transport_base import transport_base


class influxdb_out(transport_base):
    ''' InfluxDB v1 output transport that writes data to an InfluxDB server '''
    host: str = "localhost"
    port: int = 8086
    database: str = "solar"
    username: str = ""
    password: str = ""
    measurement: str = "device_data"
    include_timestamp: bool = True
    include_device_info: bool = True
    batch_size: int = 100
    batch_timeout: float = 10.0
    force_float: bool = True  # Force all numeric fields to be floats to avoid InfluxDB type conflicts
    
    # Connection monitoring settings
    reconnect_attempts: int = 5
    reconnect_delay: float = 5.0
    connection_timeout: int = 10
    
    # Exponential backoff settings
    use_exponential_backoff: bool = True
    max_reconnect_delay: float = 300.0  # 5 minutes max delay
    
    # Persistent storage settings
    enable_persistent_storage: bool = True
    persistent_storage_path: str = "influxdb_backlog"
    max_backlog_size: int = 10000  # Maximum number of points to store
    max_backlog_age: int = 86400  # 24 hours in seconds
    
    # Periodic reconnection settings
    periodic_reconnect_interval: float = 14400.0  # 4 hours in seconds
    
    client = None
    last_batch_time = 0
    last_connection_check = 0
    connection_check_interval = 300  # Check connection every 300 seconds
    
    # Periodic reconnection settings
    last_periodic_reconnect_attempt = 0
    
    # Persistent storage
    backlog_file = None
    backlog_points = []

    def __init__(self, settings: SectionProxy):
        self.host = settings.get("host", fallback=self.host)
        self.port = settings.getint("port", fallback=self.port)
        self.database = settings.get("database", fallback=self.database)
        self.username = settings.get("username", fallback=self.username)
        self.password = settings.get("password", fallback=self.password)
        self.measurement = settings.get("measurement", fallback=self.measurement)
        self.include_timestamp = strtobool(settings.get("include_timestamp", fallback=self.include_timestamp))
        self.include_device_info = strtobool(settings.get("include_device_info", fallback=self.include_device_info))
        self.batch_size = settings.getint("batch_size", fallback=self.batch_size)
        self.batch_timeout = settings.getfloat("batch_timeout", fallback=self.batch_timeout)
        self.force_float = strtobool(settings.get("force_float", fallback=self.force_float))
        
        # Connection monitoring settings
        self.reconnect_attempts = settings.getint("reconnect_attempts", fallback=self.reconnect_attempts)
        self.reconnect_delay = settings.getfloat("reconnect_delay", fallback=self.reconnect_delay)
        self.connection_timeout = settings.getint("connection_timeout", fallback=self.connection_timeout)
        
        # Exponential backoff settings
        self.use_exponential_backoff = strtobool(settings.get("use_exponential_backoff", fallback=self.use_exponential_backoff))
        self.max_reconnect_delay = settings.getfloat("max_reconnect_delay", fallback=self.max_reconnect_delay)
        
        # Persistent storage settings
        self.enable_persistent_storage = strtobool(settings.get("enable_persistent_storage", fallback=self.enable_persistent_storage))
        self.persistent_storage_path = settings.get("persistent_storage_path", fallback=self.persistent_storage_path)
        self.max_backlog_size = settings.getint("max_backlog_size", fallback=self.max_backlog_size)
        self.max_backlog_age = settings.getint("max_backlog_age", fallback=self.max_backlog_age)
        
        # Periodic reconnection settings
        self.periodic_reconnect_interval = settings.getfloat("periodic_reconnect_interval", fallback=self.periodic_reconnect_interval)
        
        self.write_enabled = True  # InfluxDB output is always write-enabled
        super().__init__(settings)
        
        # Initialize instance variables for thread safety
        self.batch_points = []
        self._batch_lock = threading.Lock()
        
        # Initialize persistent storage
        if self.enable_persistent_storage:
            self._init_persistent_storage()

    def _init_persistent_storage(self):
        """Initialize persistent storage for data backlog"""
        try:
            # Create storage directory if it doesn't exist
            if not os.path.exists(self.persistent_storage_path):
                os.makedirs(self.persistent_storage_path)
            
            # Create backlog file path
            self.backlog_file = os.path.join(
                self.persistent_storage_path, 
                f"influxdb_backlog_{self.transport_name}.pkl"
            )
            
            # Load existing backlog
            self._load_backlog()
            
            self._log.info(f"Persistent storage initialized: {self.backlog_file}")
            self._log.info(f"Loaded {len(self.backlog_points)} points from backlog")
            
        except Exception as e:
            self._log.error(f"Failed to initialize persistent storage: {e}")
            self.enable_persistent_storage = False

    def _load_backlog(self):
        """Load backlog points from persistent storage"""
        if not self.backlog_file or not os.path.exists(self.backlog_file):
            self.backlog_points = []
            return
        
        try:
            with open(self.backlog_file, 'rb') as f:
                self.backlog_points = pickle.load(f)
            
            # Clean old points based on age
            current_time = time.time()
            original_count = len(self.backlog_points)
            self.backlog_points = [
                point for point in self.backlog_points 
                if current_time - point.get('_backlog_time', 0) < self.max_backlog_age
            ]
            
            if len(self.backlog_points) < original_count:
                self._log.info(f"Cleaned {original_count - len(self.backlog_points)} old points from backlog")
                self._save_backlog()
                
        except Exception as e:
            self._log.error(f"Failed to load backlog: {e}")
            self.backlog_points = []

    def _save_backlog(self):
        """Save backlog points to persistent storage"""
        if not self.backlog_file or not self.enable_persistent_storage:
            return
        
        try:
            with open(self.backlog_file, 'wb') as f:
                pickle.dump(self.backlog_points, f)
        except Exception as e:
            self._log.error(f"Failed to save backlog: {e}")

    def _add_to_backlog(self, point):
        """Add a point to the backlog"""
        if not self.enable_persistent_storage:
            return
        
        # Add timestamp for age tracking
        point['_backlog_time'] = time.time()
        
        self.backlog_points.append(point)
        
        # Limit backlog size
        if len(self.backlog_points) > self.max_backlog_size:
            removed = self.backlog_points.pop(0)  # Remove oldest point
            self._log.warning(f"Backlog full, removed oldest point: {removed.get('measurement', 'unknown')}")
        
        self._save_backlog()
        # self._log.debug(f"Added point to backlog. Backlog size: {len(self.backlog_points)}")  # Suppressed debug message

    def _flush_backlog(self):
        """Flush backlog points to InfluxDB"""
        if not self.backlog_points or not self.connected:
            return
        
        self._log.info(f"Flushing {len(self.backlog_points)} backlog points to InfluxDB")
        
        try:
            # Remove internal timestamp before sending to InfluxDB
            points_to_send = []
            for point in self.backlog_points:
                point_copy = point.copy()
                point_copy.pop('_backlog_time', None)  # Remove internal timestamp
                points_to_send.append(point_copy)
            
            self.client.write_points(points_to_send)
            self._log.info(f"Successfully wrote {len(points_to_send)} backlog points to InfluxDB")
            
            # Clear backlog after successful write
            self.backlog_points = []
            self._save_backlog()
            
        except Exception as e:
            self._log.error(f"Failed to flush backlog to InfluxDB: {e}")
            # Don't clear backlog on failure - will retry later

    def connect(self):
        """Initialize the InfluxDB client connection"""
        self._log.info("influxdb_out connect")
        
        try:
            from influxdb import InfluxDBClient
            
            # Create InfluxDB client with timeout settings
            self.client = InfluxDBClient(
                host=self.host,
                port=self.port,
                username=self.username if self.username else None,
                password=self.password if self.password else None,
                database=self.database,
                timeout=self.connection_timeout
            )
            
            # Test connection
            self.client.ping()
            
            # Create database if it doesn't exist
            databases = self.client.get_list_database()
            if not any(db['name'] == self.database for db in databases):
                self._log.info(f"Creating database: {self.database}")
                self.client.create_database(self.database)
            
            self.connected = True
            self.last_connection_check = time.time()
            self.last_periodic_reconnect_attempt = time.time()
            self._log.info(f"Connected to InfluxDB at {self.host}:{self.port}")
            
            # Flush any backlog after successful connection
            if self.enable_persistent_storage:
                self._flush_backlog()
            
        except ImportError:
            self._log.error("InfluxDB client not installed. Please install with: pip install influxdb")
            self.connected = False
        except Exception as e:
            self._log.error(f"Failed to connect to InfluxDB: {e}")
            self.connected = False

    def _check_connection(self):
        """Check if the connection is still alive and reconnect if necessary"""
        current_time = time.time()
        
        # Check for periodic reconnection (even if connected)
        if (self.periodic_reconnect_interval > 0 and 
            current_time - self.last_periodic_reconnect_attempt >= self.periodic_reconnect_interval):
            
            self.last_periodic_reconnect_attempt = current_time
            self._log.info(f"Periodic reconnection check (every {self.periodic_reconnect_interval} seconds)")
            
            # Force a reconnection attempt to refresh the connection
            if self.connected and self.client:
                try:
                    # Test current connection
                    self.client.ping()
                    # self._log.debug("Periodic connection check: connection is healthy")  # Suppressed debug message
                except Exception as e:
                    self._log.warning(f"Periodic connection check failed: {e}")
                    return self._attempt_reconnect()
            else:
                # Not connected, attempt reconnection
                return self._attempt_reconnect()
        
        # Only check connection periodically to avoid excessive ping calls
        if current_time - self.last_connection_check < self.connection_check_interval:
            return self.connected
        
        self.last_connection_check = current_time
        
        if not self.connected or not self.client:
            return self._attempt_reconnect()
        
        try:
            # Test connection with ping
            self.client.ping()
            return True
        except Exception as e:
            self._log.warning(f"Connection check failed: {e}")
            return self._attempt_reconnect()

    def _attempt_reconnect(self):
        """Attempt to reconnect to InfluxDB with exponential backoff"""
        self._log.info(f"Attempting to reconnect to InfluxDB at {self.host}:{self.port}")
        
        for attempt in range(self.reconnect_attempts):
            try:
                self._log.info(f"Reconnection attempt {attempt + 1}/{self.reconnect_attempts}")
                
                # Close existing client if it exists
                if self.client:
                    try:
                        self.client.close()
                    except Exception:
                        pass
                
                # Create new client
                from influxdb import InfluxDBClient
                self.client = InfluxDBClient(
                    host=self.host,
                    port=self.port,
                    username=self.username if self.username else None,
                    password=self.password if self.password else None,
                    database=self.database,
                    timeout=self.connection_timeout
                )
                
                # Test connection
                self.client.ping()
                
                self.connected = True
                self.last_periodic_reconnect_attempt = time.time()
                self._log.info(f"Successfully reconnected to InfluxDB")
                
                # Flush any backlog after successful reconnection
                if self.enable_persistent_storage:
                    self._flush_backlog()
                
                return True
                
            except Exception as e:
                self._log.warning(f"Reconnection attempt {attempt + 1} failed: {e}")
                if attempt < self.reconnect_attempts - 1:
                    # Calculate delay with exponential backoff
                    if self.use_exponential_backoff:
                        delay = min(self.reconnect_delay * (2 ** attempt), self.max_reconnect_delay)
                        self._log.info(f"Waiting {delay:.1f} seconds before next attempt (exponential backoff)")
                    else:
                        delay = self.reconnect_delay
                        self._log.info(f"Waiting {delay:.1f} seconds before next attempt")
                    
                    time.sleep(delay)
        
        self._log.error(f"Failed to reconnect after {self.reconnect_attempts} attempts")
        self.connected = False
        return False

    def trigger_periodic_reconnect(self):
        """Manually trigger a periodic reconnection check"""
        self.last_periodic_reconnect_attempt = 0  # Reset timer to force immediate check
        return self._check_connection()

    def write_data(self, data: dict[str, str], from_transport: transport_base):
        # Promote LCDMachineModelCode to device_model if present and meaningful
        if "LCDMachineModelCode" in data and data["LCDMachineModelCode"] and data["LCDMachineModelCode"] != "hotnoob":
            from_transport.device_model = data["LCDMachineModelCode"]
        if not self.write_enabled:
            return

        # Check connection status before processing data
        if not self._check_connection():
            self._log.warning("Not connected to InfluxDB, storing data in backlog")
            # Store data in backlog instead of skipping
            self._process_and_store_data(data, from_transport)
            return

        # self._log.debug(f"write data from [{from_transport.transport_name}] to influxdb_out transport")  # Suppressed debug message
        # self._log.debug(f"Data: {data}")  # Suppressed debug message

        # Process and write data
        self._process_and_write_data(data, from_transport)

    def _process_and_store_data(self, data: dict[str, str], from_transport: transport_base):
        # Promote LCDMachineModelCode to device_model if present and meaningful
        if "LCDMachineModelCode" in data and data["LCDMachineModelCode"] and data["LCDMachineModelCode"] != "hotnoob":
            from_transport.device_model = data["LCDMachineModelCode"]
        if not self.enable_persistent_storage:
            self._log.warning("Persistent storage disabled, data will be lost")
            return
        
        # Create InfluxDB point
        point = self._create_influxdb_point(data, from_transport)
        
        # Add to backlog
        self._add_to_backlog(point)
        
        # Also add to current batch for immediate flush when reconnected
        should_flush = False
        with self._batch_lock:
            self.batch_points.append(point)
            
            current_time = time.time()
            if (len(self.batch_points) >= self.batch_size or 
                (current_time - self.last_batch_time) >= self.batch_timeout):
                # self._log.debug(f"Flushing batch to backlog: size={len(self.batch_points)}")  # Suppressed debug message
                should_flush = True
        
        # Flush outside the lock to avoid deadlock
        if should_flush:
            self._flush_batch()

    def _process_and_write_data(self, data: dict[str, str], from_transport: transport_base):
        # Promote LCDMachineModelCode to device_model if present and meaningful
        if "LCDMachineModelCode" in data and data["LCDMachineModelCode"] and data["LCDMachineModelCode"] != "hotnoob":
            from_transport.device_model = data["LCDMachineModelCode"]
        # Prepare tags for InfluxDB
        tags = {}
        
        # Add device information as tags if enabled
        if self.include_device_info:
            tags.update({
                "device_identifier": from_transport.device_identifier,
                "device_name": from_transport.device_name,
                "device_manufacturer": from_transport.device_manufacturer,
                "device_model": from_transport.device_model,
                "device_serial_number": from_transport.device_serial_number,
                "transport": from_transport.transport_name
            })
            self._log.debug(f"Tags: {tags}")
        
        # Prepare fields (the actual data values)
        fields = {}
        for key, value in data.items():
            should_force_float = False
            unit_mod_found = None
            is_enum = False
            is_ascii = False
            entry = None
            if hasattr(from_transport, 'protocolSettings') and from_transport.protocolSettings:
                for registry_type in [Registry_Type.INPUT, Registry_Type.HOLDING]:
                    registry_map = from_transport.protocolSettings.get_registry_map(registry_type)
                    for e in registry_map:
                        if e.variable_name.lower() == key.lower():
                            entry = e
                            unit_mod_found = e.unit_mod
                            if e.unit_mod != 1.0:
                                should_force_float = True
                            if getattr(e, 'has_enum_mapping', False):
                                is_enum = True
                            if getattr(e, 'data_type', None) == Data_Type.ASCII:
                                is_ascii = True
                            break
                    if should_force_float or is_enum or is_ascii:
                        break
            if is_enum or is_ascii:
                fields[key] = str(value)
                continue
            try:
                float_val = float(value)
                if self.force_float:
                    fields[key] = float_val
                else:
                    if float_val.is_integer():
                        fields[key] = int(float_val)
                    else:
                        fields[key] = float_val
            except (ValueError, TypeError):
                fields[key] = str(value)
                self._log.debug(f"Field {key}: {value} -> string (conversion failed)")
        
        # Create InfluxDB point
        point = self._create_influxdb_point(data, from_transport)
        
        # Add to batch with thread safety
        should_flush = False
        with self._batch_lock:
            self.batch_points.append(point)
            # self._log.debug(f"Added point to batch. Batch size: {len(self.batch_points)}")  # Suppressed debug message
            
            # Check if we should flush the batch
            current_time = time.time()
            if (len(self.batch_points) >= self.batch_size or 
                (current_time - self.last_batch_time) >= self.batch_timeout):
                # self._log.debug(f"Flushing batch: size={len(self.batch_points)}, timeout={current_time - self.last_batch_time:.1f}s")  # Suppressed debug message
                should_flush = True
        
        # Flush outside the lock to avoid deadlock
        if should_flush:
            self._flush_batch()

    def _create_influxdb_point(self, data: dict[str, str], from_transport: transport_base):
        """Create an InfluxDB point from data"""
        # Prepare tags for InfluxDB
        tags = {}
        
        # Add device information as tags if enabled
        if self.include_device_info:
            tags.update({
                "device_identifier": from_transport.device_identifier,
                "device_name": from_transport.device_name,
                "device_manufacturer": from_transport.device_manufacturer,
                "device_model": from_transport.device_model,
                "device_serial_number": from_transport.device_serial_number,
                "transport": from_transport.transport_name
            })
        
        # Prepare fields (the actual data values)
        fields = {}
        for key, value in data.items():
            should_force_float = False
            unit_mod_found = None
            is_enum = False
            is_ascii = False
            entry = None
            if hasattr(from_transport, 'protocolSettings') and from_transport.protocolSettings:
                for registry_type in [Registry_Type.INPUT, Registry_Type.HOLDING]:
                    registry_map = from_transport.protocolSettings.get_registry_map(registry_type)
                    for e in registry_map:
                        if e.variable_name.lower() == key.lower():
                            entry = e
                            unit_mod_found = e.unit_mod
                            if e.unit_mod != 1.0:
                                should_force_float = True
                            if getattr(e, 'has_enum_mapping', False):
                                is_enum = True
                            if getattr(e, 'data_type', None) == Data_Type.ASCII:
                                is_ascii = True
                            break
                    if should_force_float or is_enum or is_ascii:
                        break
            if is_enum or is_ascii:
                fields[key] = str(value)
                continue
            try:
                float_val = float(value)
                if self.force_float:
                    fields[key] = float_val
                else:
                    if float_val.is_integer():
                        fields[key] = int(float_val)
                    else:
                        fields[key] = float_val
            except (ValueError, TypeError):
                fields[key] = str(value)
                self._log.debug(f"Field {key}: {value} -> string (conversion failed)")
        
        # Create InfluxDB point
        point = {
            "measurement": self.measurement,
            "tags": tags,
            "fields": fields
        }
        
        # Add timestamp if enabled
        if self.include_timestamp:
            point["time"] = int(time.time() * 1e9)  # Convert to nanoseconds
        
        return point

    def _flush_batch(self):
        """Flush the batch of points to InfluxDB"""
        with self._batch_lock:
            if not self.batch_points:
                return
                
            # Get a copy of the batch points and clear the list
            points_to_write = self.batch_points.copy()
            self.batch_points = []
            
        # Check connection before attempting to write
        if not self._check_connection():
            self._log.warning("Not connected to InfluxDB, storing batch in backlog")
            # Store all points in backlog
            for point in points_to_write:
                self._add_to_backlog(point)
            return
            
        try:
            self.client.write_points(points_to_write)
            
            # Log serial numbers and sample values if debug level is enabled
            if self._log.isEnabledFor(logging.DEBUG):
                serial_numbers = []
                sample_values = []
                for point in points_to_write:
                    # Get serial number
                    if 'tags' in point and 'device_serial_number' in point['tags']:
                        serial_numbers.append(point['tags']['device_serial_number'])
                    else:
                        serial_numbers.append('None')
                    
                    # Get sample field values
                    if 'fields' in point:
                        fields = point['fields']
                        sample_data = {}
                        for field_name in ['vacr', 'soc', 'fwcode', 'vbat', 'pinv']:
                            if field_name in fields:
                                sample_data[field_name] = fields[field_name]
                        if sample_data:
                            sample_values.append(sample_data)
                        else:
                            sample_values.append('No sample fields found')
                    else:
                        sample_values.append('No fields found')
                
                serial_list = ', '.join(serial_numbers)
                self._log.info(f"Wrote {len(points_to_write)} points to InfluxDB (serial numbers: {serial_list})")
                
                # Log sample values for each point
                for i, (serial, samples) in enumerate(zip(serial_numbers, sample_values)):
                    if isinstance(samples, dict):
                        sample_str = ', '.join([f"{k}={v}" for k, v in samples.items()])
                        self._log.debug(f"  Point {i+1} ({serial}): {sample_str}")
                    else:
                        self._log.debug(f"  Point {i+1} ({serial}): {samples}")
            else:
                self._log.info(f"Wrote {len(points_to_write)} points to InfluxDB")
            
            self.last_batch_time = time.time()
        except Exception as e:
            self._log.error(f"Failed to write batch to InfluxDB: {e}")
            # Don't immediately mark as disconnected, try to reconnect first
            if self._attempt_reconnect():
                # If reconnection successful, try to write again
                try:
                    self.client.write_points(points_to_write)
                    
                    # Log serial numbers and sample values if debug level is enabled
                    if self._log.isEnabledFor(logging.DEBUG):
                        serial_numbers = []
                        sample_values = []
                        for point in points_to_write:
                            # Get serial number
                            if 'tags' in point and 'device_serial_number' in point['tags']:
                                serial_numbers.append(point['tags']['device_serial_number'])
                            else:
                                serial_numbers.append('None')
                            
                            # Get sample field values
                            if 'fields' in point:
                                fields = point['fields']
                                sample_data = {}
                                for field_name in ['vacr', 'soc', 'fwcode', 'vbat', 'pinv']:
                                    if field_name in fields:
                                        sample_data[field_name] = fields[field_name]
                                if sample_data:
                                    sample_values.append(sample_data)
                                else:
                                    sample_values.append('No sample fields found')
                            else:
                                sample_values.append('No fields found')
                        
                        serial_list = ', '.join(serial_numbers)
                        self._log.info(f"Successfully wrote {len(points_to_write)} points to InfluxDB after reconnection (serial numbers: {serial_list})")
                        
                        # Log sample values for each point
                        for i, (serial, samples) in enumerate(zip(serial_numbers, sample_values)):
                            if isinstance(samples, dict):
                                sample_str = ', '.join([f"{k}={v}" for k, v in samples.items()])
                                self._log.debug(f"  Point {i+1} ({serial}): {sample_str}")
                            else:
                                self._log.debug(f"  Point {i+1} ({serial}): {samples}")
                    else:
                        self._log.info(f"Successfully wrote {len(points_to_write)} points to InfluxDB after reconnection")
                    
                    self.last_batch_time = time.time()
                except Exception as retry_e:
                    self._log.error(f"Failed to write batch after reconnection: {retry_e}")
                    # Store failed points in backlog
                    for point in points_to_write:
                        self._add_to_backlog(point)
                    self.connected = False
            else:
                # Store failed points in backlog
                for point in points_to_write:
                    self._add_to_backlog(point)
                self.connected = False

    def init_bridge(self, from_transport: transport_base):
        """Initialize bridge - not needed for InfluxDB output"""
        pass

    def __del__(self):
        """Cleanup on destruction - flush any remaining points"""
        if self.batch_points:
            self._flush_batch()
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass 