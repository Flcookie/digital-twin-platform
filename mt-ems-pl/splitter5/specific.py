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


def check_part(sensor, uid, schema, **kwargs):
    # print("check_part:")
    # print(sensor.get_properties(uid, schema))

    is_previous_operation_checked = sensor.get_property(
        uid, schema, "is_operation_checked"
    )
    if is_previous_operation_checked is None:
        return None

    return is_previous_operation_checked


def update_part(sensor, uid, schema, **kwargs):
    part_id = kwargs["part_id"]
    previous_operation_number = sensor.get_property(uid, schema, "operation_number")
    if previous_operation_number is None:
        return False
    previous_operation_estatus = sensor.get_property(uid, schema, "operation_estatus")
    if previous_operation_estatus is None:
        return False

    if (
        (
            previous_operation_number < LAST_OPERATION_NUMBER
            and previous_operation_estatus == "BAD"
        ) or previous_operation_number >= LAST_OPERATION_NUMBER
    ):
        properties = collections.OrderedDict()
        properties["part_id"] = part_id
        properties["operation_number"] = 0
        properties["operation_astatus"] = "GOOD"
        properties["operation_estatus"] = "GOOD"
        properties["is_operation_checked"] = False
        properties["operation0_acount"] = 1
        properties["operation0_ecount"] = 1
        for operation_number in range(1, LAST_OPERATION_NUMBER + 1):
            properties["operation" + str(operation_number) + "_acount"] = 0
            properties["operation" + str(operation_number) + "_ecount"] = 0
        if not sensor.set_properties(uid, schema, properties):
            return False

        event = common.build_event(COMPONENT_ID, part_id, "CHECKOUT")
        topic = common.render_topic("component_event", COMPONENT_ID, "all")
        payload = common.serialize_object(event)
        mqtt_client.publish(topic, payload=payload, qos=2)
    else:
        if not sensor.set_property(uid, schema, "is_operation_checked", False):
            return False

    if previous_operation_estatus == "GOOD":
        if previous_operation_number >= LAST_OPERATION_NUMBER:
            event = common.build_event(COMPONENT_ID, part_id, "FINISH")
            topic = common.render_topic("component_event", COMPONENT_ID, "all")
            payload = common.serialize_object(event)
            mqtt_client.publish(topic, payload=payload, qos=2)
    else:
        event = common.build_event(COMPONENT_ID, part_id, "SCRAP")
        topic = common.render_topic("component_event", COMPONENT_ID, "all")
        payload = common.serialize_object(event)
        mqtt_client.publish(topic, payload=payload, qos=2)

    # print("update_part:")
    # print(sensor.get_properties(uid, schema))
    return True
