#!/usr/bin/env python3


import os
import re
import signal
import subprocess
import paho.mqtt.client as mqtt
import json
import collections
import threading
import time
import ev3dev.ev3 as ev3
import random

os.chdir(os.path.dirname(os.path.abspath(__file__)))
signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit()))
mqtt.Client._call_socket_register_write = lambda _self: None
mqtt.Client._call_socket_unregister_write = lambda _self, _sock=None: None


###############################################################################
# Variable declarations                                                       #
###############################################################################
path = os.path.join("config.json")
with open(path, encoding="utf-8") as file:
    config = json.load(file, object_pairs_hook=lambda p: collections.OrderedDict(p))

GATE_ID = config["gate_id"]
NEXT_STATION_IDS = config["next_station_ids"]

INPUT_SENSOR_PORT = config["input_sensor_port"]
INPUT_SENSOR_THRESHOLD = config["input_sensor_threshold"]

CUTTER_MOTOR_PORT = config["cutter_motor_port"]
CUTTER_MOTOR_POLARITY = config["cutter_motor_polarity"]
CUTTER_MOTOR_SPEED = config["cutter_motor_speed"]
CUTTER_MOTOR_START_POSITION = 0
CUTTER_MOTOR_END_POSITION = config["cutter_motor_end_position"]
CUTTER_MOTOR_END_DELAY = config["cutter_motor_end_delay"]

PUSHER_MOTOR_PORT = config["pusher_motor_port"]
PUSHER_MOTOR_POLARITY = config["pusher_motor_polarity"]
PUSHER_MOTOR_SPEED = config["pusher_motor_speed"]
PUSHER_MOTOR_START_POSITION = 0
PUSHER_MOTOR_END_POSITIONS = config["pusher_motor_end_positions"]
PUSHER_MOTOR_END_DELAY = config["pusher_motor_end_delay"]

MQTT_BROKER_HOST = config["mqtt_broker_host"]
MQTT_BROKER_PORT = config["mqtt_broker_port"]

MAIN_EXECUTION_INTERVAL = config["main_execution_interval"]


###############################################################################
# Variable declarations                                                       #
###############################################################################
system_status = "STOP"
gate_status = "STOP"
routing_lock = threading.Lock()
routing_queue = list()


###############################################################################
# Function definitions                                                        #
###############################################################################
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT with code " + str(rc))
    topic = render_topic("system_time", "master", "all")
    client.subscribe(topic, qos=2)
    topic = render_topic("system_status", "master", "all")
    client.subscribe(topic, qos=2)
    topic = render_topic("next_component_id", "+", GATE_ID)
    client.subscribe(topic, qos=2)


def on_message(client, userdata, msg):
    global system_status
    global routing_queue

    context, source_id, target_id = parse_topic(msg.topic)
    payload = msg.payload.decode("utf-8")
    if context == "system_time":
        if payload and re.match(r"^[\d\s\-:TZ\.]+$", payload.strip()):
            try:
                subprocess.run(["sudo", "date", "-s", payload.strip()], capture_output=True, timeout=5)
            except Exception:
                pass
    elif context == "system_status":
        status = payload.upper()
        if status in ["STOP", "START"]:
            system_status = status
    else:
        if system_status != "STOP":
            if context == "next_component_id":
                with routing_lock:
                    routing_queue.append(payload)


def render_topic(context, source_id, target_id):
    return "/".join([context, source_id, target_id])


def parse_topic(topic):
    return tuple(topic.split("/"))


def sleep(duration=float("inf"), condition=lambda: True):
    end_time = time.time() + duration
    while time.time() < end_time and condition():
        time.sleep(0.05)


###############################################################################
# Device initialization                                                       #
###############################################################################
ev3.Leds.set_color(ev3.Leds.LEFT, ev3.Leds.GREEN)
ev3.Leds.set_color(ev3.Leds.RIGHT, ev3.Leds.GREEN)

input_sensor = ev3.ColorSensor(INPUT_SENSOR_PORT)
input_sensor.mode = ev3.ColorSensor.MODE_COL_REFLECT

cutter_motor = ev3.MediumMotor(CUTTER_MOTOR_PORT)
cutter_motor.reset()
cutter_motor.polarity = CUTTER_MOTOR_POLARITY
cutter_motor.speed_sp = CUTTER_MOTOR_SPEED
cutter_motor.stop_action = ev3.Motor.STOP_ACTION_BRAKE

pusher_motor = ev3.MediumMotor(PUSHER_MOTOR_PORT)
pusher_motor.reset()
pusher_motor.polarity = PUSHER_MOTOR_POLARITY
pusher_motor.speed_sp = PUSHER_MOTOR_SPEED
pusher_motor.stop_action = ev3.Motor.STOP_ACTION_BRAKE

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
print("Gate " + GATE_ID + " program started")

try:
    while True:
        sleep(duration=MAIN_EXECUTION_INTERVAL)
        if system_status == "STOP":
            if gate_status == "START":
                routing_queue.clear()
                gate_status = "STOP"
                print("Gate " + GATE_ID + " stopped")
        else:
            if gate_status == "STOP":
                gate_status = "START"
                print("Gate " + GATE_ID + " started")

            if input_sensor.value() > INPUT_SENSOR_THRESHOLD:
                cutter_motor.run_to_abs_pos(position_sp=CUTTER_MOTOR_END_POSITION)
                cutter_motor.wait_until(ev3.Motor.STATE_RUNNING)
                cutter_motor.wait_until_not_moving()
                sleep(duration=CUTTER_MOTOR_END_DELAY)
                cutter_motor.run_to_abs_pos(position_sp=CUTTER_MOTOR_START_POSITION)
                cutter_motor.wait_until(ev3.Motor.STATE_RUNNING)
                cutter_motor.wait_until_not_moving()

                with routing_lock:
                    if len(routing_queue) <= 0:
                        next_station_id = random.choice(NEXT_STATION_IDS)
                    else:
                        next_station_id = routing_queue.pop(0)

                pusher_motor_end_position = PUSHER_MOTOR_END_POSITIONS[next_station_id]
                pusher_motor.run_to_abs_pos(position_sp=pusher_motor_end_position)
                pusher_motor.wait_until(ev3.Motor.STATE_RUNNING)
                pusher_motor.wait_until_not_moving()
                sleep(duration=PUSHER_MOTOR_END_DELAY)
                pusher_motor.run_to_abs_pos(position_sp=PUSHER_MOTOR_START_POSITION)
                pusher_motor.wait_until(ev3.Motor.STATE_RUNNING)
                pusher_motor.wait_until_not_moving()
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    system_status = "STOP"
    gate_status = "STOP"

    cutter_motor.stop()
    if abs(CUTTER_MOTOR_START_POSITION - cutter_motor.position) > 0:
        cutter_motor.run_to_abs_pos(position_sp=CUTTER_MOTOR_START_POSITION)
        cutter_motor.wait_until(ev3.Motor.STATE_RUNNING)
        cutter_motor.wait_until_not_moving()
    pusher_motor.stop()
    if abs(PUSHER_MOTOR_START_POSITION - pusher_motor.position) > 0:
        pusher_motor.run_to_abs_pos(position_sp=PUSHER_MOTOR_START_POSITION)
        pusher_motor.wait_until(ev3.Motor.STATE_RUNNING)
        pusher_motor.wait_until_not_moving()

    os.remove("program.pid")
    print("Gate " + GATE_ID + " program stopped")
