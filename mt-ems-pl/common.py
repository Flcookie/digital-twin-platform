import json
import buildhat
import collections
import sys
import traceback
import signal
import datetime
import threading
import time
import random
import adafruit_pn532.adafruit_pn532 as pn532
import adafruit_pn532.uart as pn532_uart
import serial
import math
import struct


###############################################################################
# Constant declarations                                                       #
###############################################################################
SLEEP_TIME_RESOLUTION = 0.1
UART_DEFAULT_BAUDRATE = 115200
UART_READ_TIMEOUT = 0.1
COMMAND_ACK_TIMEOUT = 0.1
BAUDRATE_BYTECODES = {
    9600: b"\x00", 19200: b"\x01", 38400: b"\x02", 57600: b"\x03", 115200: b"\x04"
}
NUMBER_OF_RETRIES = 2
RETRY_INTERVAL = 0.1
META_BLOCK_INDEX = 1
DATA_BLOCK_INDICES = [index for index in range(4, 64) if (index + 1) % 4 != 0]
WRITE_ENDURANCE = 200000


###############################################################################
# Function definitions                                                        #
###############################################################################
def load_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file, object_pairs_hook=lambda p: collections.OrderedDict(p))


def excepthook(args):
    if args.thread == buildhat.Motor._instance.cb:
        instance_ = buildhat.Motor._instance
        instance_.cb = threading.Thread(
            target=instance_.callbackloop, args=(instance_.cbqueue,)
        )
        instance_.cb.daemon = True
        instance_.cb.start()
    elif args.thread == buildhat.Motor._instance.th:
        instance_ = buildhat.Motor._instance
        listevt = threading.Event()
        listevt.set()
        instance_.th = threading.Thread(
            target=instance_.loop,
            args=(instance_.cond, instance_.state == 1, instance_.cbqueue, listevt),
        )
        instance_.th.daemon = True
        instance_.th.start()
    else:
        print("Exception in thread " + args.thread.name, file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
        signal.raise_signal(signal.SIGINT)


def render_topic(context, source_id, target_id):
    return "/".join([context, source_id, target_id])


def parse_topic(topic):
    return tuple(topic.split("/"))


def build_event(component_id, part_id_, activity):
    event = collections.OrderedDict()
    event["time"] = datetime.datetime.now().isoformat()
    event["component_id"] = component_id
    event["part_id"] = part_id_
    event["activity"] = activity
    return event


def serialize_object(object_):
    return json.dumps(object_, separators=(",", ":"))


def deserialize_object(string):
    return json.loads(string, object_pairs_hook=lambda p: collections.OrderedDict(p))


def sleep(duration=float("inf"), condition=lambda: True):
    end_time = time.time() + duration
    while time.time() < end_time and condition():
        time.sleep(SLEEP_TIME_RESOLUTION)


def get_random_sample(distribution):
    type_ = distribution["type"]
    parameters = distribution["parameters"]
    if type_ == "DETERMINISTIC":
        return parameters[0]
    elif type_ == "UNIFORM":
        return random.uniform(parameters[0], parameters[1])
    elif type_ == "TRIANGULAR":
        return random.triangular(parameters[0], parameters[1], parameters[2])
    elif type_ == "BETA":
        return random.betavariate(parameters[0], parameters[1])
    elif type_ == "EXPONENTIAL":
        return random.expovariate(parameters[0])
    elif type_ == "GAMMA":
        return random.gammavariate(parameters[0], parameters[1])
    elif type_ == "LOG_NORMAL":
        return random.lognormvariate(parameters[0], parameters[1])
    elif type_ == "NORMAL":
        return random.normalvariate(parameters[0], parameters[1])
    elif type_ == "VON_MISES":
        return random.vonmisesvariate(parameters[0], parameters[1])
    elif type_ == "PARETO":
        return random.paretovariate(parameters[0])
    elif type_ == "WEIBULL":
        return random.weibullvariate(parameters[0], parameters[1])
    elif type_ == "REPLAYER":
        if "samples" not in distribution.keys() or "index" not in distribution.keys():
            with open(parameters[0], encoding="utf-8") as file:
                segments = file.read().strip().split(parameters[1])
                distribution["samples"] = [float(segment) for segment in segments]
                distribution["index"] = len(distribution["samples"]) - 1
        samples = distribution["samples"]
        index = distribution["index"]
        index = (index + 1) % len(samples)
        distribution["index"] = index
        return samples[index]
    else:
        raise RuntimeError("Unknown distribution: " + type_)


###############################################################################
# Class definitions                                                           #
###############################################################################
class Sensor(pn532_uart.PN532_UART):
    def __init__(self, port, baudrate, reset=None, debug=False):
        try:
            uart = serial.Serial(
                port=port, baudrate=baudrate, timeout=UART_READ_TIMEOUT
            )
            super().__init__(uart, reset=reset, debug=debug)
        except RuntimeError:
            uart = serial.Serial(
                port=port, baudrate=UART_DEFAULT_BAUDRATE, timeout=UART_READ_TIMEOUT
            )
            super().__init__(uart, reset=reset, debug=debug)
            self.set_baudrate(baudrate)

    def call_function(self, command, response_length=0, params=b"", timeout=1):
        count = 0
        while True:
            try:
                if not self.send_command(
                    command, params=params, timeout=COMMAND_ACK_TIMEOUT
                ):
                    raise RuntimeError("Failed to send command to PN532")
                return self.process_response(
                    command, response_length=response_length, timeout=timeout
                )
            except RuntimeError as error:
                count += 1
                if count <= NUMBER_OF_RETRIES:
                    time.sleep(RETRY_INTERVAL)
                else:
                    raise error

    def send_ack(self):
        self._write_data(pn532._ACK)

    def set_baudrate(self, value):
        self.call_function(
            pn532._COMMAND_SETSERIALBAUDRATE, params=BAUDRATE_BYTECODES[value]
        )
        self.send_ack()
        time.sleep(0.01)
        self._uart.baudrate = value

    def RF_configuration(self, max_retries):
        self.call_function(
            pn532._COMMAND_RFCONFIGURATION,
            params=b"\x05\x02\x01" + bytes([max_retries]),
        )

    def read_passive_target(self, card_baud=pn532._MIFARE_ISO14443A, timeout=1):
        count = 0
        while True:
            try:
                response = self.listen_for_passive_target(
                    card_baud=card_baud, timeout=COMMAND_ACK_TIMEOUT
                )
                if not response:
                    return None
                return self.get_passive_target(timeout=timeout)
            except RuntimeError as error:
                count += 1
                if count <= NUMBER_OF_RETRIES:
                    time.sleep(RETRY_INTERVAL)
                else:
                    raise error

    def get_passive_target(self, timeout=1):
        response = self.process_response(
            pn532._COMMAND_INLISTPASSIVETARGET, response_length=30, timeout=timeout
        )
        if response is None or response[0] == 0x00:
            return None
        if response[0] > 0x01:
            raise RuntimeError("More than one card detected!")
        if response[5] > 7:
            raise RuntimeError("Found card with unexpectedly long UID!")
        return response[6:6 + response[5]]

    def release_passive_target(self):
        self.call_function(pn532._COMMAND_INRELEASE, response_length=1, params=b"\x00")

    def read_block(self, uid, index):
        if self.mifare_classic_authenticate_block(
            uid, index, pn532.MIFARE_CMD_AUTH_A, b"\xFF\xFF\xFF\xFF\xFF\xFF"
        ):
            block = self.mifare_classic_read_block(index)
            if block is not None:
                return block
        return None

    def write_block(self, uid, index, buffer):
        if self.mifare_classic_authenticate_block(
            uid, index, pn532.MIFARE_CMD_AUTH_A, b"\xFF\xFF\xFF\xFF\xFF\xFF"
        ):
            if self.mifare_classic_write_block(index, buffer):
                return True
        return False

    def format_memory(self, uid, schema, properties):
        meta_buffer = bytearray(
            b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF"
        )
        group_index = 0
        number_of_groups = math.ceil(len(schema) / 3)
        counts = [0 for _ in range(number_of_groups)]
        for block_index in DATA_BLOCK_INDICES:
            data_block = self.read_block(uid, block_index)
            if data_block is None:
                return False
            if data_block[12:16] == b"\xFF\xFF\xFF\xFF":
                count = 0
            else:
                count = struct.unpack("I", data_block[12:16])[0]
            if count < WRITE_ENDURANCE:
                meta_buffer[group_index] = block_index
                counts[group_index] = count
                group_index += 1
                if group_index >= number_of_groups:
                    break
        if group_index < number_of_groups:
            return False
        if not self.write_block(uid, META_BLOCK_INDEX, meta_buffer):
            return False

        property_index = 0
        data_buffer = bytearray(16)
        for name in schema.keys():
            if property_index % 3 == 0:
                data_buffer[:] = (
                    b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF"
                )
            group_index = math.floor(property_index / 3)
            start = 4 * (property_index - group_index * 3)
            end = start + 4
            value = properties[name]
            if schema[name]["type"] == "bool":
                data = struct.pack("?", value)
                data += b"\x00\x00\x00"
            elif schema[name]["type"] == "int":
                data = struct.pack("i", value)
            elif schema[name]["type"] == "float":
                data = struct.pack("f", value)
            elif schema[name]["type"] == "str":
                data = value.encode("utf-8")
                for _ in range(len(data), 4):
                    data += b"\x00"
                data = data[:4]
            else:
                raise RuntimeError("Unsupported property type: " + schema[name]["type"])
            data_buffer[start:end] = data

            if (property_index + 1) % 3 == 0 or property_index >= len(schema) - 1:
                block_index = meta_buffer[group_index]
                counts[group_index] += 1
                data_buffer[12:16] = struct.pack("I", counts[group_index])
                if not self.write_block(uid, block_index, data_buffer):
                    return False
            property_index += 1

        return True

    def get_property(self, uid, schema, name):
        meta_block = self.read_block(uid, META_BLOCK_INDEX)
        if meta_block is None:
            return None
        property_index = schema[name]["index"]
        group_index = math.floor(property_index / 3)
        block_index = meta_block[group_index]
        data_block = self.read_block(uid, block_index)
        if data_block is None:
            return None

        start = 4 * (property_index - group_index * 3)
        end = start + 4
        data = data_block[start:end]
        if schema[name]["type"] == "bool":
            value = struct.unpack("????", data)[0]
        elif schema[name]["type"] == "int":
            value = struct.unpack("i", data)[0]
        elif schema[name]["type"] == "float":
            value = struct.unpack("f", data)[0]
        elif schema[name]["type"] == "str":
            value = data.decode("utf-8").rstrip("\0")
        else:
            raise RuntimeError("Unsupported property type: " + schema[name]["type"])

        return value

    def get_properties(self, uid, schema):
        meta_block = self.read_block(uid, META_BLOCK_INDEX)
        if meta_block is None:
            return None
        number_of_groups = math.ceil(len(schema) / 3)
        names = list(schema.keys())
        properties = collections.OrderedDict()
        for group_index in range(number_of_groups):
            block_index = meta_block[group_index]
            data_block = self.read_block(uid, block_index)
            if data_block is None:
                return None

            property_indices = range(
                group_index * 3, min(group_index * 3 + 3, len(schema))
            )
            for property_index in property_indices:
                name = names[property_index]
                start = 4 * (property_index - group_index * 3)
                end = start + 4
                data = data_block[start:end]
                if schema[name]["type"] == "bool":
                    value = struct.unpack("????", data)[0]
                elif schema[name]["type"] == "int":
                    value = struct.unpack("i", data)[0]
                elif schema[name]["type"] == "float":
                    value = struct.unpack("f", data)[0]
                elif schema[name]["type"] == "str":
                    value = data.decode("utf-8").rstrip("\0")
                else:
                    raise RuntimeError(
                        "Unsupported property type: " + schema[name]["type"]
                    )
                properties[name] = value

        return properties

    def set_property(self, uid, schema, name, value):
        meta_block = self.read_block(uid, META_BLOCK_INDEX)
        if meta_block is None:
            return False
        property_index = schema[name]["index"]
        group_index = math.floor(property_index / 3)
        block_index = meta_block[group_index]
        data_block = self.read_block(uid, block_index)
        if data_block is None:
            return False

        data_buffer = bytearray(data_block)
        start = 4 * (property_index - group_index * 3)
        end = start + 4
        if schema[name]["type"] == "bool":
            data = struct.pack("?", value)
            data += b"\x00\x00\x00"
        elif schema[name]["type"] == "int":
            data = struct.pack("i", value)
        elif schema[name]["type"] == "float":
            data = struct.pack("f", value)
        elif schema[name]["type"] == "str":
            data = value.encode("utf-8")
            for _ in range(len(data), 4):
                data += b"\x00"
            data = data[:4]
        else:
            raise RuntimeError("Unsupported property type: " + schema[name]["type"])
        data_buffer[start:end] = data

        count = struct.unpack("I", data_buffer[12:16])[0]
        if count < WRITE_ENDURANCE:
            count += 1
        else:
            number_of_groups = math.ceil(len(schema) / 3)
            block_index = max(meta_block[:number_of_groups]) + 1
            if block_index >= 64:
                RuntimeError("No more spare blocks")
            meta_buffer = bytearray(meta_block)
            meta_buffer[group_index] = block_index
            if not self.write_block(uid, META_BLOCK_INDEX, meta_buffer):
                return False
            count = 1
        data_buffer[12:16] = struct.pack("I", count)

        if not self.write_block(uid, block_index, data_buffer):
            return False

        return True

    def set_properties(self, uid, schema, properties):
        meta_block = self.read_block(uid, META_BLOCK_INDEX)
        if meta_block is None:
            return False
        number_of_groups = math.ceil(len(schema) / 3)
        names = list(schema.keys())
        for group_index in range(number_of_groups):
            block_index = meta_block[group_index]
            data_block = self.read_block(uid, block_index)
            if data_block is None:
                return False

            property_indices = range(
                group_index * 3, min(group_index * 3 + 3, len(schema))
            )
            data_buffer = bytearray(data_block)
            for property_index in property_indices:
                name = names[property_index]
                value = properties[name]
                start = 4 * (property_index - group_index * 3)
                end = start + 4
                if schema[name]["type"] == "bool":
                    data = struct.pack("?", value)
                    data += b"\x00\x00\x00"
                elif schema[name]["type"] == "int":
                    data = struct.pack("i", value)
                elif schema[name]["type"] == "float":
                    data = struct.pack("f", value)
                elif schema[name]["type"] == "str":
                    data = value.encode("utf-8")
                    for _ in range(len(data), 4):
                        data += b"\x00"
                    data = data[:4]
                else:
                    raise RuntimeError(
                        "Unsupported property type: " + schema[name]["type"]
                    )
                data_buffer[start:end] = data

            count = struct.unpack("I", data_buffer[12:16])[0]
            if count < WRITE_ENDURANCE:
                count += 1
            else:
                number_of_groups = math.ceil(len(schema) / 3)
                block_index = max(meta_block[:number_of_groups]) + 1
                if block_index >= 64:
                    RuntimeError("No more spare blocks")
                meta_buffer = bytearray(meta_block)
                meta_buffer[group_index] = block_index
                if not self.write_block(uid, META_BLOCK_INDEX, meta_buffer):
                    return False
                count = 1
            data_buffer[12:16] = struct.pack("I", count)

            if not self.write_block(uid, block_index, data_buffer):
                return False

        return True


class Motor(buildhat.Motor):
    _write_lock = threading.Lock()

    def get_end_position(self, degrees):
        if self.default_speed < 0:
            return self.get_position() - degrees
        else:
            return self.get_position() + degrees

    def run_to_position(self, position, speed=None, block=True, _=None):
        if self.default_speed < 0:
            self.run_for_degrees(self.get_position() - position)
        else:
            self.run_for_degrees(position - self.get_position())

    def run_to_aposition(self, degrees, speed=None, blocking=True, direction="shortest"):
        super().run_to_position(degrees, speed=speed, blocking=blocking, direction=direction)

    def _write(self, cmd):
        self.isconnected()
        with Motor._write_lock:
            Motor._instance.write(cmd.encode())


class MotorPair(buildhat.MotorPair):
    def __init__(self, leftport, rightport):
        self._leftmotor = Motor(leftport)
        self._rightmotor = Motor(rightport)
        self._release = True
        self._rpm = False
        self.default_speedl = 20
        self.default_speedr = -20

    def __del__(self):
        self._leftmotor.__del__()
        self._rightmotor.__del__()

    def set_default_speed(self, default_speedl=20, default_speedr=-20):
        self.default_speedl = default_speedl
        self.default_speedr = default_speedr

    def plimit(self, plimit):
        self._leftmotor.plimit(plimit)
        self._rightmotor.plimit(plimit)

    def run_for_rotations(self, rotations, speedl=None, speedr=None):
        if speedl is None:
            speedl = self.default_speedl
        if speedr is None:
            speedr = self.default_speedr
        super().run_for_rotations(rotations, speedl, speedr)

    def run_for_degrees(self, degrees, speedl=None, speedr=None):
        if speedl is None:
            speedl = self.default_speedl
        if speedr is None:
            speedr = self.default_speedr
        super().run_for_degrees(degrees, speedl, speedr)

    def run_for_seconds(self, seconds, speedl=None, speedr=None):
        if speedl is None:
            speedl = self.default_speedl
        if speedr is None:
            speedr = self.default_speedr
        super().run_for_seconds(seconds, speedl, speedr)

    def start(self, speedl=None, speedr=None):
        if speedl is None:
            speedl = self.default_speedl
        if speedr is None:
            speedr = self.default_speedr
        super().start(speedl, speedr)

    def coast(self):
        self._leftmotor.coast()
        self._rightmotor.coast()

    def run_to_position(self, degreesl, degreesr, speedl=None, speedr=None, direction="shortest"):
        if speedl is None:
            speedl = self.default_speedl
        if speedr is None:
            speedr = self.default_speedr
        th1 = threading.Thread(target=self._leftmotor._run_to_position, args=(degreesl, speedl, direction))
        th2 = threading.Thread(target=self._rightmotor._run_to_position, args=(degreesr, speedr, direction))
        th1.daemon = True
        th2.daemon = True
        th1.start()
        th2.start()
        th1.join()
        th2.join()
