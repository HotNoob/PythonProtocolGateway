import ast
import csv
import glob
import itertools
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Union

from defs.common import strtoint

if TYPE_CHECKING:
    from configparser import SectionProxy

class Data_Type(Enum):
    BYTE = 1
    '''8bit byte'''
    USHORT = 2
    '''16 bit unsigned int'''
    UINT = 3
    '''32 bit unsigned int'''
    SHORT = 4
    '''16 bit signed int'''
    INT = 5
    '''32 bit signed int'''
    _16BIT_FLAGS = 7
    _8BIT_FLAGS = 8
    _32BIT_FLAGS = 9


    ASCII = 84
    ''' 2 characters '''
    HEX = 85
    ''' HEXADECIMAL STRING '''

    _1BIT = 201
    _2BIT = 202
    _3BIT = 203
    _4BIT = 204
    _5BIT = 205
    _6BIT = 206
    _7BIT = 207
    _8BIT = 208
    _9BIT = 209
    _10BIT = 210
    _11BIT = 211
    _12BIT = 212
    _13BIT = 213
    _14BIT = 214
    _15BIT = 215
    _16BIT = 216
    #signed bits
    _2SBIT = 302
    _3SBIT = 303
    _4SBIT = 304
    _5SBIT = 305
    _6SBIT = 306
    _7SBIT = 307
    _8SBIT = 308
    _9SBIT = 309
    _10SBIT = 310
    _11SBIT = 311
    _12SBIT = 312
    _13SBIT = 313
    _14SBIT = 314
    _15SBIT = 315
    _16SBIT = 316

    #signed magnitude  bits
    _2SMBIT = 402
    _3SMBIT = 403
    _4SMBIT = 404
    _5SMBIT = 405
    _6SMBIT = 406
    _7SMBIT = 407
    _8SMBIT = 408
    _9SMBIT = 409
    _10SMBIT = 410
    _11SMBIT = 411
    _12SMBIT = 412
    _13SMBIT = 413
    _14SMBIT = 414
    _15SMBIT = 415
    _16SMBIT = 416

    @classmethod
    def fromString(cls, name : str):
        name = name.strip().upper()
        if name[0].isdigit():
            name = "_"+name

        #common alternative names
        alias : dict[str,str] = {
            "UINT8" : "BYTE",
            "INT16" : "SHORT",
            "UINT16" : "USHORT",
            "UINT32" : "UINT",
            "INT32" : "INT"
        }

        if name in alias:
            name = alias[name]

        return getattr(cls, name)

    @classmethod
    def getSize(cls, data_type : "Data_Type"):
        sizes = {
                    Data_Type.BYTE : 8,
                    Data_Type.USHORT : 16,
                    Data_Type.UINT : 32,
                    Data_Type.SHORT : 16,
                    Data_Type.INT : 32,
                    Data_Type._8BIT_FLAGS : 8,
                    Data_Type._16BIT_FLAGS : 16,
                    Data_Type._32BIT_FLAGS : 32
                 }

        if data_type in sizes:
            return sizes[data_type]

        if data_type.value > 400:  #signed magnitude bits
            return data_type.value-400

        if data_type.value > 300:  #signed bits
            return data_type.value-300

        if data_type.value > 200: #unsigned bits
            return data_type.value-200

        return -1 #should never happen

class WriteMode(Enum):
    READ = 0x00
    ''' READ ONLY '''
    READDISABLED = 0x01
    ''' DO NOT READ OR WRITE'''
    WRITE = 0x02
    ''' READ AND WRITE '''

    #todo, write only
    WRITEONLY = 0x03
    ''' WRITE ONLY'''

    @classmethod
    def fromString(cls, name : str):
        name = name.strip().upper()

        #common alternative names
        alias : dict[str,WriteMode] = {
            "R"     : "READ",
            "NO"    : "READ",
            "READ"  : "READ",
            "WD"    : "READ",
            "RD"            : "READDISABLED",
            "READDISABLED"  : "READDISABLED",
            "DISABLED"      : "READDISABLED",
            "D"             : "READDISABLED",
            "R/W"    : "WRITE",
            "RW"    : "WRITE",
            "W"     : "WRITE",
            "YES"   : "WRITE",
            "WO"    : "WRITEONLY"
        }

        if name in alias:
            name = alias[name]
        else:
            name = "READ" #default

        return getattr(cls, name)

class Registry_Type(Enum):
    ZERO = 0x00
    ''' for protocols that don't have a command / registry type '''

    HOLDING = 0x03
    INPUT = 0x04

