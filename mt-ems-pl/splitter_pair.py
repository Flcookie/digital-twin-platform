import os
import signal
import common
import threading
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
NEXT_COMPONENT_IDS = SPECIFIC_CONFIG["next_component_ids"]
SPLITTER_IDS = SPECIFIC_CONFIG["splitter_ids"]
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

COMPONENT_CAPACITY = SPECIFIC_CONFIG["component_capacity"]

INPUT_SENSOR_PORTS = SPECIFIC_CONFIG["input_sensor_ports"]
INPUT_SENSOR_BAUDRATE = SPECIFIC_CONFIG["input_sensor_baudrate"]

CUTTER_MOTOR_PORTS = SPECIFIC_CONFIG["cutter_motor_ports"]
CUTTER_MOTOR_PLIMIT = SPECIFIC_CONFIG["cutter_motor_plimit"]
CUTTER_MOTOR_SPEED = SPECIFIC_CONFIG["cutter_motor_speed"]
CUTTER_MOTOR_RUN_DEGREES = SPECIFIC_CONFIG["cutter_motor_run_degrees"]
CUTTER_MOTOR_START_DELAY = SPECIFIC_CONFIG["cutter_motor_start_delay"]
CUTTER_MOTOR_END_DELAY = SPECIFIC_CONFIG["cutter_motor_end_delay"]

PUSHER_MOTOR_PORTS = SPECIFIC_CONFIG["pusher_motor_ports"]
PUSHER_MOTOR_PLIMIT = SPECIFIC_CONFIG["pusher_motor_plimit"]
PUSHER_MOTOR_SPEED = SPECIFIC_CONFIG["pusher_motor_speed"]
PUSHER_MOTOR_RUN_DEGREES = SPECIFIC_CONFIG["pusher_motor_run_degrees"]
PUSHER_MOTOR_START_DELAYS = SPECIFIC_CONFIG["pusher_motor_start_delays"]
PUSHER_MOTOR_END_DELAYS = SPECIFIC_CONFIG["pusher_motor_end_delays"]

SERVER_HOSTNAME = COMMON_CONFIG["server_hostname"]
SERVER_MQTT_PORT = COMMON_CONFIG["server_mqtt_port"]


###############################################################################
# Variable declarations                                                       #
###############################################################################
system_status = "STOP"
component_status = "STOP"
is_component_started = [False for _ in PRE_START_COMPONENT_IDS]
is_component_stopped = [False for _ in PRE_STOP_COMPONENT_IDS]
component_wip = 0
vacancy_lock = threading.Lock()
booking_queue = list()
is_request_accepted = [None for _ in range(len(SPLITTER_IDS))]
splitter_threads = [None for _ in range(len(SPLITTER_IDS))]


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
    topic = common.render_topic("component_wip", "master", COMPONENT_ID)
    client.subscribe(topic, qos=2)
    topic = common.render_topic("component_vacancy", "+", COMPONENT_ID)
    client.subscribe(topic, qos=2)
    topic = common.render_topic("part_memory", "master", COMPONENT_ID)
    client.subscribe(topic, qos=2)


def on_message(client, userdata, msg):
    global system_status
    global component_wip

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
            if context == "component_wip":
                component_wip = int(payload)
            elif context == "part_memory":
                for index in range(len(SPLITTER_IDS)):
                    uid = input_sensors[index].read_passive_target()
                    properties = common.deserialize_object(payload)
                    if uid is not None:
                        if input_sensors[index].format_memory(uid, SCHEMA, properties):
                            print("Successfully formatted part memory")
                        else:
                            print("Failed to format part memory")
                        input_sensors[index].release_passive_target()
                    else:
                        print("No part present at input sensor: " + str(index))
        else:
            if context == "component_vacancy":
                if payload == "BOOK":
                    with vacancy_lock:
                        if component_wip < COMPONENT_CAPACITY:
                            topic = common.render_topic(
                                "component_vacancy", COMPONENT_ID, source_id
                            )
                            client.publish(topic, payload="ACCEPT", qos=2)
                            component_wip += 1
                        else:
                            topic = common.render_topic(
                                "component_vacancy", COMPONENT_ID, source_id
                            )
                            client.publish(topic, payload="SUSPEND", qos=2)
                            booking_queue.append(source_id)
                elif payload == "PEEK":
                    with vacancy_lock:
                        if component_wip < COMPONENT_CAPACITY:
                            topic = common.render_topic(
                                "component_vacancy", COMPONENT_ID, source_id
                            )
                            client.publish(topic, payload="ACCEPT", qos=2)
                            component_wip += 1
                        else:
                            topic = common.render_topic(
                                "component_vacancy", COMPONENT_ID, source_id
                            )
                            client.publish(topic, payload="REFUSE", qos=2)
                elif payload == "ACCEPT":
                    index = NEXT_COMPONENT_IDS.index(source_id)
                    is_request_accepted[index] = True
                elif payload == "REFUSE":
                    index = NEXT_COMPONENT_IDS.index(source_id)
                    is_request_accepted[index] = False


