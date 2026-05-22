import os
import signal
import common
import collections
import threading
import random
import paho.mqtt.client as mqtt

os.chdir(os.path.dirname(os.path.abspath(__file__)))
signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit()))


###############################################################################
# Constant declarations                                                       #
###############################################################################
CONFIG = common.load_json("config.json")
SCHEMA = common.load_json("schema.json")

STATION_ID = CONFIG["station_id"]
NEXT_STATION_IDS = CONFIG["next_station_ids"]
GATE_ID = CONFIG["gate_id"]
PART_TYPES = CONFIG["part_types"]

STATION_CAPACITY = CONFIG["station_capacity"]
NEXT_STATION_CAPACITIES = CONFIG["next_station_capacities"]
SETUP_TIME_DISTRIBUTIONS = CONFIG["setup_time_distributions"]
PROCESSING_TIME_DISTRIBUTIONS = CONFIG["processing_time_distributions"]
FAILURE_PROBABILITY = CONFIG["failure_probability"]
REPAIR_TIME_DISTRIBUTION = CONFIG["repair_time_distribution"]
ROUTING_POLICIES = CONFIG["routing_policies"]
BLOCKING_POLICY = CONFIG["blocking_policy"]

INPUT_SENSOR_PORT = CONFIG["input_sensor_port"]
INPUT_SENSOR_BAUDRATE = CONFIG["input_sensor_baudrate"]

MACHINE_SENSOR_PORT = CONFIG["machine_sensor_port"]
MACHINE_SENSOR_BAUDRATE = CONFIG["machine_sensor_baudrate"]

OUTPUT_SENSOR_PORT = CONFIG["output_sensor_port"]
OUTPUT_SENSOR_BAUDRATE = CONFIG["output_sensor_baudrate"]

CONVEYOR_MOTOR_PORT = CONFIG["conveyor_motor_port"]
CONVEYOR_MOTOR_PLIMIT = CONFIG["conveyor_motor_plimit"]
CONVEYOR_MOTOR_SPEED = CONFIG["conveyor_motor_speed"]

PUSHER_MOTOR_PORT = CONFIG["pusher_motor_port"]
PUSHER_MOTOR_PLIMIT = CONFIG["pusher_motor_plimit"]
PUSHER_MOTOR_SPEED = CONFIG["pusher_motor_speed"]
PUSHER_MOTOR_RUN_DEGREES = CONFIG["pusher_motor_run_degrees"]
PUSHER_MOTOR_START_DELAY = CONFIG["pusher_motor_start_delay"]
PUSHER_MOTOR_END_DELAY = CONFIG["pusher_motor_end_delay"]

MACHINE_MOTOR_PORT = CONFIG["machine_motor_port"]
MACHINE_MOTOR_PLIMIT = CONFIG["machine_motor_plimit"]
MACHINE_MOTOR_SPEED = CONFIG["machine_motor_speed"]

MQTT_BROKER_HOST = CONFIG["mqtt_broker_host"]
MQTT_BROKER_PORT = CONFIG["mqtt_broker_port"]

MAIN_EXECUTION_INTERVAL = CONFIG["main_execution_interval"]


###############################################################################
# Variable declarations                                                       #
###############################################################################
system_status = "STOP"
station_status = "STOP"
station_wip = collections.OrderedDict([(type_, 0) for type_ in PART_TYPES])
station_total_wip = 0
routing_lock = threading.Lock()
next_station_id = None
pattern_indices = collections.OrderedDict([(type_, -1) for type_ in PART_TYPES])
next_station_wips = collections.OrderedDict(
    [(id_, station_wip.copy()) for id_ in NEXT_STATION_IDS]
)
next_station_total_wips = collections.OrderedDict(
    [(id_, 0) for id_ in NEXT_STATION_IDS]
)
blocking_lock = threading.Lock()
blocking_queue = list()
is_blocked = None
part_uid = None
part_id = None
part_type = None
previous_part_uid = None
previous_part_id = None
previous_part_type = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT with code " + str(rc))
    topic = common.render_topic("system_time", "master", "all")
    client.subscribe(topic, qos=2)
    topic = common.render_topic("system_status", "master", "all")
    client.subscribe(topic, qos=2)
    topic = common.render_topic("component_wip", "master", STATION_ID)
    client.subscribe(topic, qos=2)
    for id_ in NEXT_STATION_IDS:
        topic = common.render_topic("component_wip", "master", id_)
        client.subscribe(topic, qos=2)
        topic = common.render_topic("component_event", id_, "all")
        client.subscribe(topic, qos=2)
    topic = common.render_topic("component_vacancy", "+", STATION_ID)
    client.subscribe(topic, qos=2)
    topic = common.render_topic("part_memory", "master", STATION_ID)
    client.subscribe(topic, qos=2)