@dataclass
class registry_map_entry:
    registry_type : Registry_Type
    register : int
    register_bit : int
    register_byte : int
    ''' byte offset for canbus ect... '''

    variable_name : str
    documented_name : str
    unit : str
    unit_mod : float
    concatenate : bool
    concatenate_registers : list[int]

    values : list
    value_regex : str = ""

    value_min : int = 0
    ''' min of value range for protocol analyzing'''
    value_max : int = 65535
    ''' max of value range for protocol analyzing'''

    ''' if value needs to be concatenated with other registers'''
    data_type : Data_Type = Data_Type.USHORT
    data_type_size : int = -1
    ''' for non-fixed size types like ASCII'''

    data_byteorder : str = ''
    ''' entry specific byte order little | big | '' '''

    read_command : bytes = None
    ''' for transports/protocols that require sending a command ontop of "register" '''

    read_interval : int = 1000
    ''' how often to read register in ms'''

    next_read_timestamp : int = 0
    ''' unix timestamp in ms '''

    write_mode : WriteMode = WriteMode.READ
    ''' enable disable reading/writing '''

    has_enum_mapping : bool = False
    ''' indicates if this field has enum mappings that should be treated as strings '''

    def __str__(self):
        return self.variable_name

    def __eq__(self, other):
        return (    isinstance(other, registry_map_entry)
                    and self.register == other.register
                    and self.register_bit == other.register_bit
                    and self.registry_type == other.registry_type
                    and self.register_byte == other.register_byte)

    def __hash__(self):
        # Hash based on tuple of object attributes
        return hash((self.variable_name, self.register_bit, self.register_byte, self.registry_type))


