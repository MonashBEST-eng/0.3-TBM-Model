# odrive_can.py
#
# ODrive "CAN Simple" protocol layer, built on top of the existing TBM CAN
# relay - see can_command_dictionary.py for the wire format
# ("<hex_id>,<ext>,<rtr>,<dlc>,<hex_data>") and TOPIC_CAN_TX/TOPIC_CAN_RX.
# This file only builds/decodes raw CAN Simple frames; it knows nothing
# about MQTT or the STM relay. gtw_mqtt_commands.py uses these functions
# the same way it already uses can_command_dictionary.py (see
# odrive_set_axis_state / odrive_send_velocity / odrive_request_encoder
# there, following the same pattern as conveyer_set_speed()).
#
# Two ODrive axes, matching the original bench-test rig:
#   AXIS0 = master, driven directly by velocity commands
#   AXIS1 = follower, mirrors AXIS0's position in ODrive firmware
#
# CAN ID layout (ODrive CAN Simple default): arbitration_id = (node_id<<5)|cmd_id
#   AXIS0 (node 0): heartbeat=0x01  set_axis_state=0x07  get_encoder=0x09  set_vel=0x0D
#   AXIS1 (node 1): heartbeat=0x21  set_axis_state=0x27  get_encoder=0x29  set_vel=0x2D
#
# These sit entirely below 0x2E and don't collide with any TBM subsystem ID
# in can_command_dictionary.py (0x010/0x020/0x030/0x040/0x050/0x080) -
# re-check this comment if either side's ID ranges ever change.

import struct

AXIS0_NODE_ID = 0
AXIS1_NODE_ID = 1
NODE_IDS = (AXIS0_NODE_ID, AXIS1_NODE_ID)

CMD_HEARTBEAT             = 0x01
CMD_SET_AXIS_STATE        = 0x07
CMD_GET_ENCODER_ESTIMATES = 0x09
CMD_SET_INPUT_VEL         = 0x0D

AXIS_STATE_IDLE                = 1
AXIS_STATE_CLOSED_LOOP_CONTROL = 8


def _arbitration_id(node_id: int, cmd_id: int) -> int:
    return (node_id << 5) | cmd_id


def identify_frame(can_id: int):
    """Splits a raw arbitration ID back into (node_id, cmd_id)."""
    return can_id >> 5, can_id & 0x1F


def is_odrive_frame(can_id: int) -> bool:
    """True if this arbitration ID belongs to one of our two ODrive axes."""
    node_id, _cmd_id = identify_frame(can_id)
    return node_id in NODE_IDS


# ==================================================
# OUTGOING — build (can_id, ext, rtr, dlc, data) tuples, the same shape
# can_command_dictionary.CAN_COMMANDS entries use, ready for
# can_command_dictionary.encode_can_frame().
# ==================================================
def encode_set_axis_state(node_id: int, state: int):
    data = list(struct.pack("<I", state))
    return (_arbitration_id(node_id, CMD_SET_AXIS_STATE), 0, 0, 4, data)


def encode_set_velocity(node_id: int, velocity: float, torque_ff: float = 0.0):
    data = list(struct.pack("<ff", velocity, torque_ff))
    return (_arbitration_id(node_id, CMD_SET_INPUT_VEL), 0, 0, 8, data)


def encode_encoder_request(node_id: int):
    """RTR (remote) frame — asks the ODrive to reply with its encoder
    estimates on this same arbitration ID. Confirm the STM firmware's CAN
    relay actually forwards RTR frames from tbm/can_tx onto the bus; if it
    only forwards data frames, this request will silently never arrive."""
    return (_arbitration_id(node_id, CMD_GET_ENCODER_ESTIMATES), 0, 1, 8, [])


# ==================================================
# INCOMING — decode an already-parsed frame dict, as returned by
# can_command_dictionary.decode_can_rx_payload()
# ==================================================
def decode_heartbeat(data: list):
    """data: list of ints (raw bytes). Returns (axis_error, axis_state), or
    None if this isn't a valid 8-byte heartbeat payload."""
    if len(data) < 8:
        return None
    axis_error, axis_state, *_flags = struct.unpack("<IBBBB", bytes(data[:8]))
    return axis_error, axis_state


def decode_encoder_estimates(data: list):
    """data: list of ints. Returns (position_turns, velocity_turns_s), or
    None if this isn't a valid 8-byte encoder payload."""
    if len(data) < 8:
        return None
    position, velocity = struct.unpack("<ff", bytes(data[:8]))
    return position, velocity
