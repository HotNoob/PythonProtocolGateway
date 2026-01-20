import inspect

from classes.protocol_settings import Registry_Type, protocol_settings

#compatability
try:
    from pymodbus.client.sync import ModbusTcpClient
except ImportError:
    from pymodbus.client import ModbusTcpClient

from configparser import SectionProxy

from .modbus_base import modbus_base


class modbus_tcp(modbus_base):
    port : str = 502
    host : str = ""
    client : ModbusTcpClient
    pymodbus_slave_arg = "unit"

    def __init__(self, settings : SectionProxy, protocolSettings : protocol_settings = None):
        self.host = settings.get("host", "")
        if not self.host:
            raise ValueError("Host is not set")

        self.port = settings.getint("port", self.port)

        # pymodbus compatability; unit was renamed to address
        if "slave" in inspect.signature(ModbusTcpClient.read_holding_registers).parameters:
            self.pymodbus_slave_arg = "slave"

        client_str = self.host+"("+str(self.port)+")"
        #check if client is already initialied
        with self._clients_lock:
            if client_str in modbus_base.clients:
                self.client = modbus_base.clients[client_str]
                super().__init__(settings, protocolSettings=protocolSettings)
                return

        self.client = ModbusTcpClient(host=self.host, port=self.port, timeout=7, retries=3)

        #add to clients (thread-safe)
        with self._clients_lock:
            modbus_base.clients[client_str] = self.client

        super().__init__(settings, protocolSettings=protocolSettings)

    def write_register(self, register : int, value : int, **kwargs):
        if not self.write_enabled:
            return

        if "unit" not in kwargs:
            kwargs = {"unit": 1, **kwargs}

        #compatability
        if self.pymodbus_slave_arg != "unit":
            kwargs["slave"] = kwargs.pop("unit")

        # Use port-specific lock for thread-safe access
        port_lock = self._get_port_lock()
        with port_lock:
            self.client.write_register(register, value, **kwargs) #function code 0x06 writes to holding register

    def read_registers(self, start, count=1, registry_type : Registry_Type = Registry_Type.INPUT, **kwargs):

        if "unit" not in kwargs:
            kwargs = {"unit": 1, **kwargs}

        #compatability
        if self.pymodbus_slave_arg != "unit":
            kwargs["slave"] = kwargs.pop("unit")

        # Use port-specific lock for thread-safe access
        port_lock = self._get_port_lock()
        with port_lock:
            if registry_type == Registry_Type.INPUT:
                return self.client.read_input_registers(start,count=count, **kwargs  )
            elif registry_type == Registry_Type.HOLDING:
                return self.client.read_holding_registers(start,count=count, **kwargs)

    def connect(self):
        self.connected = self.client.connect()
        super().connect()
