import threading
import common


###############################################################################
# Constant declarations                                                       #
###############################################################################
STAGE_TYPES = None
STAGE_COMPONENT_IDS = None
STAGE_WIP_INCREMENT_EVENTS = None
STAGE_WIP_DECREMENT_EVENTS = None
STAGE_OPERATION_NUMBERS = None
TRADE_OFF_FACTOR = None
LAST_OPERATION_NUMBER = None


###############################################################################
# Variable declarations                                                       #
###############################################################################
wip_lock = None
stage_wips = None
unchecked_parts = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def initialize(caller):
    global STAGE_TYPES
    global STAGE_COMPONENT_IDS
    global STAGE_WIP_INCREMENT_EVENTS
    global STAGE_WIP_DECREMENT_EVENTS
    global STAGE_OPERATION_NUMBERS
    global TRADE_OFF_FACTOR
    global LAST_OPERATION_NUMBER
    STAGE_TYPES = caller.SPECIFIC_CONFIG["stage_types"]
    STAGE_COMPONENT_IDS = caller.SPECIFIC_CONFIG["stage_component_ids"]
    STAGE_WIP_INCREMENT_EVENTS = caller.SPECIFIC_CONFIG["stage_wip_increment_events"]
    STAGE_WIP_DECREMENT_EVENTS = caller.SPECIFIC_CONFIG["stage_wip_decrement_events"]
    STAGE_OPERATION_NUMBERS = caller.SPECIFIC_CONFIG["stage_operation_numbers"]
    TRADE_OFF_FACTOR = caller.SPECIFIC_CONFIG["trade_off_factor"]
    LAST_OPERATION_NUMBER = STAGE_OPERATION_NUMBERS[-2][-1]

    global wip_lock
    global stage_wips
    global unchecked_parts
    wip_lock = threading.Lock()
    stage_wips = [0 for _ in range(len(STAGE_TYPES))]
    unchecked_parts = [set() for _ in range(len(STAGE_TYPES))]

    on_connect = caller.mqtt_client.on_connect
    on_message = caller.mqtt_client.on_message

    def on_connect_(client, userdata, flags, rc):
        on_connect(client, userdata, flags, rc)

        for index in range(len(STAGE_TYPES)):
            topic = common.render_topic(
                "component_wip", "master", STAGE_COMPONENT_IDS[index]
            )
            client.subscribe(topic, qos=2)
            topic = common.render_topic(
                "component_event", STAGE_COMPONENT_IDS[index], "all"
            )
            client.subscribe(topic, qos=2)

    def on_message_(client, userdata, msg):
        on_message(client, userdata, msg)

        context, source_id, target_id = common.parse_topic(msg.topic)
        payload = msg.payload.decode("utf-8")
        if caller.system_status == "STOP":
            if context == "component_wip":
                index = STAGE_COMPONENT_IDS.index(target_id)
                stage_wips[index] = int(payload)
        else:
            if context == "component_event":
                event = common.deserialize_object(payload)
                with wip_lock:
                    for index in range(len(STAGE_TYPES)):
                        for increment_event in STAGE_WIP_INCREMENT_EVENTS[index]:
                            if (
                                event["component_id"] == increment_event["component_id"]
                                and event["activity"] == increment_event["activity"]
                            ):
                                stage_wips[index] += 1
                                break
                        else:
                            continue
                        break
                    for index in range(len(STAGE_TYPES)):
                        for decrement_event in STAGE_WIP_DECREMENT_EVENTS[index]:
                            if (
                                event["component_id"] == decrement_event["component_id"]
                                and event["activity"] == decrement_event["activity"]
                            ):
                                stage_wips[index] -= 1
                                break
                        else:
                            continue
                        break

    caller.mqtt_client.on_connect = on_connect_
    caller.mqtt_client.on_message = on_message_


def refresh(caller):
    global stage_wips
    global unchecked_parts
    for index in range(len(STAGE_TYPES)):
        stage_wips[index] = 0
        unchecked_parts[index].clear()