def run_splitter(index):
    global component_wip

    while system_status == "START":
        part_uid = input_sensors[index].read_passive_target()
        if part_uid is None:
            continue
        part_id = input_sensors[index].get_property(part_uid, SCHEMA, "part_id")
        if part_id is None:
            continue
        is_part_ready = specific.check_part(
            input_sensors[index], part_uid, SCHEMA, splitter_index=index
        )
        if is_part_ready is None:
            continue
        input_sensors[index].release_passive_target()
        if system_status == "STOP":
            continue

        if not is_part_ready:
            event = common.build_event(SPLITTER_IDS[index], part_id, "RETURN")
            topic = common.render_topic("component_event", COMPONENT_ID, "all")
            payload = common.serialize_object(event)
            mqtt_client.publish(topic, payload=payload, qos=2)

            common.sleep(duration=CUTTER_MOTOR_START_DELAY)
            cutter_motors[index].run_to_position(cutter_motor_end_positions[index])
            common.sleep(duration=CUTTER_MOTOR_END_DELAY)
            cutter_motors[index].run_to_position(cutter_motor_start_positions[index])

            common.sleep(duration=PUSHER_MOTOR_START_DELAYS[0])
            pusher_motors[index].run_to_position(pusher_motor_end_positions[index][0])
            common.sleep(duration=PUSHER_MOTOR_END_DELAYS[0])
            pusher_motors[index].run_to_position(pusher_motor_start_positions[index])
            if system_status == "STOP":
                continue

            event = common.build_event(SPLITTER_IDS[index], part_id, "TRANSFER")
            topic = common.render_topic("component_event", COMPONENT_ID, "all")
            payload = common.serialize_object(event)
            mqtt_client.publish(topic, payload=payload, qos=2)
        else:
            is_request_accepted[index] = None
            topic = common.render_topic(
                "component_vacancy", COMPONENT_ID, NEXT_COMPONENT_IDS[index]
            )
            mqtt_client.publish(topic, payload="PEEK", qos=2)
            common.sleep(
                condition=lambda: (
                    system_status == "START" and is_request_accepted[index] is None
                )
            )
            if system_status == "STOP":
                continue

            if not is_request_accepted[index]:
                event = common.build_event(SPLITTER_IDS[index], part_id, "RETURN")
                topic = common.render_topic("component_event", COMPONENT_ID, "all")
                payload = common.serialize_object(event)
                mqtt_client.publish(topic, payload=payload, qos=2)

                common.sleep(duration=CUTTER_MOTOR_START_DELAY)
                cutter_motors[index].run_to_position(cutter_motor_end_positions[index])
                common.sleep(duration=CUTTER_MOTOR_END_DELAY)
                cutter_motors[index].run_to_position(cutter_motor_start_positions[index])

                common.sleep(duration=PUSHER_MOTOR_START_DELAYS[0])
                pusher_motors[index].run_to_position(pusher_motor_end_positions[index][0])
                common.sleep(duration=PUSHER_MOTOR_END_DELAYS[0])
                pusher_motors[index].run_to_position(pusher_motor_start_positions[index])
                if system_status == "STOP":
                    continue

                event = common.build_event(SPLITTER_IDS[index], part_id, "TRANSFER")
                topic = common.render_topic("component_event", COMPONENT_ID, "all")
                payload = common.serialize_object(event)
                mqtt_client.publish(topic, payload=payload, qos=2)
            else:
                part_uid = input_sensors[index].read_passive_target()
                if part_uid is None:
                    continue
                is_part_updated = specific.update_part(
                    input_sensors[index], part_uid, SCHEMA
                )
                if not is_part_updated:
                    continue
                input_sensors[index].release_passive_target()

                event = common.build_event(SPLITTER_IDS[index], part_id, "FORWARD")
                topic = common.render_topic("component_event", COMPONENT_ID, "all")
                payload = common.serialize_object(event)
                mqtt_client.publish(topic, payload=payload, qos=2)

                common.sleep(duration=CUTTER_MOTOR_START_DELAY)
                cutter_motors[index].run_to_position(cutter_motor_end_positions[index])
                common.sleep(duration=CUTTER_MOTOR_END_DELAY)
                cutter_motors[index].run_to_position(cutter_motor_start_positions[index])

                common.sleep(duration=PUSHER_MOTOR_START_DELAYS[1])
                pusher_motors[index].run_to_position(pusher_motor_end_positions[index][1])
                common.sleep(duration=PUSHER_MOTOR_END_DELAYS[1])
                pusher_motors[index].run_to_position(pusher_motor_start_positions[index])
                if system_status == "STOP":
                    continue

                event = common.build_event(SPLITTER_IDS[index], part_id, "TRANSFER")
                topic = common.render_topic("component_event", COMPONENT_ID, "all")
                payload = common.serialize_object(event)
                mqtt_client.publish(topic, payload=payload, qos=2)

                with vacancy_lock:
                    component_wip -= 1
                    if component_wip < COMPONENT_CAPACITY and len(booking_queue) > 0:
                        blocked_component_id = booking_queue.pop(0)
                        topic = common.render_topic(
                            "component_vacancy", COMPONENT_ID, blocked_component_id
                        )
                        mqtt_client.publish(topic, payload="ACCEPT", qos=2)
                        component_wip += 1


