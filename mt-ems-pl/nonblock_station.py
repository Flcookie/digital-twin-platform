import os
import signal
import common
import threading
import random
import paho.mqtt.client as mqtt
import specific

os.chdir(os.path.dirname(os.path.abspath(__file__)))
signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit()))


###############################################################################
# Constant declarations                                                       #
###############################################################################
COMMON_CONFIG = common.load_json("common.json")
SPECIFIC_CONFIG = common.load_json("specific.json")
SCHEMA = common.load_json("schema.json")

COMPONENT_ID = SPECIFIC_CONFIG["component_id"]
PRE_START_COMPONENT_IDS = list()
for group in COMMON_CONFIG["component_start_order"]:
    if COMPONENT_ID not in group:
        PRE_START_COMPONENT_IDS.extend(group)
    else:
        break
PRE_STOP_COMPONENT_IDS = list()
for group in COMMON_CONFIG["component_stop_order"]:
    if COMPONENT_ID not in group:
        PRE_STOP_COMPONENT_IDS.extend(group)
    else:
        break
COMPONENT_START_DELAY = SPECIFIC_CONFIG["component_start_delay"]
COMPONENT_FREE_INTERVAL = COMMON_CONFIG["component_free_interval"]

PROCESSING_TIME_DISTRIBUTION = SPECIFIC_CONFIG["processing_time_distribution"]
FAILURE_PROBABILITY = SPECIFIC_CONFIG["failure_probability"]
REPAIR_TIME_DISTRIBUTION = SPECIFIC_CONFIG["repair_time_distribution"]

INPUT_SENSOR_PORT = SPECIFIC_CONFIG["input_sensor_port"]
INPUT_SENSOR_BAUDRATE = SPECIFIC_CONFIG["input_sensor_baudrate"]

MACHINE_SENSOR_PORT = SPECIFIC_CONFIG["machine_sensor_port"]
MACHINE_SENSOR_BAUDRATE = SPECIFIC_CONFIG["machine_sensor_baudrate"]

CUTTER_MOTOR_PORT = SPECIFIC_CONFIG["cutter_motor_port"]
CUTTER_MOTOR_PLIMIT = SPECIFIC_CONFIG["cutter_motor_plimit"]
CUTTER_MOTOR_SPEED = SPECIFIC_CONFIG["cutter_motor_speed"]
CUTTER_MOTOR_RUN_DEGREES = SPECIFIC_CONFIG["cutter_motor_run_degrees"]
CUTTER_MOTOR_START_DELAY = SPECIFIC_CONFIG["cutter_motor_start_delay"]
CUTTER_MOTOR_END_DELAY = SPECIFIC_CONFIG["cutter_motor_end_delay"]

PUSHER_MOTOR_PORT = SPECIFIC_CONFIG["pusher_motor_port"]
PUSHER_MOTOR_PLIMIT = SPECIFIC_CONFIG["pusher_motor_plimit"]
PUSHER_MOTOR_SPEED = SPECIFIC_CONFIG["pusher_motor_speed"]
PUSHER_MOTOR_RUN_DEGREES = SPECIFIC_CONFIG["pusher_motor_run_degrees"]
PUSHER_MOTOR_START_DELAYS = SPECIFIC_CONFIG["pusher_motor_start_delays"]
PUSHER_MOTOR_END_DELAYS = SPECIFIC_CONFIG["pusher_motor_end_delays"]

MACHINE_MOTOR_PORT = SPECIFIC_CONFIG["machine_motor_port"]
MACHINE_MOTOR_PLIMIT = SPECIFIC_CONFIG["machine_motor_plimit"]
MACHINE_MOTOR_SPEEDS = SPECIFIC_CONFIG["machine_motor_speeds"]

SERVER_HOSTNAME = COMMON_CONFIG["server_hostname"]
SERVER_MQTT_PORT = COMMON_CONFIG["server_mqtt_port"]


