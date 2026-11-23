# odrive_can.py
#
# ODrive "CAN Simple" protocol layer, built on top of the existing TBM CAN
# relay - see can_command_dictionary.py for the wire format
# ("<hex_id>,<ext>,<rtr>,<dlc>,<hex_data>") and TOPIC_CAN_TX/TOPIC_CAN_RX.
# This file only builds/decodes raw CAN Simple frames; it knows nothing
# about MQTT or the STM relay. gtw_mqtt_commands.py uses these functions
# the same way it already uses can_command_dictionary.py (see
# odrive_set_axis_state / odrive_send_velocity there, following the same
# pattern as conveyer_set_speed()).
#
# TRANSPORT: STM32H7 + MCP2515 (SPI CAN controller) <-> MQTT <-> this GUI.
# The relay is a transparent dumb pipe - it forwards raw CAN frames and
# needs no knowledge of ODrive, so adding the ODrive costs no firmware
# changes beyond acceptance filters and bitrate.
#
# DATA FLOW IS ASYMMETRIC BY DESIGN:
#   GUI -> ODrive : commands only (axis state, velocity setpoints)
#   ODrive -> GUI : cyclic broadcast telemetry (heartbeat + encoder),
#                   unprompted, never polled
#
# Two ODrive axes, matching the original bench-test rig:
#   AXIS0 = master, driven directly by velocity commands
#   AXIS1 = follower, mirrors AXIS0's position in ODrive firmware
#
# CAN ID layout (ODrive CAN Simple default): arbitration_id = (node_id<<5)|cmd_id
#   AXIS0 (node 0): heartbeat=0x01  set_axis_state=0x07  encoder=0x09  set_vel=0x0D
#   AXIS1 (node 1): heartbeat=0x21  set_axis_state=0x27  encoder=0x29  set_vel=0x2D
#
# These sit entirely below 0x2E and don't collide with any TBM subsystem ID
# in can_command_dictionary.py (0x010/0x020/0x030/0x040/0x050/0x080) -
# re-check this comment if either side's ID ranges ever change.
#
# NOTE ON ODRIVE ID PRIORITY: ODrive's default IDs (0x001-0x02D) are
# NUMERICALLY LOWER than every TBM subsystem ID, and on CAN lower ID =
# higher arbitration priority. So ODrive telemetry currently outranks the
# TBM's own emergency-stop frame (0x010) for bus access. Harmless at
# bench-test loads, but if this rig ever grows toward something where
# E-STOP latency matters, renumber the ODrive nodes upward rather than
# leaving safety traffic behind motor chatter.

import struct

AXIS0_NODE_ID = 0
AXIS1_NODE_ID = 1
NODE_IDS = (AXIS0_NODE_ID, AXIS1_NODE_ID)

CMD_HEARTBEAT             = 0x01
CMD_SET_AXIS_STATE        = 0x07
CMD_GET_ENCODER_ESTIMATES = 0x09
CMD_SET_INPUT_VEL         = 0x0D
CMD_CLEAR_ERRORS          = 0x18

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


def encode_clear_errors(node_id: int):
    """Clear_Errors (ODrive CAN Simple cmd_id 0x18). No payload.

    This exists specifically for the case the safety watchdog creates: once
    axis.config.enable_watchdog trips WATCHDOG_TIMER_EXPIRED (0x800), the
    ODrive LATCHES that error and refuses AXIS_STATE_CLOSED_LOOP_CONTROL
    until it is explicitly cleared - re-sending the closed-loop command
    alone does nothing. This was observed directly: state stayed at 1/IDLE
    with error 0x800 after several closed-loop requests were relayed
    through following an H7 reset.

    Without this, recovering after a watchdog trip requires plugging in
    USB and calling dump_errors(odrv0, True) - which defeats having CAN
    control at all. Sending this frame first (see
    OdriveController._wake_axes) lets a normal START recover from a trip
    with no USB involved."""
    return (_arbitration_id(node_id, CMD_CLEAR_ERRORS), 0, 0, 0, [])


# NOTE: there is deliberately no encode_encoder_request() / RTR poll here.
# On THIS rig (firmware 0.5.1) the ODrive broadcasts HEARTBEAT frames
# cyclically at 10 Hz, but 0.5.1 has NO configurable cyclic encoder
# broadcast (can_encoder_rate_ms only exists on 0.5.4+). So:
#
#   WHAT WORKS PASSIVELY : axis state, axis error, link-alive detection
#   WHAT IS NOT AVAILABLE: position / velocity readout
#
# The Control Panel's position/velocity tiles will therefore stay blank
# ("-- turns" / "-- rps") while the state tile updates normally. That is
# expected on 0.5.1, not a bug.
#
# To get position/velocity later, pick one:
#   (a) upgrade ODrive firmware to 0.5.6 and set can_encoder_rate_ms -
#       stays within the same 0.5.x API the calibration docs use, and
#       needs no H7 firmware change; or
#   (b) implement RTR request/response in the H7 firmware and restore a
#       polling method here - more firmware work, and remote-frame
#       handling on the MCP2515 is easy to get subtly wrong.
#
# ==================================================
# ODRIVE BOARD SETUP - firmware 0.5.1 (flat config names, NOT the
# nested `config.can.*` layout used by 0.5.4+)
# Run once over USB in odrivetool, then save + reboot.
# ==================================================
#   odrv0.axis0.config.can_node_id = 0
#   odrv0.axis1.config.can_node_id = 1
#   odrv0.can.set_baud_rate(500000)   # read-only property in 0.5.1 -
#                                     # must be set via this METHOD.
#                                     # MUST match the MCP2515's configured
#                                     # bitrate on the H7 side (500 kbps here).
#   odrv0.save_configuration()
#   odrv0.reboot()
#
# can_heartbeat_rate_ms defaults to 100 (10 Hz) on both axes in 0.5.1 and
# does not need changing.
#
# Bus load from heartbeats alone: 2 axes x 10 Hz = ~20 frames/s.
#
# ==================================================
# MCP2515 ACCEPTANCE FILTER SUGGESTION (H7 firmware side)
# ==================================================
# The MCP2515 has 2 RX buffers and 6 acceptance filters. The only ODrive
# telemetry actually broadcast on 0.5.1 is:
#     axis0: 0x001 (heartbeat)
#     axis1: 0x021 (heartbeat)
# (0x009 / 0x029 encoder frames only appear if you move to option (a) or
# (b) above - leave filter slots for them if you plan to.)
# Filtering in firmware rather than forwarding everything keeps the MQTT
# link and the GUI's msg_queue clear.


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