###############################################################################
# Device initialization                                                       #
###############################################################################
threading.excepthook = common.excepthook

input_sensors = list()
cutter_motors = list()
cutter_motor_start_positions = list()
cutter_motor_end_positions = list()
pusher_motors = list()
pusher_motor_start_positions = list()
pusher_motor_end_positions = list()
for splitter_index in range(len(SPLITTER_IDS)):
    input_sensors.append(
        common.Sensor(INPUT_SENSOR_PORTS[splitter_index], INPUT_SENSOR_BAUDRATE)
    )
    input_sensors[splitter_index].SAM_configuration()
    input_sensors[splitter_index].RF_configuration(0x00)

    cutter_motors.append(common.Motor(CUTTER_MOTOR_PORTS[splitter_index]))
    cutter_motors[splitter_index].plimit(CUTTER_MOTOR_PLIMIT)
    cutter_motors[splitter_index].set_default_speed(CUTTER_MOTOR_SPEED)
    cutter_motors[splitter_index].release = False
    cutter_motor_start_positions.append(cutter_motors[splitter_index].get_position())
    cutter_motor_end_positions.append(
        cutter_motors[splitter_index].get_end_position(CUTTER_MOTOR_RUN_DEGREES)
    )

    pusher_motors.append(common.Motor(PUSHER_MOTOR_PORTS[splitter_index]))
    pusher_motors[splitter_index].plimit(PUSHER_MOTOR_PLIMIT)
    pusher_motors[splitter_index].set_default_speed(PUSHER_MOTOR_SPEED)
    pusher_motors[splitter_index].release = False
    pusher_motor_start_positions.append(pusher_motors[splitter_index].get_position())
    pusher_motor_end_positions.append([
        pusher_motors[splitter_index].get_end_position(degrees)
        for degrees in PUSHER_MOTOR_RUN_DEGREES
    ])

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
                for splitter_index in range(len(SPLITTER_IDS)):
                    if splitter_threads[splitter_index] is not None:
                        splitter_threads[splitter_index].join()
                component_wip = 0
                booking_queue = list()
                for splitter_index in range(len(SPLITTER_IDS)):
                    is_request_accepted[splitter_index] = None
                    splitter_threads[splitter_index] = None
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
                for splitter_index in range(len(SPLITTER_IDS)):
                    cutter_motors[splitter_index].run_for_degrees(0)
                    pusher_motors[splitter_index].run_for_degrees(0)
                    splitter_threads[splitter_index] = threading.Thread(
                        target=run_splitter, args=(splitter_index,)
                    )
                    splitter_threads[splitter_index].daemon = True
                    splitter_threads[splitter_index].start()
                component_status = "START"
                print("Component " + COMPONENT_ID + " started")
                mqtt_topic = common.render_topic(
                    "component_status", COMPONENT_ID, "all"
                )
                mqtt_client.publish(mqtt_topic, payload="START", qos=2)
        common.sleep(duration=COMPONENT_FREE_INTERVAL)
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    system_status = "STOP"
    component_status = "STOP"

    for splitter_index in range(len(SPLITTER_IDS)):
        if splitter_threads[splitter_index] is not None:
            splitter_threads[splitter_index].join()

        input_sensors[splitter_index].power_down()

        cutter_motors[splitter_index].run_for_degrees(0)
        cutter_motors[splitter_index].run_to_position(
            cutter_motor_start_positions[splitter_index]
        )
        cutter_motors[splitter_index].coast()
        pusher_motors[splitter_index].run_for_degrees(0)
        pusher_motors[splitter_index].run_to_position(
            pusher_motor_start_positions[splitter_index]
        )
        pusher_motors[splitter_index].coast()

    for splitter_index in range(len(SPLITTER_IDS)):
        cutter_motors[splitter_index].__del__()
        pusher_motors[splitter_index].__del__()
    common.Motor._instance.shutdown()

    os.remove("program.pid")
    print("Component " + COMPONENT_ID + " program stopped")
