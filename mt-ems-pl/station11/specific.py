import random


###############################################################################
# Function definitions                                                        #
###############################################################################
OPERATION_NUMBER = None
OPERATION_STATUS_CDF = None
REWORK_PROBABILITY = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def initialize(caller):
    global OPERATION_NUMBER
    global OPERATION_STATUS_CDF
    global REWORK_PROBABILITY
    OPERATION_NUMBER = caller.SPECIFIC_CONFIG["operation_number"]
    OPERATION_STATUS_CDF = [
        caller.SPECIFIC_CONFIG["truly_good_probability"], 0.0, 0.0, 0.0
    ]
    OPERATION_STATUS_CDF[1] = (
        OPERATION_STATUS_CDF[0] + caller.SPECIFIC_CONFIG["falsely_good_probability"]
    )
    OPERATION_STATUS_CDF[2] = (
        OPERATION_STATUS_CDF[1] + caller.SPECIFIC_CONFIG["truly_bad_probability"]
    )
    OPERATION_STATUS_CDF[3] = (
        OPERATION_STATUS_CDF[2] + caller.SPECIFIC_CONFIG["falsely_bad_probability"]
    )
    REWORK_PROBABILITY = caller.SPECIFIC_CONFIG["rework_probability"]


def refresh(caller):
    pass


def check_part(sensor, uid, schema, **kwargs):
    # print("check_part:")
    # print(sensor.get_properties(uid, schema))

    previous_operation_number = sensor.get_property(uid, schema, "operation_number")
    if previous_operation_number is None:
        return None
    previous_operation_estatus = sensor.get_property(uid, schema, "operation_estatus")
    if previous_operation_estatus is None:
        return None

    return not (
        previous_operation_number == OPERATION_NUMBER - 1
        and previous_operation_estatus == "GOOD"
    )


def update_part(sensor, uid, schema, **kwargs):
    previous_operation_astatus = sensor.get_property(uid, schema, "operation_astatus")
    if previous_operation_astatus is None:
        return False
    operation_acount = sensor.get_property(
        uid, schema, "operation" + str(OPERATION_NUMBER) + "_acount"
    )
    if operation_acount is None:
        return False
    operation_ecount = sensor.get_property(
        uid, schema, "operation" + str(OPERATION_NUMBER) + "_ecount"
    )
    if operation_ecount is None:
        return False

    if not sensor.set_property(uid, schema, "operation_number", OPERATION_NUMBER):
        return False
    if previous_operation_astatus == "GOOD":
        random_sample = random.random()
        if random_sample < OPERATION_STATUS_CDF[0]:
            if not sensor.set_property(uid, schema, "operation_astatus", "GOOD"):
                return False
            if not sensor.set_property(uid, schema, "operation_estatus", "GOOD"):
                return False
            if not sensor.set_property(
                uid, schema, "operation" + str(OPERATION_NUMBER) + "_acount",
                operation_acount + 1
            ):
                return False
            if not sensor.set_property(
                uid, schema, "operation" + str(OPERATION_NUMBER) + "_ecount",
                operation_ecount + 1
            ):
                return False
        elif random_sample < OPERATION_STATUS_CDF[1]:
            if random.random() < REWORK_PROBABILITY:
                if not sensor.set_property(uid, schema, "operation_astatus", "NONE"):
                    return False
            else:
                if not sensor.set_property(uid, schema, "operation_astatus", "BAD"):
                    return False
            if not sensor.set_property(uid, schema, "operation_estatus", "GOOD"):
                return False
            if not sensor.set_property(
                uid, schema, "operation" + str(OPERATION_NUMBER) + "_ecount",
                operation_ecount + 1
            ):
                return False
        elif random_sample < OPERATION_STATUS_CDF[2]:
            if random.random() < REWORK_PROBABILITY:
                if not sensor.set_property(uid, schema, "operation_astatus", "NONE"):
                    return False
            else:
                if not sensor.set_property(uid, schema, "operation_astatus", "BAD"):
                    return False
            if not sensor.set_property(uid, schema, "operation_estatus", "BAD"):
                return False
        else:
            if not sensor.set_property(uid, schema, "operation_astatus", "GOOD"):
                return False
            if not sensor.set_property(uid, schema, "operation_estatus", "BAD"):
                return False
            if not sensor.set_property(
                uid, schema, "operation" + str(OPERATION_NUMBER) + "_acount",
                operation_acount + 1
            ):
                return False
    else:
        if not sensor.set_property(uid, schema, "operation_astatus", "BAD"):
            return False
        if not sensor.set_property(uid, schema, "operation_estatus", "BAD"):
            return False

    # print("update_part:")
    # print(sensor.get_properties(uid, schema))
    return True
