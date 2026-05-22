#!/usr/bin/env python3


import os
import re
import signal
import subprocess
import paho.mqtt.client as mqtt
import json
import collections
import threading
import datetime
import time
import random
import ev3dev.ev3 as ev3

os.chdir(os.path.dirname(os.path.abspath(__file__)))
signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit()))
mqtt.Client._call_socket_register_write = lambda _self: None
mqtt.Client._call_socket_unregister_write = lambda _self, _sock=None: None


###############################################################################
# Constant declarations                                                       #
###############################################################################
config_path = os.path.join("config.json")
with open(config_path, encoding="utf-8") as config_file:
    config = json.load(
        config_file, object_pairs_hook=lambda p: collections.OrderedDict(p)
    )

STATION_ID = config["station_id"]
NEXT_STATION_IDS = config["next_station_ids"]
GATE_ID = config["gate_id"]
PART_IDS = config["part_ids"]
PART_TYPES = config["part_types"]

STATION_CAPACITY = config["station_capacity"]
NEXT_STATION_CAPACITIES = config["next_station_capacities"]
SETUP_TIME_DISTRIBUTIONS = config["setup_time_distributions"]
PROCESSING_TIME_DISTRIBUTIONS = config["processing_time_distributions"]
FAILURE_PROBABILITY = config["failure_probability"]
REPAIR_TIME_DISTRIBUTION = config["repair_time_distribution"]
ROUTING_POLICIES = config["routing_policies"]
BLOCKING_POLICY = config["blocking_policy"]

MACHINE_SENSOR_PORT = config["machine_sensor_port"]
MACHINE_SENSOR_THRESHOLD = config["machine_sensor_threshold"]

OUTPUT_SENSOR_PORT = config["output_sensor_port"]
OUTPUT_SENSOR_THRESHOLD = config["output_sensor_threshold"]

CONVEYOR_MOTOR_PORT = config["conveyor_motor_port"]
CONVEYOR_MOTOR_POLARITY = config["conveyor_motor_polarity"]
CONVEYOR_MOTOR_SPEED = config["conveyor_motor_speed"]

PUSHER_MOTOR_PORT = config["pusher_motor_port"]
PUSHER_MOTOR_POLARITY = config["pusher_motor_polarity"]
PUSHER_MOTOR_SPEED = config["pusher_motor_speed"]
PUSHER_MOTOR_START_POSITION = 0
PUSHER_MOTOR_END_POSITION = config["pusher_motor_end_position"]
PUSHER_MOTOR_START_DELAY = config["pusher_motor_start_delay"]
PUSHER_MOTOR_END_DELAY = config["pusher_motor_end_delay"]

MACHINE_MOTOR_PORT = config["machine_motor_port"]
MACHINE_MOTOR_POLARITY = config["machine_motor_polarity"]
MACHINE_MOTOR_SPEED = config["machine_motor_speed"]

MQTT_BROKER_HOST = config["mqtt_broker_host"]
MQTT_BROKER_PORT = config["mqtt_broker_port"]

MAIN_EXECUTION_INTERVAL = config["main_execution_interval"]


###############################################################################
# Variable declarations                                                       #
###############################################################################
system_status = "STOP"
station_status = "STOP"
station_wip = collections.OrderedDict([(type_, 0) for type_ in PART_TYPES.values()])
station_total_wip = 0
routing_lock = threading.Lock()
next_station_id = None
pattern_indices = collections.OrderedDict(
    [(type_, -1) for type_ in PART_TYPES.values()]
)
next_station_wips = collections.OrderedDict(
    [(id_, station_wip.copy()) for id_ in NEXT_STATION_IDS]
)
next_station_total_wips = collections.OrderedDict(
    [(id_, 0) for id_ in NEXT_STATION_IDS]
)
blocking_lock = threading.Lock()
blocking_queue = list()
is_blocked = None
input_part_id = None
input_part_type = None
part_id = None
part_type = None
previous_part_id = None
previous_part_type = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT with code " + str(rc))
    topic = render_topic("system_time", "master", "all")
    client.subscribe(topic, qos=2)
    topic = render_topic("system_status", "master", "all")
    client.subscribe(topic, qos=2)
    topic = render_topic("component_wip", "master", STATION_ID)
    client.subscribe(topic, qos=2)
    for id_ in NEXT_STATION_IDS:
        topic = render_topic("component_wip", "master", id_)
        client.subscribe(topic, qos=2)
        topic = render_topic("component_event", id_, "all")
        client.subscribe(topic, qos=2)
    topic = render_topic("component_vacancy", "+", STATION_ID)
    client.subscribe(topic, qos=2)
    topic = render_topic("part_uid", STATION_ID, "all")
    client.subscribe(topic, qos=2)


