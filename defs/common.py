import os
import re

from serial.tools import list_ports


def strtobool (val):
    """Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1'
    """
    if isinstance(val, bool):
        return val

    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return 1

    return 0

def strtoint(val : str) -> int:
    ''' converts str to int, but allows for hex string input, identified by x prefix'''

    if isinstance(val, int): #is already int.
        return val

    val = val.lower().strip()

    if val and val[0] == "x":
        val = val[1:]
        # Pad the string with a leading zero
        if len(val) % 2 != 0:
            val = "0" + val

        return int.from_bytes(bytes.fromhex(val), byteorder="big")

    if val and val.startswith("0x"):
        val = val[2:]
        # Pad the string with a leading zero
        if len(val) % 2 != 0:
            val = "0" + val

        return int.from_bytes(bytes.fromhex(val), byteorder="big")

    if not val: #empty
        return 0

    return int(val)

def get_usb_serial_port_info(port : str = "") -> str:

    # If port is a symlink
    if os.path.islink(port):
        port = os.path.realpath(port)

    for p in list_ports.comports(): #from serial.tools
        if str(p.device).upper() == port.upper():
            vid = hex(p.vid) if p.vid is not None else ""
            pid = hex(p.pid) if p.pid is not None else ""
            serial = str(p.serial_number) if p.serial_number is not None else ""
            location = str(p.location) if p.location is not None else ""
            return "["+vid+":"+pid+":"+serial+":"+location+"]"

    return ""

def find_usb_serial_port(port : str =  "", vendor_id : str = "", product_id : str = "", serial_number : str = "", location : str = "") -> str:

    # If port is a symlink
    if os.path.islink(port):
        port = os.path.realpath(port)

    if not port.startswith("["):
        return port

    port = port.replace("None", "")

    match  = re.match(r"\[(?P<vendor>[\da-zA-Z]+|):?(?P<product>[\da-zA-Z]+|):?(?P<serial>[\da-zA-Z]+|):?(?P<location>[\d\-]+|)\]", port)
    if match:
        vendor_id = int(match.group("vendor"), 16) if match.group("vendor") else ""
        product_id = int(match.group("product"), 16) if match.group("product") else ""
        serial_number = match.group("serial") if match.group("serial") else ""
        location = match.group("location") if match.group("location") else ""

        for port in list_ports.comports(): #from serial.tools
            if ((not vendor_id or port.vid == vendor_id) and
                ( not product_id or port.pid == product_id) and
                ( not serial_number or port.serial_number == serial_number) and
                ( not location or port.location == location)):
                return port.device
    else:
        print("Bad Port Pattern", port)
        return None

    return None
