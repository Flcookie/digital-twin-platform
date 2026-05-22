import collections
import common


###############################################################################
# Constant declarations                                                       #
###############################################################################
COMPONENT_ID = None
LAST_OPERATION_NUMBER = None


###############################################################################
# Variable declarations                                                       #
###############################################################################
mqtt_client = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def initialize(caller):
    global COMPONENT_ID
    global LAST_OPERATION_NUMBER
    COMPONENT_ID = caller.COMPONENT_ID
    for name in reversed(caller.SCHEMA.keys()):
        if name.startswith("operation") and name.endswith("_ecount"):
            LAST_OPERATION_NUMBER = int(name[9:-7])
            break

    global mqtt_client
    mqtt_client = caller.mqtt_client


def refresh(caller):
    pass


def update_part(sensor, uid, schema, **kwargs):
    part_id = kwargs["part_id"]
    previous_operation_number = sensor.get_property(uid, schema, "operation_number")
    if previous_operation_number is None:
        return False

    if previous_operation_number > 0:
        properties = collections.OrderedDict()
        properties["part_id"] = part_id
        properties["operation_number"] = 0
        properties["operation_astatus"] = "GOOD"
        properties["operation_estatus"] = "GOOD"
        properties["is_operation_checked"] = False
        properties["operation0_acount"] = 1
        properties["operation0_ecount"] = 1
        for number in range(1, LAST_OPERATION_NUMBER + 1):
            properties["operation" + str(number) + "_acount"] = 0
            properties["operation" + str(number) + "_ecount"] = 0
        if not sensor.set_properties(uid, schema, properties):
            return False

    event = common.build_event(COMPONENT_ID, part_id, "START")
    topic = common.render_topic("component_event", COMPONENT_ID, "all")
    payload = common.serialize_object(event)
    mqtt_client.publish(topic, payload=payload, qos=2)

    # print("update_part:")
    # print(sensor.get_properties(uid, schema))
    return True