def on_message(client, userdata, msg):
    global system_status
    global station_wip
    global station_total_wip
    global is_blocked
    global input_part_id
    global input_part_type

    context, source_id, target_id = parse_topic(msg.topic)
    payload = msg.payload.decode("utf-8")
    if context == "system_time":
        os.system("sudo date -s " + payload)
    elif context == "system_status":
        status = payload.upper()
        if status in ["STOP", "START"]:
            system_status = status
    else:
        if system_status == "STOP":
            if context == "component_wip":
                if target_id == STATION_ID:
                    station_wip = deserialize_object(payload)
                    station_total_wip = sum(station_wip.values())
                if target_id in NEXT_STATION_IDS:
                    next_station_wips[target_id] = deserialize_object(payload)
                    next_station_total_wips[target_id] = sum(
                        next_station_wips[target_id].values()
                    )
        else:
            if context == "component_event":
                event = deserialize_object(payload)
                part_type_ = event["part_type"]
                activity = event["activity"]
                if activity == "TRANSFER":
                    with routing_lock:
                        next_station_wips[source_id][part_type_] -= 1
                        next_station_total_wips[source_id] -= 1
            elif context == "component_vacancy":
                packet = deserialize_object(payload)
                code = packet["code"]
                if code == "BOOK":
                    part_type_ = packet["data"]
                    with blocking_lock:
                        if station_total_wip < STATION_CAPACITY:
                            packet = build_packet("ACCEPT")
                            topic = render_topic(
                                "component_vacancy", STATION_ID, source_id
                            )
                            payload = serialize_object(packet)
                            client.publish(topic, payload=payload, qos=2)
                            station_wip[part_type_] += 1
                            station_total_wip += 1
                        else:
                            packet = build_packet("SUSPEND")
                            topic = render_topic(
                                "component_vacancy", STATION_ID, source_id
                            )
                            payload = serialize_object(packet)
                            client.publish(topic, payload=payload, qos=2)
                            blocking_queue.append([source_id, part_type_])
                elif code == "ACCEPT":
                    is_blocked = False
                elif code == "SUSPEND":
                    is_blocked = True
            elif context == "part_uid":
                input_part_id = PART_IDS[payload]
                input_part_type = PART_TYPES[payload]


def render_topic(context, source_id, target_id):
    return "/".join([context, source_id, target_id])


def parse_topic(topic):
    return tuple(topic.split("/"))


def build_event(station_id, part_id_, part_type_, activity):
    event = collections.OrderedDict()
    event["time"] = datetime.datetime.now().isoformat()
    event["station_id"] = station_id
    event["part_id"] = part_id_
    event["part_type"] = part_type_
    event["activity"] = activity
    return event


def build_packet(code, data=None):
    packet = collections.OrderedDict()
    packet["code"] = code
    packet["data"] = data
    return packet


def serialize_object(object_):
    return json.dumps(object_, separators=(",", ":"))


def deserialize_object(string):
    return json.loads(string, object_pairs_hook=lambda p: collections.OrderedDict(p))


