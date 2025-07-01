import inspect

from classes.protocol_settings import Registry_Type, protocol_settings

try:
    from pymodbus.client.sync import ModbusSerialClient
except ImportError:
    from pymodbus.client import ModbusSerialClient


from configparser import SectionProxy

from defs.common import find_usb_serial_port, get_usb_serial_port_info, strtoint

from .modbus_base import modbus_base


class modbus_rtu(modbus_base):
    port : str = "/dev/ttyUSB0"
    addresses : list[int] = []
    baudrate : int = 9600
    client : ModbusSerialClient

    pymodbus_slave_arg = "unit"

    def __init__(self, settings : SectionProxy, protocolSettings : protocol_settings = None):
        super().__init__(settings, protocolSettings=protocolSettings)

        self.port = settings.get("port", "")
        if not self.port:
            raise ValueError("Port is not set")

        self.port = find_usb_serial_port(self.port)
        if not self.port:
            raise ValueError("Port is not valid / not found")

        print("Serial Port : " + self.port + " = ", get_usb_serial_port_info(self.port)) #print for config convience

        if "baud" in self.protocolSettings.settings:
            self.baudrate = strtoint(self.protocolSettings.settings["baud"])
        #todo better baud/baudrate alias handling
        self.baudrate = settings.getint("baudrate", self.baudrate)

        address : int = settings.getint("address", 0)
        self.addresses = [address]

        # pymodbus compatability; unit was renamed to address
        if "slave" in inspect.signature(ModbusSerialClient.read_holding_registers).parameters:
            self.pymodbus_slave_arg = "slave"


        # Get the signature of the __init__ method
        init_signature = inspect.signature(ModbusSerialClient.__init__)

        client_str = self.port+"("+str(self.baudrate)+")"

        if client_str in modbus_base.clients:
            self.client = modbus_base.clients[client_str]
            return

            self._log.debug(f"Creating new client with baud rate: {self.baudrate}")

        if "method" in init_signature.parameters:
            self.client = ModbusSerialClient(method="rtu", port=self.port,
                                        baudrate=int(self.baudrate),
                                        stopbits=1, parity="N", bytesize=8, timeout=2
                                        )
        else:
            self.client = ModbusSerialClient(
                            port=self.port,
                            baudrate=int(self.baudrate),
                            stopbits=1, parity="N", bytesize=8, timeout=2
                            )

        #add to clients
        modbus_base.clients[client_str] = self.client

    def read_registers(self, start, count=1, registry_type : Registry_Type = Registry_Type.INPUT, **kwargs):

        if "unit" not in kwargs:
            kwargs = {"unit": int(self.addresses[0]), **kwargs}

        #compatability
        if self.pymodbus_slave_arg != "unit":
            kwargs["slave"] = kwargs.pop("unit")

        if registry_type == Registry_Type.INPUT:
            return self.client.read_input_registers(address=start, count=count, **kwargs)
        elif registry_type == Registry_Type.HOLDING:
            return self.client.read_holding_registers(address=start, count=count, **kwargs)

    def write_register(self, register : int, value : int, **kwargs):
        if not self.write_enabled:
            return

        if "unit" not in kwargs:
            kwargs = {"unit": self.addresses[0], **kwargs}

        #compatability
        if self.pymodbus_slave_arg != "unit":
            kwargs["slave"] = kwargs.pop("unit")

        self.client.write_register(register, value, **kwargs) #function code 0x06 writes to holding register

    def connect(self):
        self.connected = self.client.connect()
        self._log.debug(f"Modbus rtu connected: {self.connected}")
        super().connect()