###############################################################################
# Variable declarations                                                       #
###############################################################################
system_status = "STOP"
component_status = "STOP"
is_component_started = [False for _ in PRE_START_COMPONENT_IDS]
is_component_stopped = [False for _ in PRE_STOP_COMPONENT_IDS]
part_uid = None
part_id = None
is_part_ready = False
is_part_updated = False
machine_status = "IDLE"
machine_thread = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT with code " + str(rc))
    topic = common.render_topic("system_status", "master", "all")
    client.subscribe(topic, qos=2)
    for id_ in PRE_START_COMPONENT_IDS:
        topic = common.render_topic("component_status", id_, "all")
        client.subscribe(topic, qos=2)
    for id_ in PRE_STOP_COMPONENT_IDS:
        topic = common.render_topic("component_status", id_, "all")
        client.subscribe(topic, qos=2)
    topic = common.render_topic("part_memory", "master", COMPONENT_ID)
    client.subscribe(topic, qos=2)


def on_message(client, userdata, msg):
    global system_status

    context, source_id, target_id = common.parse_topic(msg.topic)
    payload = msg.payload.decode("utf-8")
    if context == "system_status":
        status = payload.upper()
        if status in ["STOP", "START"]:
            system_status = status
    elif context == "component_status":
        if source_id in PRE_START_COMPONENT_IDS:
            index = PRE_START_COMPONENT_IDS.index(source_id)
            is_component_started[index] = (payload == "START")
        if source_id in PRE_STOP_COMPONENT_IDS:
            index = PRE_STOP_COMPONENT_IDS.index(source_id)
            is_component_stopped[index] = (payload == "STOP")
    else:
        if system_status == "STOP":
            if context == "part_memory":
                if target_id == COMPONENT_ID:
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


def run_machine(part_id_):
    global machine_status

    event = common.build_event(COMPONENT_ID, part_id_, "PROCESS")
    topic = common.render_topic("component_event", COMPONENT_ID, "all")
    payload = common.serialize_object(event)
    mqtt_client.publish(topic, payload=payload, qos=2)

    processing_time = common.get_random_sample(PROCESSING_TIME_DISTRIBUTION)
    common.sleep(
        duration=processing_time, condition=lambda: system_status == "START"
    )
    if system_status == "STOP":
        return

    if random.random() < FAILURE_PROBABILITY:
        event = common.build_event(COMPONENT_ID, part_id_, "FAIL")
        topic = common.render_topic("component_event", COMPONENT_ID, "all")
        payload = common.serialize_object(event)
        mqtt_client.publish(topic, payload=payload, qos=2)

        repair_time = common.get_random_sample(REPAIR_TIME_DISTRIBUTION)
        common.sleep(
            duration=repair_time, condition=lambda: system_status == "START"
        )
    machine_status = "DONE"


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

cutter_motor = common.Motor(CUTTER_MOTOR_PORT)
cutter_motor.plimit(CUTTER_MOTOR_PLIMIT)
cutter_motor.set_default_speed(CUTTER_MOTOR_SPEED)
cutter_motor.release = False
cutter_motor_start_position = cutter_motor.get_position()
cutter_motor_end_position = cutter_motor.get_end_position(CUTTER_MOTOR_RUN_DEGREES)

pusher_motor = common.Motor(PUSHER_MOTOR_PORT)
pusher_motor.plimit(PUSHER_MOTOR_PLIMIT)
pusher_motor.set_default_speed(PUSHER_MOTOR_SPEED)
pusher_motor.release = False
pusher_motor_start_position = pusher_motor.get_position()
pusher_motor_end_positions = [
    pusher_motor.get_end_position(degrees) for degrees in PUSHER_MOTOR_RUN_DEGREES
]

machine_motor = common.Motor(MACHINE_MOTOR_PORT)
machine_motor.plimit(MACHINE_MOTOR_PLIMIT)
machine_motor.release = False

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(SERVER_HOSTNAME, port=SERVER_MQTT_PORT)
mqtt_client.loop_start()

specific.initialize(__import__(__name__))


###############################################################################
# Program execution                                                           #
###############################################################################
program_pid = str(os.getpid())
with open("program.pid", "w") as file:
    file.write(program_pid + "\n")
print("Component " + COMPONENT_ID + " program started")