class protocol_settings:

    protocol : str
    transport : str
    settings_dir : str
    variable_mask : list[str]
    ''' list of variables to allow and exclude all others '''

    variable_screen : list[str]
    ''' list of variables to exclude '''

    registry_map : dict[Registry_Type, list[registry_map_entry]] = {}
    registry_map_size : dict[Registry_Type, int] = {}
    registry_map_ranges : dict[Registry_Type, list[tuple]] = {}

    codes : dict[str, str]
    settings : dict[str, str]
    ''' default settings provided by protocol json '''

    transport_settings : "SectionProxy" = None

    byteorder : str = "big"

    _log : logging.Logger = None


    def __init__(self, protocol : str, transport_settings : "SectionProxy" = None, settings_dir : str = "protocols"):

        #apply log level to logger
        self._log_level = getattr(logging, logging.getLevelName(logging.getLogger().getEffectiveLevel()), logging.INFO)
        self._log : logging.Logger = logging.getLogger(__name__)
        self._log.setLevel(self._log_level)

        self.protocol = protocol
        self.settings_dir = settings_dir
        self.transport_settings = transport_settings

        #load variable mask
        self.variable_mask = []
        if os.path.isfile("variable_mask.txt"):
            with open("variable_mask.txt") as f:
                for line in f:
                    if line[0] == "#": #skip comment
                        continue

                    self.variable_mask.append(line.strip().lower())

        #load variable screen
        self.variable_screen = []
        if os.path.isfile("variable_screen.txt"):
            with open("variable_screen.txt") as f:
                for line in f:
                    if line[0] == "#": #skip comment
                        continue

                    self.variable_screen.append(line.strip().lower())

        self.load__json() #load first, so priority to json codes

        if "transport" in self.settings:
            self.transport = self.settings["transport"]
        elif "reader" in self.settings:
            self.transport = self.settings["reader"]
        else:
            self.transport = "modbus_rtu"

        if "byteorder" in self.settings: #handle byte order for ints n stuff
            self.byteorder = self.settings["byteorder"]

        for registry_type in Registry_Type:
            self.load_registry_map(registry_type)

    def get_registry_map(self, registry_type : Registry_Type = Registry_Type.ZERO) -> list[registry_map_entry]:
        return self.registry_map[registry_type]

    def get_registry_ranges(self, registry_type : Registry_Type) -> list[registry_map_entry]:
        return self.registry_map_ranges[registry_type]


    def get_holding_registry_entry(self, name : str):
        ''' deprecated '''
        return self.get_registry_entry(name, registry_type=Registry_Type.HOLDING)

    def get_input_registry_entry(self, name : str):
        ''' deprecated '''
        return self.get_registry_entry(name, registry_type=Registry_Type.INPUT)

    def get_registry_entry(self, name : str, registry_type : Registry_Type) -> registry_map_entry:

        name = name.strip().lower().replace(" ", "_") #clean name
        for item in self.registry_map[registry_type]:
            if item.documented_name == name:
                return item

        return None

    def load__json(self, file : str = "", settings_dir : str = ""):
        if not settings_dir:
            settings_dir = self.settings_dir

        if not file:
            file = self.protocol + ".json"

        path = self.find_protocol_file(file, settings_dir)

        #if path does not exist; nothing to load. skip.
        if not path:
            self._log.error("ERROR: '"+file+"' not found")
            return

        with open(path) as f:
            self.codes = json.loads(f.read())

        self.settings = {}

        # Iterate over the keys and add entries not ending with "_codes" to self.settings
        for key, value in self.codes.items():
            if not key.endswith("_codes"):
                self.settings[key] = value

    def load_registry_overrides(self, override_path, keys : list[str]):
        """Load overrides into a multidimensional dictionary keyed by each specified key."""
        overrides = {key: {} for key in keys}

        with open(override_path, newline="", encoding="latin-1") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                for key in keys:
                    if key in row:
                        row[key] = row[key].strip().lower().replace(" ", "_")
                        key_value = row[key]
                        if key_value:
                            overrides[key][key_value] = row
        return overrides


    def load__registry(self, path, registry_type : Registry_Type = Registry_Type.INPUT) -> list[registry_map_entry]:
        registry_map : list[registry_map_entry] = []
        register_regex = re.compile(r"(?P<register>(?:0?x[\da-z]+|[\d]+))\.(b(?P<bit>x?\d{1,2})|(?P<byte>x?\d{1,2}))")

        read_interval_regex = re.compile(r"(?P<value>[\.\d]+)(?P<unit>[xs]|ms)")


        data_type_regex = re.compile(r"(?P<datatype>\w+)\.(?P<length>\d+)")

        range_regex = re.compile(r"(?P<reverse>r|)(?P<start>(?:0?x[\da-z]+|[\d]+))[\-~](?P<end>(?:0?x[\da-z]+|[\d]+))")
        ascii_value_regex = re.compile(r"(?P<regex>^\[.+\]$)")
        list_regex = re.compile(r"\s*(?:(?P<range_start>(?:0?x[\da-z]+|[\d]+))-(?P<range_end>(?:0?x[\da-z]+|[\d]+))|(?P<element>[^,\s][^,]*?))\s*(?:,|$)")


        #load read_interval from transport settings, for #x per register read intervals
        transport_read_interval : int = 1000
        if self.transport_settings is not None:
            transport_read_interval = self.transport_settings.getint("read_interval", transport_read_interval)


        if not os.path.exists(path): #return empty is file doesnt exist.
            return registry_map


        overrides : dict[str, dict]  = None
        override_keys = ["documented name", "register"]
        overrided_keys = set()
        ''' list / set of keys that were used for overriding. to track unique entries'''

        #assuming path ends with .csv
        override_path = path[:-4] + ".override.csv"

        if os.path.exists(override_path):
            self._log.info("loading override file: " + override_path)

            overrides = self.load_registry_overrides(override_path, override_keys)

        def determine_delimiter(first_row) -> str:
            if first_row.count(";") > first_row.count(","):
                return ";"
            else:
                return ","

        def process_row(row):
            # Initialize variables to hold numeric and character parts
            unit_multiplier : float = 1
            unit_symbol : str = ""
            read_interval : int = 0
            ''' read interval in ms '''

             #clean up doc name, for extra parsing
            row["documented name"] = row["documented name"].strip().lower().replace(" ", "_")

            #region read_interval


            if "read interval" in row:
                row["read interval"] = row["read interval"].lower() #ensure is all lower case
                match = read_interval_regex.search(row["read interval"])
                if match:
                    unit = match.group("unit")
                    value = match.group("value")
                    if value:
                        value = float(value)
                        if unit == "x":
                            read_interval = int((transport_read_interval * 1000) * value)
                        else: # seconds or ms
                            read_interval = value
                            if unit != "ms":
                                read_interval *= 1000

            if read_interval == 0:
                read_interval = transport_read_interval * 1000
                if "read_interval" in self.settings:
                    try:
                        read_interval = int(self.settings["read_interval"])
                    except ValueError:
                        read_interval = transport_read_interval * 1000


            #region overrides
            if overrides is not None:
                #apply overrides using documented name or register
                override_row = None
                # Check each key in order until a match is found
                for key in override_keys:
                    key_value = row.get(key)
                    if key_value and key_value in overrides[key]:
                        override_row = overrides[key][key_value]
                        overrided_keys.add(key_value)
                        break

                # Apply non-empty override values if an override row is found
                if override_row:
                    for field, override_value in override_row.items():
                        if override_value:  # Only replace if override value is non-empty
                            row[field] = override_value

            #endregion overrides

            #region unit

            #if or is in the unit; ignore unit
            if "or" in row["unit"].lower() or ":" in row["unit"].lower():
                unit_multiplier = 1
                unit_symbol = row["unit"]
            else:
                # Use regular expressions to extract numeric and character parts
                matches = re.findall(r"(\-?[0-9.]+)|(.*?)$", row["unit"])

                # Iterate over the matches and assign them to appropriate variables
                for match in matches:
                    if match[0]:  # If it matches a numeric part
                        unit_multiplier = float(match[0])
                    elif match[1]:  # If it matches a character part
                        unit_symbol = match[1].strip()

            #convert to float
            try:
                unit_multiplier = float(unit_multiplier)
            except Exception:
                unit_multiplier = float(1)

            if unit_multiplier == 0:
                unit_multiplier = float(1)

            #endregion unit


            variable_name = row["variable name"] if row["variable name"] else row["documented name"]
            variable_name = variable_name.strip().lower().replace(" ", "_").replace("__", "_") #clean name

            if re.search(r"[^a-zA-Z0-9\_]", variable_name) :
                self._log.warning("Invalid Name : " + str(variable_name) + " reg: " + str(row["register"]) + " doc name: " + str(row["documented name"]) + " path: " + str(path))


            if not variable_name and not row["documented name"]: #skip empty entry / no name. todo add more invalidator checks.
                return

            #region data type
            data_type = Data_Type.USHORT
            data_type_len : int = -1
            data_byteorder : str = ''
            #optional row, only needed for non-default data types
            if "data type" in row and row["data type"]:
                data_type_str : str = ''

                matches = data_type_regex.search(row["data type"])
                if matches:
                    data_type_len = int(matches.group("length"))
                    data_type_str = matches.group("datatype")
                else:
                    data_type_str = row["data type"]

                #check if datatype specifies byteorder
                if data_type_str.upper().endswith("_LE"):
                    data_byteorder = "little"
                    data_type_str = data_type_str[:-3]
                elif data_type_str.upper().endswith("_BE"):
                    data_byteorder = "big"
                    data_type_str = data_type_str[:-3]


                data_type = Data_Type.fromString(data_type_str)



            if "values" not in row:
                row["values"] = ""
                self._log.warning("No Value Column : path: " + str(path))

            #endregion data type

            #region values
            #get value range for protocol analyzer
            values : list = []
            value_min : int = 0
            value_max : int = 65535 #default - max value for ushort
            value_regex : str = ""
            value_is_json : bool = False

            #test if value is json.
            if "{" in row["values"]: #to try and stop non-json values from parsing. the json parser is buggy for validation
                try:
                    codes_json = json.loads(row["values"])
                    value_is_json = True

                    name = row["documented name"]+"_codes"
                    if name not in self.codes:
                        self.codes[name] = codes_json

                except ValueError:
                    value_is_json = False

            if not value_is_json:
                if "," in row["values"]:
                    matches = list_regex.finditer(row["values"])

                    for match in matches:
                        groups = match.groupdict()
                        if groups["range_start"] and groups["range_end"]:
                            start = strtoint(groups["range_start"])
                            end = strtoint(groups["range_end"])
                            values.extend(range(start, end + 1))
                        else:
                            values.append(groups["element"])
                else:
                    matched : bool = False
                    val_match = range_regex.search(row["values"])
                    if val_match:
                        value_min = strtoint(val_match.group("start"))
                        value_max = strtoint(val_match.group("end"))
                        matched = True

                    if data_type == Data_Type.ASCII: #might need to apply too hex values as well? or min-max works for hex?
                        #value_regex
                        val_match = ascii_value_regex.search(row["values"])
                        if val_match:
                            value_regex = val_match.group("regex")
                            matched = True

                    if not matched: #single value
                        values.append(row["values"])
            #endregion values

            #region register
            concatenate : bool = False
            concatenate_registers : list[int] = []

            register : int = -1
            register_bit : int = 0
            register_byte : int = -1
            row["register"] = row["register"].lower() #ensure is all lower case
            match = register_regex.search(row["register"])
            if match:
                register = strtoint(match.group("register"))

                register_bit = match.group("bit")
                if register_bit:
                    register_bit = strtoint(register_bit)
                else:
                    register_bit = 0

                register_byte = match.group("byte")
                if register_byte:
                    register_byte = strtoint(register_byte)
                else:
                    register_byte = 0

                #print("register: " + str(register) + " bit : " + str(register_bit))
            else:
                range_match = range_regex.search(row["register"])
                if not range_match:
                    register = strtoint(row["register"])
                else:
                    reverse = range_match.group("reverse")
                    start = strtoint(range_match.group("start"))
                    end = strtoint(range_match.group("end"))
                    register = start
                    if end > start:
                        concatenate = True
                        if reverse:
                            for i in range(end, start-1, -1):
                                concatenate_registers.append(i)
                        else:
                            for i in range(start, end+1):
                                concatenate_registers.append(i)

            if concatenate_registers:
                r = range(len(concatenate_registers))
            else:
                r = range(1)

            #endregion register

            read_command = None
            if "read command" in row and row["read command"]:
                if row["read command"][0] == "x":
                    read_command = bytes.fromhex(row["read command"][1:])
                else:
                    read_command = row["read command"].encode("utf-8")

            writeMode : WriteMode = WriteMode.READ
            if "writable" in row:
                writeMode = WriteMode.fromString(row["writable"])

            if "write" in row:
                writeMode = WriteMode.fromString(row["write"])

            for i in r:
                item = registry_map_entry(
                                            registry_type = registry_type,
                                            register= register,
                                            register_bit=register_bit,
                                            register_byte= register_byte,
                                            variable_name= variable_name,
                                            documented_name = row["documented name"],
                                            unit= str(unit_symbol),
                                            unit_mod= unit_multiplier,
                                            data_type= data_type,
                                            data_type_size = data_type_len,
                                            data_byteorder = data_byteorder,
                                            concatenate = concatenate,
                                            concatenate_registers = concatenate_registers,
                                            values=values,
                                            value_min=value_min,
                                            value_max=value_max,
                                            value_regex=value_regex,
                                            read_command = read_command,
                                            read_interval=read_interval,
                                            write_mode=writeMode,
                                            has_enum_mapping=value_is_json
                                        )
                registry_map.append(item)

                register = register + 1


        with open(path, newline="", encoding="latin-1") as csvfile:

            #clean column names before passing to csv dict reader

            delimeter = ";"
            first_row = next(csvfile).lower().replace("_", " ")
            if first_row.count(";") < first_row.count(","):
                delimeter = ","

            first_row = re.sub(r"\s+" + re.escape(delimeter) +"|" + re.escape(delimeter) +r"\s+", delimeter, first_row) #trim values

            csvfile = itertools.chain([first_row], csvfile) #add clean header to begining of iterator

            # Create a CSV reader object
            reader = csv.DictReader(csvfile, delimiter=delimeter)

            # Iterate over each row in the CSV file
            for row in reader:
                process_row(row)

            if overrides is not None:
                # Add any unmatched overrides as new entries... probably need to add some better error handling to ensure entry isnt empty ect...
                for key in override_keys:
                    applied = False
                    for key_value, override_row in overrides[key].items():
                        # Check if both keys are unique before applying
                        if all(override_row.get(k) for k in override_keys):
                            if all(override_row.get(k) not in overrided_keys for k in override_keys):
                                self._log.info("Loading unique entry from overrides for both unique keys")
                                process_row(override_row)

                                # Mark both keys as applied
                                for k in override_keys:
                                    overrided_keys.add(override_row.get(k))

                                applied = True
                                break  # Exit inner loop after applying unique entry

                    if applied:
                        continue

            for index in reversed(range(len(registry_map))):
                item = registry_map[index]
                if index > 0:
                    #if high/low, its a double
                    if (
                        item.documented_name.endswith("_l")
                        and registry_map[index-1].documented_name.replace("_h", "_l") == item.documented_name
                        ):
                        combined_item = registry_map[index-1]

                        if not combined_item.data_type or combined_item.data_type  == Data_Type.USHORT:
                            if registry_map[index].data_type != Data_Type.USHORT:
                                combined_item.data_type = registry_map[index].data_type
                            else:
                                combined_item.data_type = Data_Type.UINT


                        if combined_item.documented_name == combined_item.variable_name:
                            combined_item.variable_name = combined_item.variable_name[:-2].strip()

                        combined_item.documented_name = combined_item.documented_name[:-2].strip()

                        if not combined_item.unit: #fix inconsistsent documentation
                            combined_item.unit = registry_map[index].unit
                            combined_item.unit_mod = registry_map[index].unit_mod

                        del registry_map[index]

            #apply mask
            if self.variable_mask:
                for index in reversed(range(len(registry_map))):
                    item = registry_map[index]
                    if (
                        item.documented_name.strip().lower() not in self.variable_mask
                        and item.variable_name.strip().lower() not in self.variable_mask
                        ):
                        del registry_map[index]

            #apply variable screen
            if self.variable_screen:
                for index in reversed(range(len(registry_map))):
                    item = registry_map[index]
                    if (
                        item.documented_name.strip().lower() in self.variable_mask
                        and item.variable_name.strip().lower() in self.variable_mask
                        ):
                        del registry_map[index]

            return registry_map

    def calculate_registry_ranges(self, map : list[registry_map_entry], max_register : int, init : bool = False, timestamp: int = 0) -> list[tuple]:

        ''' read optimization; calculate which ranges to read'''
        max_batch_size = 45 #see manual; says max batch is 45

        if "batch_size" in self.settings:
            try:
                max_batch_size = int(self.settings["batch_size"])
            except ValueError:
                pass

        # Debug: log the parameters
        import logging
        log = logging.getLogger(__name__)
        log.info(f"calculate_registry_ranges: max_register={max_register}, max_batch_size={max_batch_size}, map_size={len(map)}, init={init}")

        start = -max_batch_size
        ranges : list[tuple] = []

        if timestamp > 0:
            timestamp_ms = timestamp*1000
        else:
            timestamp_ms = int(time.time() * 1000)

        while (start := start+max_batch_size) <= max_register:

            registers : list[int] = [] #use a list, im too lazy to write logic

            end = start+max_batch_size
            for register in map:
                if register.register >= start and register.register < end:
                    if register.write_mode == WriteMode.READDISABLED: ##register is disabled; skip
                        continue
                    if register.write_mode == WriteMode.WRITEONLY: ##Write Only; skip
                        continue

                    #we are assuming calc registry ranges is being called EVERY READ.
                    if init: #add but do not update timestamp; can maybe rename init to no timestamp at this point
                        registers.append(register.register)
                    elif register.next_read_timestamp < timestamp_ms:
                        register.next_read_timestamp = timestamp_ms + register.read_interval
                        registers.append(register.register)

            if registers: #not empty
                ranges.append((min(registers), max(registers)-min(registers)+1)) ## APPENDING A TUPLE!

        return ranges


    def find_protocol_file(self, file : str, base_dir : str = "" ) -> str:

        path = base_dir + "/" + file
        if os.path.exists(path):
            return path

        suffix = file.split("_", 1)[0]

        path = base_dir + "/" + suffix +"/" + file
        if os.path.exists(path):
            return path

        #find file by name, recurisvely. last resort
        search_pattern = os.path.join(base_dir, "**", file)
        matches = glob.glob(search_pattern, recursive=True)
        return matches[0] if matches else None


    def load_registry_map(self, registry_type : Registry_Type, file : str = "", settings_dir : str = ""):
        if not settings_dir:
            settings_dir = self.settings_dir

        if not file:
            if registry_type == Registry_Type.ZERO:
                file = self.protocol + ".registry_map.csv"
            else:
                file = self.protocol + "."+registry_type.name.lower()+"_registry_map.csv"

        path = self.find_protocol_file(file, settings_dir)

        #if path does not exist; nothing to load. skip.
        if not path:
            return

        self.registry_map[registry_type] = self.load__registry(path, registry_type)

        size : int = 0

        #get max register size
        for item in self.registry_map[registry_type]:
            if item.register > size:
                size = item.register

        self.registry_map_size[registry_type] = size
        self._log.info(f"load_registry_map: {registry_type.name} - loaded {len(self.registry_map[registry_type])} entries, max_register={size}")
        self.registry_map_ranges[registry_type] = self.calculate_registry_ranges(self.registry_map[registry_type], self.registry_map_size[registry_type], init=True)

    def process_register_bytes(self, registry : dict[int,bytes], entry : registry_map_entry):
        ''' process bytes into data'''

        byte_order : str = self.byteorder
        if entry.data_byteorder: #allow map entry to override byteorder
            byte_order = entry.data_byteorder

        if isinstance(registry[entry.register], tuple):
            register = registry[entry.register][0] #can bus uses tuple for timestamp
        else:
            register = registry[entry.register]

        if entry.register_byte > 0:
            register = register[entry.register_byte:]

        if entry.data_type_size > 0:
            register = register[:entry.data_type_size]

        if entry.data_type == Data_Type.UINT:
            value = int.from_bytes(register[:4], byteorder=byte_order, signed=False)
        elif entry.data_type == Data_Type.INT:
            value = int.from_bytes(register[:4], byteorder=byte_order, signed=True)
        elif entry.data_type == Data_Type.USHORT:
            value = int.from_bytes(register[:2], byteorder=byte_order, signed=False)
        elif entry.data_type == Data_Type.SHORT:
            value = int.from_bytes(register[:2], byteorder=byte_order, signed=True)
        elif entry.data_type == Data_Type._16BIT_FLAGS or entry.data_type == Data_Type._8BIT_FLAGS or entry.data_type == Data_Type._32BIT_FLAGS:
            val = int.from_bytes(register, byteorder=byte_order, signed=False)
            #16 bit flags
            start_bit : int = 0
            end_bit : int = 16 #default 16 bit
            flag_size : int = Data_Type.getSize(entry.data_type)

            if entry.register_bit > 0: #handle custom bit offset
                start_bit = entry.register_bit

            #handle custom sizes, less than 1 register
            end_bit = flag_size + start_bit

            if entry.documented_name+"_codes" in self.codes:
                code_key : str = entry.documented_name+"_codes"
                flags : list[str] = []
                flag_indexes : list[str] = []
                for i in range(start_bit, end_bit):  # Iterate over each bit position (0 to 15)
                    byte = i // 8
                    bit = i % 8
                    val = register[byte]
                    # Check if the i-th bit is set
                    if (val >> bit) & 1:
                        flag_index = "b"+str(i)
                        flag_indexes.append(flag_index)
                        if flag_index in self.codes[code_key]:
                            flags.append(self.codes[code_key][flag_index])

                #check multibit flags
                multibit_flags = [key for key in self.codes if "&" in key]

                if multibit_flags: #if multibit flags are found
                    flag_indexes_set : set[str] = set(flag_indexes)
                    for multibit_flag in multibit_flags:
                        bits = multibit_flag.split("&")  # Split key into 'bits'
                        if all(bit in flag_indexes_set for bit in bits): # Check if all bits are present in the flag_indexes_set
                            flags.append(self.codes[code_key][multibit_flag])

                value = ",".join(flags)
            else:
                flags : list[str] = []
                for i in range(start_bit, end_bit):  # Iterate over each bit position (0 to 15)
                    # Check if the i-th bit is set
                    if (val >> i) & 1:
                        flags.append("1")
                    else:
                        flags.append("0")
                value = "".join(flags)


        elif entry.data_type.value > 400: #signed-magnitude bit types ( sign bit is the last bit instead of front )
            bit_size = Data_Type.getSize(entry.data_type)
            bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
            bit_index = entry.register_bit

            # Check if the value is negative
            if (register >> bit_index) & 1:
                # If negative, extend the sign bit to fill out the value
                sign_extension = 0xFFFFFFFFFFFFFFFF << bit_size
                value = (register >> (bit_index + 1)) | sign_extension
            else:
                # If positive, simply extract the value using the bit mask
                value = (register >> bit_index) & bit_mask
        elif entry.data_type.value > 300: #signed bit types
            bit_size = Data_Type.getSize(entry.data_type)
            bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
            bit_index = entry.register_bit

            # Check if the value is negative
            if (register >> (bit_index + bit_size - 1)) & 1:
                # If negative, extend the sign bit to fill out the value
                sign_extension = 0xFFFFFFFFFFFFFFFF << bit_size
                value = (register >> bit_index) | sign_extension
            else:
                # If positive, simply extract the value using the bit mask
                value = (register >> bit_index) & bit_mask

        elif entry.data_type == Data_Type.BYTE: #bit types
            value = int.from_bytes(register[:1], byteorder=byte_order, signed=False)
        elif entry.data_type.value > 200: #bit types
            bit_size = Data_Type.getSize(entry.data_type)
            bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
            bit_index = entry.register_bit


            if isinstance(register, bytes):
                register = int.from_bytes(register, byteorder=byte_order)

            value = (register >> bit_index) & bit_mask


        elif entry.data_type == Data_Type.HEX:
            value = register.hex() #convert bytes to hex
        elif entry.data_type == Data_Type.ASCII:
            try:
                value = register.decode("utf-8") #convert bytes to ascii
            except UnicodeDecodeError as e:
                self._log.error("UnicodeDecodeError:", e)

        #apply unit mod
        if entry.unit_mod != float(1):
            value = value * entry.unit_mod

        #apply codes
        if (entry.data_type != Data_Type._16BIT_FLAGS and
            entry.documented_name+"_codes" in self.codes):
            try:
                cleanval = str(int(value))

                if cleanval in self.codes[entry.documented_name+"_codes"]:
                    value = self.codes[entry.documented_name+"_codes"][cleanval]
            except Exception:
                #do nothing; try is for intval
                value = value

        return value


    def process_register_ushort(self, registry : dict[int, int], entry : registry_map_entry ):
        ''' process ushort type registry into data'''

        byte_order : str = self.byteorder
        if entry.data_byteorder:
            byte_order = entry.data_byteorder

        if entry.data_type == Data_Type.UINT: #read uint
            if entry.register + 1 not in registry:
                return

            value = float((registry[entry.register] << 16) + registry[entry.register + 1])
        elif entry.data_type == Data_Type.SHORT: #read signed short
            val = registry[entry.register]

            # Convert the combined unsigned value to a signed integer if necessary
            if val & (1 << 15):  # Check if the sign bit (bit 31) is set
                # Perform two's complement conversion to get the signed integer
                value = val - (1 << 16)
            else:
                value = val
            value = -value
        elif entry.data_type == Data_Type.INT: #read int
            if entry.register + 1 not in registry:
                return

            combined_value_unsigned = (registry[entry.register] << 16) + registry[entry.register + 1]

            # Convert the combined unsigned value to a signed integer if necessary
            if combined_value_unsigned & (1 << 31):  # Check if the sign bit (bit 31) is set
                # Perform two's complement conversion to get the signed integer
                value = combined_value_unsigned - (1 << 32)
            else:
                value = combined_value_unsigned
            value = -value
            #value = struct.unpack('<h', bytes([min(max(registry[item.register], 0), 255), min(max(registry[item.register+1], 0), 255)]))[0]
            #value = int.from_bytes(bytes([registry[item.register], registry[item.register + 1]]), byteorder='little', signed=True)
        elif entry.data_type == Data_Type._16BIT_FLAGS or entry.data_type == Data_Type._8BIT_FLAGS or entry.data_type == Data_Type._32BIT_FLAGS:

            #16 bit flags
            start_bit : int = 0
            end_bit : int = 16 #default 16 bit
            flag_size : int = Data_Type.getSize(entry.data_type)

            if entry.register_bit > 0: #handle custom bit offset
                start_bit = entry.register_bit

            #handle custom sizes, less than 1 register
            end_bit = flag_size + start_bit

            offset : int = 0
            #calculate current offset for mutliregiter values, were assuming concatenate registers is in order, 0 being the first / lowest
            #offset should always be >= 0
            if entry.concatenate:
                offset : int = entry.register - entry.concatenate_registers[0]

            #compensate for current offset
            end_bit = end_bit - (offset * 16)

            val = registry[entry.register]

            if entry.documented_name+"_codes" in self.codes:
                flags : list[str] = []
                offset : int = 0

                if end_bit > 0:
                    end : int = 16 if end_bit >= 16 else end_bit
                    for i in range(start_bit, end):  # Iterate over each bit position (0 to 15)
                        # Check if the i-th bit is set
                        if (val >> i) & 1:
                            flag_index = "b"+str(i+offset-start_bit)
                            if flag_index in self.codes[entry.documented_name+"_codes"]:
                                flags.append(self.codes[entry.documented_name+"_codes"][flag_index])


                value = ",".join(flags)
            else:
                flags : list[str] = []
                if end_bit > 0:
                    end : int = 16 if end_bit >= 16 else end_bit
                    for i in range(start_bit, end):  # Iterate over each bit position (0 to 15)
                        # Check if the i-th bit is set
                        if (val >> i) & 1:
                            flags.append("1")
                        else:
                            flags.append("0")

                value = "".join(flags)

        elif entry.data_type.value > 200 or entry.data_type == Data_Type.BYTE: #bit types
                bit_size = Data_Type.getSize(entry.data_type)
                bit_mask = (1 << bit_size) - 1  # Create a mask for extracting X bits
                bit_index = entry.register_bit
                value = (registry[entry.register] >> bit_index) & bit_mask
        elif entry.data_type == Data_Type.HEX:
                value = registry[entry.register].to_bytes((16 + 7) // 8, byteorder=byte_order) #convert to ushort to bytes
                value = value.hex() #convert bytes to hex
        elif entry.data_type == Data_Type.ASCII:
            # For ASCII data, use little-endian byte order to read characters in correct order
            value = registry[entry.register].to_bytes((16 + 7) // 8, byteorder="little") #convert to ushort to bytes
            try:
                value = value.decode("utf-8") #convert bytes to ascii
            except UnicodeDecodeError as e:
                self._log.error("UnicodeDecodeError:", e)

        else: #default, Data_Type.USHORT
            value = float(registry[entry.register])

        if entry.unit_mod != float(1):
            value = value * entry.unit_mod

        #move this to transport level
        #if  isinstance(value, float) and self.max_precision > -1:
        #   value = round(value, self.max_precision)

        if (entry.data_type != Data_Type._16BIT_FLAGS and
            entry.documented_name+"_codes" in self.codes):
            try:
                cleanval = str(int(value))

                if cleanval in self.codes[entry.documented_name+"_codes"]:
                    value = self.codes[entry.documented_name+"_codes"][cleanval]
            except Exception:
                #do nothing; try is for intval
                value = value

        return value

    def process_registery(self, registry : Union[dict[int, int], dict[int, bytes]] , map : list[registry_map_entry]) -> dict[str,str]:
        '''process registry into appropriate datatypes and names -- maybe add func for single entry later?'''

        concatenate_registry : dict = {}
        info = {}
        for entry in map:

            if entry.register not in registry:
                continue
            value = ""

            if isinstance(registry[entry.register], bytes):
                value = self.process_register_bytes(registry, entry)
            else:
                value = self.process_register_ushort(registry, entry)

            #if item.unit:
            #    value = str(value) + item.unit
            if entry.concatenate:
                concatenate_registry[entry.register] = value

                all_exist = True
                for key in entry.concatenate_registers:
                    if key not in concatenate_registry:
                        all_exist = False
                        break
                if all_exist:
                #if all(key in concatenate_registry for key in item.concatenate_registers):
                    concatenated_value = ""
                    for key in entry.concatenate_registers:
                        concatenated_value = concatenated_value + str(concatenate_registry[key])
                        del concatenate_registry[key]

                    #replace null characters with spaces and trim
                    if entry.data_type == Data_Type.ASCII:
                        concatenated_value = concatenated_value.replace("\x00", " ").strip()

                    info[entry.variable_name] = concatenated_value
            else:
                info[entry.variable_name] = value

        return info

    def validate_registry_entry(self, entry : registry_map_entry, val) -> int:
            #if code, validate first.
            if entry.documented_name+"_codes" in self.codes:
                if val in self.codes[entry.documented_name+"_codes"]:
                    return 1
                else:
                    return 0

            if entry.data_type == Data_Type.ASCII:
                if val and not re.match(r"[^a-zA-Z0-9\_\-]", val): #validate ascii
                    if entry.value_regex: #regex validation
                        if re.match(entry.value_regex, val):
                            if entry.concatenate:
                                return len(entry.concatenate_registers)

            else: #default type
                intval = int(val)
                if intval >= entry.value_min and intval <= entry.value_max:
                    return 1

                self._log.error(f"validate_registry_entry '{entry.variable_name}' fail (INT) {intval} != {entry.value_min}~{entry.value_max}")

            return 0

    def evaluate_expressions(self, expression, variables : dict[str,str]):
        # Define the register string
        register = "x4642.[ 1 + ((( [battery 1 number of cells] *2 )+ (1~[battery 1 number of temperature] *2)) ) ]"

        # Define variables
        vars = {"battery 1 number of cells": 8, "battery 1 number of temperature": 2}

        # Function to evaluate mathematical expressions
        def evaluate_variables(expression):
            # Define a regular expression pattern to match variables
            var_pattern = re.compile(r"\[([^\[\]]+)\]")

            # Replace variables in the expression with their values
            def replace_vars(match):
                var_name = match.group(1)
                if var_name in vars:
                    return str(vars[var_name])
                else:
                    return match.group(0)

            # Replace variables with their values
            return var_pattern.sub(replace_vars, expression)

        def evaluate_ranges(expression):
            # Define a regular expression pattern to match ranges
            range_pattern = re.compile(r"\[.*?((?P<start>\d+)\s?\~\s?(?P<end>\d+)).*?\]")

            # Find all ranges in the expression
            ranges = range_pattern.findall(expression)

            # If there are no ranges, return the expression as is
            if not ranges:
                return [expression]

            # Initialize list to store results
            results = []

            # Iterate over each range found in the expression
            for group, range_start, range_end in ranges:
                range_start = int(range_start)
                range_end = int(range_end)
                if range_start > range_end:
                    range_start, range_end = range_end, range_start #swap

                # Generate duplicate entries for each value in the range
                for i in range(range_start, range_end + 1):
                    replaced_expression = expression.replace(group, str(i))
                    results.append(replaced_expression)

            return results

        def evaluate_expression(expression):
            # Define a regular expression pattern to match "maths"
            var_pattern = re.compile(r"\[(?P<maths>.*?)\]")

            # Replace variables in the expression with their values
            def replace_vars(match):
                try:
                    maths = match.group("maths")
                    maths = re.sub(r"\s", "", maths) #remove spaces, because ast.parse doesnt like them

                    # Parse the expression safely
                    tree = ast.parse(maths, mode="eval")

                    # Evaluate the expression
                    end_value = ast.literal_eval(compile(tree, filename="", mode="eval"))

                    return str(end_value)
                except Exception:
                    return match.group(0)

            # Replace variables with their values
            return var_pattern.sub(replace_vars, expression)


        # Evaluate the register string
        result = evaluate_variables(register)
        print("Result:", result)

        result = evaluate_ranges(result)
        print("Result:", result)

        results = []
        for r in result:
            results.extend(evaluate_ranges(r))

        for r in results:
            print(evaluate_expression(r))

#settings = protocol_settings('v0.14')