def check_part(sensor, uid, schema, **kwargs):
    # print("check_part:")
    # print(sensor.get_properties(uid, schema))

    part_id = kwargs["part_id"]
    is_previous_operation_checked = sensor.get_property(
        uid, schema, "is_operation_checked"
    )
    if is_previous_operation_checked is None:
        return None
    previous_operation_number = sensor.get_property(uid, schema, "operation_number")
    if previous_operation_number is None:
        return None
    previous_operation_estatus = sensor.get_property(uid, schema, "operation_estatus")
    if previous_operation_estatus is None:
        return None

    part_priority = -1.0
    highest_part_priority = 0.0
    if not is_previous_operation_checked:
        previous_stage_index = -1
        for index in range(len(STAGE_TYPES) - 1):
            if previous_operation_number in STAGE_OPERATION_NUMBERS[index]:
                previous_stage_index = index
                break
        unchecked_parts[previous_stage_index].add(part_id)
        with wip_lock:
            stage_wip_sum = sum(stage_wips[:-2])
            for index in range(len(STAGE_TYPES) - 1):
                if len(unchecked_parts[index]) <= 0:
                    priority = -1.0
                else:
                    if stage_wips[index] < 0:
                        priority = (
                            TRADE_OFF_FACTOR * (stage_wip_sum / 1)
                            + (1 - TRADE_OFF_FACTOR) * (len(STAGE_TYPES) - index - 1)
                        )
                    else:
                        priority = (
                            TRADE_OFF_FACTOR * (stage_wip_sum / (stage_wips[index] + 1))
                            + (1 - TRADE_OFF_FACTOR) * (len(STAGE_TYPES) - index - 1)
                        )
                if index == previous_stage_index:
                    part_priority = priority
                if priority > highest_part_priority:
                    highest_part_priority = priority
        # print(f"Stage WIPs: {stage_wips}")
        # print(f"Unchecked Parts: {unchecked_parts}")
        # print(f"Part ID: {part_id}")
        # print(f"Part Priority: {part_priority}")
        # print(f"Highest Part Priority: {highest_part_priority}")

    return not (
        not is_previous_operation_checked
        and (
            (
                previous_operation_number < LAST_OPERATION_NUMBER
                and previous_operation_estatus == "BAD"
            ) or previous_operation_number >= LAST_OPERATION_NUMBER
        ) and part_priority >= highest_part_priority
    )


def update_part(sensor, uid, schema, **kwargs):
    part_id = kwargs["part_id"]
    previous_operation_number = sensor.get_property(uid, schema, "operation_number")
    if previous_operation_number is None:
        return False
    previous_operation_astatus = sensor.get_property(uid, schema, "operation_astatus")
    if previous_operation_astatus is None:
        return False
    previous_operation_estatus = sensor.get_property(
        uid, schema, "operation_estatus"
    )
    if previous_operation_estatus is None:
        return False
    previous_operation_ecount = sensor.get_property(
        uid, schema, "operation" + str(previous_operation_number) + "_ecount"
    )
    if previous_operation_ecount is None:
        return False

    previous_stage_index = -1
    for index in range(len(STAGE_TYPES) - 1):
        if previous_operation_number in STAGE_OPERATION_NUMBERS[index]:
            previous_stage_index = index
            break
    if previous_operation_astatus == "NONE":
        if previous_operation_ecount <= 0:
            previous_previous_operation_number = previous_operation_number - 1
        else:
            if (
                STAGE_TYPES[previous_stage_index] == "LOOPING"
                and previous_operation_number == (
                    STAGE_OPERATION_NUMBERS[previous_stage_index][0]
                )
            ):
                previous_previous_operation_number = (
                    STAGE_OPERATION_NUMBERS[previous_stage_index][-1]
                )
            else:
                previous_previous_operation_number = previous_operation_number - 1

        if not sensor.set_property(
            uid, schema, "operation_number", previous_previous_operation_number
        ):
            return False
        if not sensor.set_property(uid, schema, "operation_astatus", "GOOD"):
            return False
        if previous_operation_estatus == "GOOD":
            if not sensor.set_property(
                uid, schema, "operation" + str(previous_operation_number)
                + "_ecount", previous_operation_ecount - 1
            ):
                return False
        else:
            if not sensor.set_property(uid, schema, "operation_estatus", "GOOD"):
                return False
    elif previous_operation_astatus == "GOOD":
        if previous_operation_estatus == "BAD":
            if not sensor.set_property(uid, schema, "operation_estatus", "GOOD"):
                return False
            if not sensor.set_property(
                uid, schema, "operation" + str(previous_operation_number)
                + "_ecount", previous_operation_ecount + 1
            ):
                return False
    else:
        if previous_operation_estatus == "GOOD":
            if not sensor.set_property(uid, schema, "operation_estatus", "BAD"):
                return False
    if not sensor.set_property(uid, schema, "is_operation_checked", True):
        return False

    unchecked_parts[previous_stage_index].discard(part_id)

    # print("update_part:")
    # print(sensor.get_properties(uid, schema))
    return True
