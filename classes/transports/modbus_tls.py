from configparser import SectionProxy

from pymodbus.client.sync import ModbusTlsClient

from classes.protocol_settings import Registry_Type, protocol_settings

from .transport_base import transport_base


class modbus_udp(transport_base):
    port : int = 502
    host : str = ""

    hostname : str = ""
    ''' optional for cert '''

    certfile : str = ""
    keyfile : str = ""
    client : ModbusTlsClient

    def __init__(self, settings : SectionProxy, protocolSettings : protocol_settings = None):
        self.host = settings.get("host", "")
        if not self.host:
            raise ValueError("Host is not set")

        self.port = settings.getint("port", self.port)

        self.certfile = settings.get("certfile", "")
        if not self.certfile:
            raise ValueError("certfile is not set")

        self.keyfile = settings.get("keyfile", "")
        if not self.keyfile:
            raise ValueError("keyfile is not set")

        self.hostname = settings.get("hostname", self.host)

        self.client = ModbusTlsClient(host=self.host,
                                      hostname = self.hostname,
                                      certfile = self.certfile,
                                      keyfile  = self.keyfile,
                                      port=self.port,
                                      timeout=7,
                                      retries=3)
        super().__init__(settings, protocolSettings=protocolSettings)

    def read_registers(self, start, count=1, registry_type : Registry_Type = Registry_Type.INPUT, **kwargs):
        if registry_type == Registry_Type.INPUT:
            return self.client.read_input_registers(start, count=count, **kwargs)
        elif registry_type == Registry_Type.HOLDING:
            return self.client.read_holding_registers(start, count=count, **kwargs)

    def connect(self):
        self.connected = self.client.connect()
        super().connect()