def sleep(duration=float("inf"), condition=lambda: True):
    end_time = time.time() + duration
    while time.time() < end_time and condition():
        time.sleep(0.05)


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


def get_next_station_id(policy):
    if policy is None:
        return NEXT_STATION_IDS[0]
    else:
        type_ = policy["type"]
        parameters = policy["parameters"]
        if type_ == "PATTERN":
            return choose_by_pattern(parameters)
        elif type_ == "PROBABILITY":
            return choose_by_probability(parameters)
        elif type_ == "PRIORITY":
            return choose_by_priority(parameters)
        elif type_ == "JSQ":
            return choose_by_jsq(parameters)
        else:
            raise RuntimeError("Unknown routing policy: " + type_)


def choose_by_pattern(pattern):
    pattern_indices[part_type] += 1
    pattern_indices[part_type] %= len(pattern)
    return pattern[pattern_indices[part_type]]


def choose_by_probability(probabilities):
    cum = 0.0
    sample = random.random()
    id_ = None
    for id_, probability in probabilities.items():
        cum += probability
        if sample < cum:
            break
    return id_


def choose_by_priority(priority):
    id_ = None
    for id_ in priority:
        if next_station_total_wips[id_] < NEXT_STATION_CAPACITIES[id_]:
            break
    return id_


def choose_by_jsq(_):
    min_wip = float("inf")
    min_ids = list()
    for id_ in NEXT_STATION_IDS:
        if next_station_total_wips[id_] < min_wip:
            min_wip = next_station_total_wips[id_]
            min_ids.clear()
            min_ids.append(id_)
        elif next_station_total_wips[id_] == min_wip:
            min_ids.append(id_)
    return random.choice(min_ids)


###############################################################################
# Device initialization                                                       #
###############################################################################
ev3.Leds.AMBER = (0.5, 0.5)
ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.GREEN)
ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.GREEN)

machine_sensor = ev3.ColorSensor(MACHINE_SENSOR_PORT)
machine_sensor.mode = ev3.ColorSensor.MODE_COL_REFLECT

output_sensor = ev3.ColorSensor(OUTPUT_SENSOR_PORT)
output_sensor.mode = ev3.ColorSensor.MODE_COL_REFLECT

conveyor_motor = ev3.LargeMotor(CONVEYOR_MOTOR_PORT)
conveyor_motor.reset()
conveyor_motor.polarity = CONVEYOR_MOTOR_POLARITY
conveyor_motor.speed_sp = CONVEYOR_MOTOR_SPEED
conveyor_motor.stop_action = ev3.Motor.STOP_ACTION_BRAKE

pusher_motor = ev3.MediumMotor(PUSHER_MOTOR_PORT)
pusher_motor.reset()
pusher_motor.polarity = PUSHER_MOTOR_POLARITY
pusher_motor.speed_sp = PUSHER_MOTOR_SPEED
pusher_motor.stop_action = ev3.Motor.STOP_ACTION_BRAKE

machine_motor = ev3.LargeMotor(MACHINE_MOTOR_PORT)
machine_motor.reset()
machine_motor.polarity = MACHINE_MOTOR_POLARITY
machine_motor.speed_sp = MACHINE_MOTOR_SPEED
machine_motor.stop_action = ev3.Motor.STOP_ACTION_BRAKE

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER_HOST, port=MQTT_BROKER_PORT)
mqtt_client.loop_start()


###############################################################################
# Program execution                                                           #
###############################################################################
program_pid = str(os.getpid())
with open("program.pid", "w") as file:
    file.write(program_pid + "\n")
print("Station " + STATION_ID + " program started")

