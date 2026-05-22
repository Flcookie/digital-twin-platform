import os
import signal
import common
import threading
import paho.mqtt.client as mqtt

os.chdir(os.path.dirname(os.path.abspath(__file__)))
signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit()))


###############################################################################
# Constant declarations                                                       #
###############################################################################
COMMON_CONFIG = common.load_json("common.json")
SPECIFIC_CONFIG = common.load_json("specific.json")

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

LINE_PAIR_PORTS = SPECIFIC_CONFIG["line_pair_ports"]
LINE_PAIR_PLIMIT = SPECIFIC_CONFIG["line_pair_plimit"]
LINE_PAIR_SPEEDS = SPECIFIC_CONFIG["line_pair_speeds"]

BRIDGE_MOTOR_PORT = SPECIFIC_CONFIG["bridge_motor_port"]
BRIDGE_MOTOR_PLIMIT = SPECIFIC_CONFIG["bridge_motor_plimit"]
BRIDGE_MOTOR_SPEED = SPECIFIC_CONFIG["bridge_motor_speed"]

SERVER_HOSTNAME = COMMON_CONFIG["server_hostname"]
SERVER_MQTT_PORT = COMMON_CONFIG["server_mqtt_port"]


###############################################################################
# Variable declarations                                                       #
###############################################################################
system_status = "STOP"
component_status = "STOP"
is_component_started = [False for _ in PRE_START_COMPONENT_IDS]
is_component_stopped = [False for _ in PRE_STOP_COMPONENT_IDS]


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


###############################################################################
# Device initialization                                                       #
###############################################################################
threading.excepthook = common.excepthook

line_pair = common.MotorPair(*LINE_PAIR_PORTS)
line_pair.plimit(LINE_PAIR_PLIMIT)
line_pair.set_default_speed(*LINE_PAIR_SPEEDS)
line_pair.release = True

bridge_motor = common.Motor(BRIDGE_MOTOR_PORT)
bridge_motor.plimit(BRIDGE_MOTOR_PLIMIT)
bridge_motor.set_default_speed(BRIDGE_MOTOR_SPEED)
bridge_motor.release = True

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(SERVER_HOSTNAME, port=SERVER_MQTT_PORT)
mqtt_client.loop_start()


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
                line_pair.stop()
                bridge_motor.stop()
                component_status = "STOP"
                print("Component " + COMPONENT_ID + " stopped")
                mqtt_topic = common.render_topic(
                    "component_status", COMPONENT_ID, "all"
                )
                mqtt_client.publish(mqtt_topic, payload="STOP", qos=2)
        else:
            if component_status == "STOP" and all(is_component_started):
                common.sleep(duration=COMPONENT_START_DELAY)
                line_pair.start()
                bridge_motor.start()
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

    line_pair.stop()
    bridge_motor.stop()

    line_pair.__del__()
    bridge_motor.__del__()
    common.Motor._instance.shutdown()

    os.remove("program.pid")
    print("Component " + COMPONENT_ID + " program stopped")