def on_message(client, userdata, msg):
    global system_status
    global station_wip
    global station_total_wip
    global is_blocked

    context, source_id, target_id = common.parse_topic(msg.topic)
    payload = msg.payload.decode("utf-8")
    if context == "system_time":
        common.safe_set_system_time(payload, "[station] ")
    elif context == "system_status":
        status = payload.upper()
        if status in ["STOP", "START"]:
            system_status = status
            common.notify_status_changed()
    else:
        if system_status == "STOP":
            if context == "component_wip":
                if target_id == STATION_ID:
                    station_wip = common.deserialize_object(payload)
                    station_total_wip = sum(station_wip.values())
                if target_id in NEXT_STATION_IDS:
                    next_station_wips[target_id] = common.deserialize_object(payload)
                    next_station_total_wips[target_id] = sum(
                        next_station_wips[target_id].values()
                    )
            elif context == "part_memory":
                uid = input_sensor.read_passive_target()
                properties = common.deserialize_object(payload)
                if uid is not None:
                    if input_sensor.format_memory(uid, SCHEMA, properties):
                        print("Successfully formatted part memory")
                    else:
                        print("Failed to format part memory")
                    input_sensor.release_passive_target()
                else:
                    print("No part present at input sensor")
        else:
            if context == "component_event":
                event = common.deserialize_object(payload)
                part_type_ = event["part_type"]
                activity = event["activity"]
                if activity == "TRANSFER":
                    with routing_lock:
                        next_station_wips[source_id][part_type_] -= 1
                        next_station_total_wips[source_id] -= 1
            elif context == "component_vacancy":
                packet = common.deserialize_object(payload)
                code = packet["code"]
                if code == "BOOK":
                    part_type_ = packet["data"]
                    with blocking_lock:
                        if station_total_wip < STATION_CAPACITY:
                            packet = common.build_packet("ACCEPT")
                            topic = common.render_topic(
                                "component_vacancy", STATION_ID, source_id
                            )
                            payload = common.serialize_object(packet)
                            client.publish(topic, payload=payload, qos=2)
                            station_wip[part_type_] += 1
                            station_total_wip += 1
                        else:
                            packet = common.build_packet("SUSPEND")
                            topic = common.render_topic(
                                "component_vacancy", STATION_ID, source_id
                            )
                            payload = common.serialize_object(packet)
                            client.publish(topic, payload=payload, qos=2)
                            blocking_queue.append([source_id, part_type_])
                elif code == "ACCEPT":
                    is_blocked = False
                elif code == "SUSPEND":
                    is_blocked = True


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
threading.excepthook = common.excepthook

input_sensor = common.Sensor(INPUT_SENSOR_PORT, INPUT_SENSOR_BAUDRATE)
input_sensor.SAM_configuration()
input_sensor.RF_configuration(0x00)

machine_sensor = common.Sensor(MACHINE_SENSOR_PORT, MACHINE_SENSOR_BAUDRATE)
machine_sensor.SAM_configuration()
machine_sensor.RF_configuration(0xFF)

output_sensor = common.Sensor(OUTPUT_SENSOR_PORT, OUTPUT_SENSOR_BAUDRATE)
output_sensor.SAM_configuration()
output_sensor.RF_configuration(0xFF)

conveyor_motor = common.Motor(CONVEYOR_MOTOR_PORT)
conveyor_motor.plimit(CONVEYOR_MOTOR_PLIMIT)
conveyor_motor.set_default_speed(CONVEYOR_MOTOR_SPEED)
conveyor_motor.release = True