try:
    while True:
        if system_status == "STOP":
            if component_status == "START" and all(is_component_stopped):
                if machine_thread is not None:
                    machine_thread.join()
                machine_motor.stop()
                part_uid = None
                part_id = None
                is_part_ready = False
                is_part_updated = False
                machine_status = "IDLE"
                machine_thread = None
                component_status = "STOP"
                specific.refresh(__import__(__name__))
                print("Component " + COMPONENT_ID + " stopped")
                mqtt_topic = common.render_topic(
                    "component_status", COMPONENT_ID, "all"
                )
                mqtt_client.publish(mqtt_topic, payload="STOP", qos=2)
        else:
            if component_status == "STOP" and all(is_component_started):
                common.sleep(duration=COMPONENT_START_DELAY)
                machine_motor.start(speed=MACHINE_MOTOR_SPEEDS[0])
                cutter_motor.run_for_degrees(0)
                pusher_motor.run_for_degrees(0)
                component_status = "START"
                print("Component " + COMPONENT_ID + " started")
                mqtt_topic = common.render_topic(
                    "component_status", COMPONENT_ID, "all"
                )
                mqtt_client.publish(mqtt_topic, payload="START", qos=2)

        if component_status == "STOP":
            common.sleep(duration=COMPONENT_FREE_INTERVAL)
        else:
            if machine_status == "IDLE":
                part_uid = input_sensor.read_passive_target()
                if part_uid is None:
                    continue
                part_id = input_sensor.get_property(part_uid, SCHEMA, "part_id")
                if part_id is None:
                    continue
                is_part_ready = specific.check_part(
                    input_sensor, part_uid, SCHEMA, part_id=part_id
                )
                if is_part_ready is None:
                    continue
                input_sensor.release_passive_target()
                if system_status == "STOP":
                    continue

                if not is_part_ready:
                    component_event = common.build_event(COMPONENT_ID, part_id, "LOAD")
                    mqtt_topic = common.render_topic(
                        "component_event", COMPONENT_ID, "all"
                    )
                    mqtt_payload = common.serialize_object(component_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    common.sleep(duration=CUTTER_MOTOR_START_DELAY)
                    cutter_motor.run_to_position(cutter_motor_end_position)
                    common.sleep(duration=CUTTER_MOTOR_END_DELAY)
                    cutter_motor.run_to_position(cutter_motor_start_position)

                    common.sleep(duration=PUSHER_MOTOR_START_DELAYS[0])
                    pusher_motor.run_to_position(pusher_motor_end_positions[0])
                    common.sleep(duration=PUSHER_MOTOR_END_DELAYS[0])
                    pusher_motor.run_to_position(
                        pusher_motor_start_position, block=False
                    )

                    part_uid = machine_sensor.read_passive_target(timeout=float("inf"))
                    machine_sensor.release_passive_target()
                    machine_motor.run_for_degrees(0)
                    if system_status == "STOP":
                        continue

                    machine_status = "BUSY"
                    machine_thread = threading.Thread(
                        target=run_machine, args=[part_id]
                    )
                    machine_thread.daemon = True
                    machine_thread.start()
                else:
                    component_event = common.build_event(COMPONENT_ID, part_id, "PASS")
                    mqtt_topic = common.render_topic(
                        "component_event", COMPONENT_ID, "all"
                    )
                    mqtt_payload = common.serialize_object(component_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    common.sleep(duration=CUTTER_MOTOR_START_DELAY)
                    cutter_motor.run_to_position(cutter_motor_end_position)
                    common.sleep(duration=CUTTER_MOTOR_END_DELAY)
                    cutter_motor.run_to_position(cutter_motor_start_position)

                    common.sleep(duration=PUSHER_MOTOR_START_DELAYS[2])
                    pusher_motor.run_to_position(pusher_motor_end_positions[2])
                    common.sleep(duration=PUSHER_MOTOR_END_DELAYS[2])

                    component_event = common.build_event(
                        COMPONENT_ID, part_id, "TRANSFER"
                    )
                    mqtt_topic = common.render_topic(
                        "component_event", COMPONENT_ID, "all"
                    )
                    mqtt_payload = common.serialize_object(component_event)
                    mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                    pusher_motor.run_to_position(pusher_motor_start_position)
            elif machine_status == "BUSY":
                part_uid = input_sensor.read_passive_target()
                if part_uid is None:
                    continue
                part_id = input_sensor.get_property(part_uid, SCHEMA, "part_id")
                if part_id is None:
                    continue
                is_part_ready = specific.check_part(
                    input_sensor, part_uid, SCHEMA, part_id=part_id
                )
                if is_part_ready is None:
                    continue
                input_sensor.release_passive_target()
                if system_status == "STOP":
                    continue

                component_event = common.build_event(COMPONENT_ID, part_id, "PASS")
                mqtt_topic = common.render_topic("component_event", COMPONENT_ID, "all")
                mqtt_payload = common.serialize_object(component_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                common.sleep(duration=CUTTER_MOTOR_START_DELAY)
                cutter_motor.run_to_position(cutter_motor_end_position)
                common.sleep(duration=CUTTER_MOTOR_END_DELAY)
                cutter_motor.run_to_position(cutter_motor_start_position)

                common.sleep(duration=PUSHER_MOTOR_START_DELAYS[2])
                pusher_motor.run_to_position(pusher_motor_end_positions[2])
                common.sleep(duration=PUSHER_MOTOR_END_DELAYS[2])

                component_event = common.build_event(COMPONENT_ID, part_id, "TRANSFER")
                mqtt_topic = common.render_topic("component_event", COMPONENT_ID, "all")
                mqtt_payload = common.serialize_object(component_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                pusher_motor.run_to_position(pusher_motor_start_position)
            else:
                part_uid = machine_sensor.read_passive_target(timeout=float("inf"))
                part_id = machine_sensor.get_property(part_uid, SCHEMA, "part_id")
                if part_id is None:
                    continue
                is_part_updated = specific.update_part(
                    machine_sensor, part_uid, SCHEMA, part_id=part_id
                )
                if not is_part_updated:
                    continue
                machine_sensor.release_passive_target()
                if system_status == "STOP":
                    continue

                component_event = common.build_event(COMPONENT_ID, part_id, "UNLOAD")
                mqtt_topic = common.render_topic("component_event", COMPONENT_ID, "all")
                mqtt_payload = common.serialize_object(component_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                machine_motor.start(speed=MACHINE_MOTOR_SPEEDS[1])
                common.sleep(
                    condition=lambda: (
                        machine_motor.get_speed() / MACHINE_MOTOR_SPEEDS[1] < 0.5
                    )
                )
                common.sleep(duration=PUSHER_MOTOR_START_DELAYS[1])
                pusher_motor.run_to_position(pusher_motor_end_positions[1])
                common.sleep(duration=PUSHER_MOTOR_END_DELAYS[1])

                machine_status = "IDLE"
                component_event = common.build_event(COMPONENT_ID, part_id, "TRANSFER")
                mqtt_topic = common.render_topic("component_event", COMPONENT_ID, "all")
                mqtt_payload = common.serialize_object(component_event)
                mqtt_client.publish(mqtt_topic, payload=mqtt_payload, qos=2)

                pusher_motor.run_to_position(pusher_motor_start_position)
                machine_motor.run_for_degrees(0)
                machine_motor.start(speed=MACHINE_MOTOR_SPEEDS[0])
                common.sleep(
                    condition=lambda: (
                        machine_motor.get_speed() / MACHINE_MOTOR_SPEEDS[0] < 0.5
                    )
                )
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    system_status = "STOP"
    component_status = "STOP"

    if machine_thread is not None:
        machine_thread.join()

    input_sensor.power_down()
    machine_sensor.power_down()

    cutter_motor.run_for_degrees(0)
    cutter_motor.run_to_position(cutter_motor_start_position)
    cutter_motor.coast()
    pusher_motor.run_for_degrees(0)
    pusher_motor.run_to_position(pusher_motor_start_position)
    pusher_motor.coast()
    machine_motor.stop()

    cutter_motor.__del__()
    pusher_motor.__del__()
    machine_motor.__del__()
    common.Motor._instance.shutdown()

    os.remove("program.pid")
    print("Component " + COMPONENT_ID + " program stopped")