try:
    while True:
        sleep(duration=MAIN_EXECUTION_INTERVAL)
        if system_status == "STOP":
            if station_status == "START":
                ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.GREEN)
                ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.GREEN)
                conveyor_motor.stop()
                machine_motor.stop()
                for type_ in PART_TYPES.values():
                    station_wip[type_] = 0
                station_total_wip = 0
                next_station_id = None
                for type_ in PART_TYPES.values():
                    pattern_indices[type_] = -1
                for id_ in NEXT_STATION_IDS:
                    for type_ in PART_TYPES.values():
                        next_station_wips[id_][type_] = 0
                    next_station_total_wips[id_] = 0
                blocking_queue.clear()
                is_blocked = None
                input_part_id = None
                input_part_type = None
                part_id = None
                part_type = None
                previous_part_id = None
                previous_part_type = None
                station_status = "STOP"
                print("Station " + STATION_ID + " stopped")
        else:
            if station_status == "STOP":
                conveyor_motor.run_forever()
                conveyor_motor.wait_until(ev3.Motor.STATE_RUNNING)
                machine_motor.run_forever()
                machine_motor.wait_until(ev3.Motor.STATE_RUNNING)
                station_status = "START"
                print("Station " + STATION_ID + " started")

            sleep(
                condition=lambda: (
                    system_status == "START"
                    and (input_part_id is None or input_part_type is None)
                )
            )
            if system_status == "STOP":
                continue
            previous_part_id = part_id
            previous_part_type = part_type
            part_id = input_part_id
            part_type = input_part_type
            input_part_id = None
            input_part_type = None

            if BLOCKING_POLICY["type"] == "BBS":
                with routing_lock:
                    next_station_id = get_next_station_id(ROUTING_POLICIES[part_type])
                is_blocked = None
                vacancy_packet = build_packet("BOOK", data=part_type)
                mqtt_topic = render_topic(
                    "component_vacancy", STATION_ID, next_station_id
                )
                mqtt_payload = serialize_object(vacancy_packet)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                sleep(condition=lambda: system_status == "START" and is_blocked is None)
                if system_status == "STOP":
                    continue

                if is_blocked:
                    station_event = build_event(STATION_ID, part_id, part_type, "BLOCK")
                    mqtt_topic = render_topic("component_event", STATION_ID, "all")
                    mqtt_payload = serialize_object(station_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    sleep(condition=lambda: system_status == "START" and is_blocked)
                    if system_status == "STOP":
                        continue

            ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.AMBER)
            ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.AMBER)

            station_event = build_event(STATION_ID, part_id, part_type, "LOAD")
            mqtt_topic = render_topic("component_event", STATION_ID, "all")
            mqtt_payload = serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            sleep(duration=PUSHER_MOTOR_START_DELAY)
            pusher_motor.run_to_abs_pos(position_sp=PUSHER_MOTOR_END_POSITION)
            pusher_motor.wait_until(ev3.Motor.STATE_RUNNING)
            pusher_motor.wait_until_not_moving()
            sleep(duration=PUSHER_MOTOR_END_DELAY)
            pusher_motor.run_to_abs_pos(position_sp=PUSHER_MOTOR_START_POSITION)
            pusher_motor.wait_until(ev3.Motor.STATE_RUNNING)
            pusher_motor.wait_until_not_moving()

            sleep(condition=lambda: (machine_sensor.value() < MACHINE_SENSOR_THRESHOLD))
            machine_motor.stop()
            if system_status == "STOP":
                continue

            if previous_part_type is None:
                setup_time_distribution = (
                    SETUP_TIME_DISTRIBUTIONS[part_type][part_type]
                )
            else:
                setup_time_distribution = (
                    SETUP_TIME_DISTRIBUTIONS[previous_part_type][part_type]
                )
            if setup_time_distribution is not None:
                station_event = build_event(STATION_ID, part_id, part_type, "SETUP")
                mqtt_topic = render_topic("component_event", STATION_ID, "all")
                mqtt_payload = serialize_object(station_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                setup_time = get_random_sample(setup_time_distribution)
                sleep(duration=setup_time, condition=lambda: system_status == "START")
                if system_status == "STOP":
                    continue

            station_event = build_event(STATION_ID, part_id, part_type, "PROCESS")
            mqtt_topic = render_topic("component_event", STATION_ID, "all")
            mqtt_payload = serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            processing_time = get_random_sample(
                PROCESSING_TIME_DISTRIBUTIONS[part_type]
            )
            sleep(duration=processing_time, condition=lambda: system_status == "START")
            if system_status == "STOP":
                continue

            if random.random() < FAILURE_PROBABILITY:
                ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.RED)
                ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.RED)

                station_event = build_event(STATION_ID, part_id, part_type, "FAIL")
                mqtt_topic = render_topic("component_event", STATION_ID, "all")
                mqtt_payload = serialize_object(station_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                repair_time = get_random_sample(REPAIR_TIME_DISTRIBUTION)
                sleep(duration=repair_time, condition=lambda: system_status == "START")
                if system_status == "STOP":
                    continue

                ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.AMBER)
                ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.AMBER)

            station_event = build_event(STATION_ID, part_id, part_type, "UNLOAD")
            mqtt_topic = render_topic("component_event", STATION_ID, "all")
            mqtt_payload = serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            machine_motor.run_forever()
            machine_motor.wait_until(ev3.Motor.STATE_RUNNING)
            sleep(condition=lambda: (output_sensor.value() < OUTPUT_SENSOR_THRESHOLD))
            if system_status == "STOP":
                continue

            ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.GREEN)
            ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.GREEN)

            if BLOCKING_POLICY["type"] == "BAS":
                machine_motor.stop()
                with routing_lock:
                    next_station_id = get_next_station_id(ROUTING_POLICIES[part_type])
                is_blocked = None
                vacancy_packet = build_packet("BOOK", data=part_type)
                mqtt_topic = render_topic(
                    "component_vacancy", STATION_ID, next_station_id
                )
                mqtt_payload = serialize_object(vacancy_packet)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                sleep(condition=lambda: system_status == "START" and is_blocked is None)
                if system_status == "STOP":
                    continue

                if is_blocked:
                    station_event = build_event(STATION_ID, part_id, part_type, "BLOCK")
                    mqtt_topic = render_topic("component_event", STATION_ID, "all")
                    mqtt_payload = serialize_object(station_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    sleep(condition=lambda: system_status == "START" and is_blocked)
                    if system_status == "STOP":
                        continue
                machine_motor.run_forever()

            if GATE_ID is not None:
                mqtt_topic = render_topic("next_component_id", STATION_ID, GATE_ID)
                mqtt_client.publish(mqtt_topic, payload=next_station_id, qos=2)

            station_event = build_event(STATION_ID, part_id, part_type, "TRANSFER")
            mqtt_topic = render_topic("component_event", STATION_ID, "all")
            mqtt_payload = serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            with blocking_lock:
                station_wip[part_type] -= 1
                station_total_wip -= 1
                next_station_wips[next_station_id][part_type] += 1
                next_station_total_wips[next_station_id] += 1
                if station_total_wip < STATION_CAPACITY and len(blocking_queue) > 0:
                    blocked_station_id, blocked_part_type = blocking_queue.pop(0)
                    vacancy_packet = build_packet("ACCEPT")
                    mqtt_topic = render_topic(
                        "component_vacancy", STATION_ID, blocked_station_id
                    )
                    mqtt_payload = serialize_object(vacancy_packet)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)
                    station_wip[blocked_part_type] += 1
                    station_total_wip += 1
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    system_status = "STOP"
    station_status = "STOP"

    ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.GREEN)
    ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.GREEN)
    conveyor_motor.stop()
    machine_motor.stop()
    pusher_motor.stop()
    if abs(PUSHER_MOTOR_START_POSITION - pusher_motor.position) > 0:
        pusher_motor.run_to_abs_pos(position_sp=PUSHER_MOTOR_START_POSITION)
        pusher_motor.wait_until(ev3.Motor.STATE_RUNNING)
        pusher_motor.wait_until_not_moving()

    os.remove("program.pid")
    print("Station " + STATION_ID + " program stopped")
