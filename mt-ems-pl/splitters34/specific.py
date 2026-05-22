###############################################################################
# Function definitions                                                        #
###############################################################################
OPERATION_RANGE = None
NUMBER_OF_CYCLES = None


###############################################################################
# Function definitions                                                        #
###############################################################################
def initialize(caller):
    global OPERATION_RANGE
    global NUMBER_OF_CYCLES
    OPERATION_RANGE = caller.SPECIFIC_CONFIG["operation_range"]
    NUMBER_OF_CYCLES = caller.SPECIFIC_CONFIG["number_of_cycles"]


def refresh(caller):
    pass


def check_part(sensor, uid, schema, **kwargs):
    # print("check_part:")
    # print(sensor.get_properties(uid, schema))

    splitter_index = kwargs["splitter_index"]

    previous_operation_number = sensor.get_property(uid, schema, "operation_number")
    if previous_operation_number is None:
        return None
    previous_operation_estatus = sensor.get_property(uid, schema, "operation_estatus")
    if previous_operation_estatus is None:
        return None
    previous_operation_ecount = sensor.get_property(
        uid, schema, "operation" + str(previous_operation_number) + "_ecount"
    )
    if previous_operation_ecount is None:
        return None

    if splitter_index <= 0:
        return (
            previous_operation_number <= OPERATION_RANGE[1]
            and previous_operation_estatus == "BAD"
        ) or (
            previous_operation_number == OPERATION_RANGE[1]
            and previous_operation_ecount >= NUMBER_OF_CYCLES
        ) or previous_operation_number > OPERATION_RANGE[1]
    else:
        return previous_operation_number < OPERATION_RANGE[0] - 1


def update_part(sensor, uid, schema, **kwargs):
    # print("update_part:")
    # print(sensor.get_properties(uid, schema))
    return True