pusher_motor = common.Motor(PUSHER_MOTOR_PORT)
pusher_motor.plimit(PUSHER_MOTOR_PLIMIT)
pusher_motor.set_default_speed(PUSHER_MOTOR_SPEED)
pusher_motor.release = False
pusher_motor_start_position = pusher_motor.get_position()
pusher_motor_end_position = pusher_motor.get_end_position(PUSHER_MOTOR_RUN_DEGREES)

machine_motor = common.Motor(MACHINE_MOTOR_PORT)
machine_motor.plimit(MACHINE_MOTOR_PLIMIT)
machine_motor.set_default_speed(MACHINE_MOTOR_SPEED)
machine_motor.release = False

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
        common.sleep(duration=MAIN_EXECUTION_INTERVAL)
        if system_status == "STOP":
            if station_status == "START":
                conveyor_motor.stop()
                machine_motor.stop()
                for type_ in PART_TYPES:
                    station_wip[type_] = 0
                station_total_wip = 0
                next_station_id = None
                for type_ in PART_TYPES:
                    pattern_indices[type_] = -1
                for id_ in NEXT_STATION_IDS:
                    for type_ in PART_TYPES:
                        next_station_wips[id_][type_] = 0
                    next_station_total_wips[id_] = 0
                blocking_queue.clear()
                is_blocked = None
                part_uid = None
                part_id = None
                part_type = None
                previous_part_uid = None
                previous_part_id = None
                previous_part_type = None
                station_status = "STOP"
                print("Station " + STATION_ID + " stopped")
        else:
            if station_status == "STOP":
                pusher_motor.run_for_degrees(0)
                conveyor_motor.start()
                machine_motor.start()
                station_status = "START"
                print("Station " + STATION_ID + " started")

            previous_part_uid = part_uid
            previous_part_id = part_id
            previous_part_type = part_type
            while system_status == "START":
                part_uid = input_sensor.read_passive_target()
                if part_uid is None:
                    continue
                part_id = input_sensor.get_property(part_uid, SCHEMA, "part_id")
                if part_id is None:
                    continue
                part_type = input_sensor.get_property(part_uid, SCHEMA, "part_type")
                if part_type is None:
                    continue
                input_sensor.release_passive_target()
                break
            if system_status == "STOP":
                continue

            if BLOCKING_POLICY["type"] == "BBS":
                with routing_lock:
                    next_station_id = get_next_station_id(ROUTING_POLICIES[part_type])
                is_blocked = None
                vacancy_packet = common.build_packet("BOOK", data=part_type)
                mqtt_topic = common.render_topic(
                    "component_vacancy", STATION_ID, next_station_id
                )
                mqtt_payload = common.serialize_object(vacancy_packet)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                common.sleep(
                    condition=lambda: system_status == "START" and is_blocked is None
                )
                if system_status == "STOP":
                    continue

                if is_blocked:
                    station_event = common.build_event(
                        STATION_ID, part_id, part_type, "BLOCK"
                    )
                    mqtt_topic = common.render_topic(
                        "component_event", STATION_ID, "all"
                    )
                    mqtt_payload = common.serialize_object(station_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    common.sleep(
                        condition=lambda: system_status == "START" and is_blocked
                    )
                    if system_status == "STOP":
                        continue

            station_event = common.build_event(STATION_ID, part_id, part_type, "LOAD")
            mqtt_topic = common.render_topic("component_event", STATION_ID, "all")
            mqtt_payload = common.serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            common.sleep(duration=PUSHER_MOTOR_START_DELAY)
            pusher_motor.run_to_position(pusher_motor_end_position)
            common.sleep(duration=PUSHER_MOTOR_END_DELAY)
            pusher_motor.run_to_position(pusher_motor_start_position)

            part_uid = machine_sensor.read_passive_target(timeout=float("inf"))
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
                station_event = common.build_event(
                    STATION_ID, part_id, part_type, "SETUP"
                )
                mqtt_topic = common.render_topic("component_event", STATION_ID, "all")
                mqtt_payload = common.serialize_object(station_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                setup_time = common.get_random_sample(setup_time_distribution)
                common.sleep(
                    duration=setup_time, condition=lambda: system_status == "START"
                )
                if system_status == "STOP":
                    continue

            station_event = common.build_event(
                STATION_ID, part_id, part_type, "PROCESS"
            )
            mqtt_topic = common.render_topic("component_event", STATION_ID, "all")
            mqtt_payload = common.serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            processing_time = common.get_random_sample(
                PROCESSING_TIME_DISTRIBUTIONS[part_type]
            )
            common.sleep(
                duration=processing_time, condition=lambda: system_status == "START"
            )
            if system_status == "STOP":
                continue

            if random.random() < FAILURE_PROBABILITY:
                station_event = common.build_event(
                    STATION_ID, part_id, part_type, "FAIL"
                )
                mqtt_topic = common.render_topic("component_event", STATION_ID, "all")
                mqtt_payload = common.serialize_object(station_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                repair_time = common.get_random_sample(REPAIR_TIME_DISTRIBUTION)
                common.sleep(
                    duration=repair_time, condition=lambda: system_status == "START"
                )
                if system_status == "STOP":
                    continue

            station_event = common.build_event(STATION_ID, part_id, part_type, "UNLOAD")
            mqtt_topic = common.render_topic("component_event", STATION_ID, "all")
            mqtt_payload = common.serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            machine_motor.start()
            part_uid = output_sensor.read_passive_target(timeout=float("inf"))
            if system_status == "STOP":
                continue

            if BLOCKING_POLICY["type"] == "BAS":
                machine_motor.stop()
                with routing_lock:
                    next_station_id = get_next_station_id(ROUTING_POLICIES[part_type])
                is_blocked = None
                vacancy_packet = common.build_packet("BOOK", data=part_type)
                mqtt_topic = common.render_topic(
                    "component_vacancy", STATION_ID, next_station_id
                )
                mqtt_payload = common.serialize_object(vacancy_packet)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                common.sleep(
                    condition=lambda: system_status == "START" and is_blocked is None
                )
                if system_status == "STOP":
                    continue

                if is_blocked:
                    station_event = common.build_event(
                        STATION_ID, part_id, part_type, "BLOCK"
                    )
                    mqtt_topic = common.render_topic(
                        "component_event", STATION_ID, "all"
                    )
                    mqtt_payload = common.serialize_object(station_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    common.sleep(
                        condition=lambda: system_status == "START" and is_blocked
                    )
                    if system_status == "STOP":
                        continue
                machine_motor.start()

            if GATE_ID is not None:
                mqtt_topic = common.render_topic(
                    "next_component_id", STATION_ID, GATE_ID
                )
                mqtt_client.publish(mqtt_topic, payload=next_station_id, qos=2)

            station_event = common.build_event(
                STATION_ID, part_id, part_type, "TRANSFER"
            )
            mqtt_topic = common.render_topic("component_event", STATION_ID, "all")
            mqtt_payload = common.serialize_object(station_event)
            mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

            with blocking_lock:
                station_wip[part_type] -= 1
                station_total_wip -= 1
                next_station_wips[next_station_id][part_type] += 1
                next_station_total_wips[next_station_id] += 1
                if station_total_wip < STATION_CAPACITY and len(blocking_queue) > 0:
                    blocked_station_id, blocked_part_type = blocking_queue.pop(0)
                    vacancy_packet = common.build_packet("ACCEPT")
                    mqtt_topic = common.render_topic(
                        "component_vacancy", STATION_ID, blocked_station_id
                    )
                    mqtt_payload = common.serialize_object(vacancy_packet)
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

    input_sensor.power_down()
    machine_sensor.power_down()
    output_sensor.power_down()

    conveyor_motor.stop()
    pusher_motor.run_for_degrees(0)
    pusher_motor.run_to_position(pusher_motor_start_position)
    pusher_motor.coast()
    machine_motor.stop()

    conveyor_motor.__del__()
    pusher_motor.__del__()
    machine_motor.__del__()
    common.Motor._instance.shutdown()

    os.remove("program.pid")
    print("Station " + STATION_ID + " program stopped")
