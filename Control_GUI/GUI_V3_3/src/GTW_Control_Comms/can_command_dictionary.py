# can_command_dictionary.py
#
# The single source of truth for what each GUI action means in terms of
# actual CAN frames. The STM firmware no longer interprets anything - it
# just relays whatever raw frame arrives on tbm/can_tx straight onto the
# CAN bus, and relays every frame it receives back on stm32/can_rx. This
# file is the one place to edit/extend when adding new commands; the STM
# firmware needs no changes at all for a new row here.
#
# Wire format (plain text, matches the STM firmware's parser exactly):
#   "<hex_id>,<ext 0/1>,<rtr 0/1>,<dlc>,<hex_data>"
# e.g. "10,0,0,1,01" = ID 0x010, standard, data frame, DLC 1, data byte 01
#
# Layout: CAN ID groups by subsystem (0x010=safety, 0x020=startup,
# 0x030=operation mode, 0x040=mobility, 0x050=cutterhead, 0x080=conveyor),
# with the data byte distinguishing which action within that subsystem.

# ==================================================
# TOPICS - the two ends of the relay
# ==================================================
TOPIC_CAN_TX = "tbm/can_tx"     # GUI -> STM: frame to transmit onto the CAN bus
TOPIC_CAN_RX = "stm32/can_rx"   # STM -> GUI: frame the STM received off the CAN bus

# ==================================================
# GUI-SIDE COMMAND TOPICS
# These are the human-readable (topic, payload) pairs the rest of the GUI
# already publishes for logging/decode purposes - CAN_COMMANDS below maps
# each one to the actual CAN frame it means.
# ==================================================
TOPIC_EMERGENCY = "tbm/EMERGENCY_STOP"
TOPIC_SYS_INIT_START = "tbm/startup_procedure"
TOPIC_OPERATION_MODE = "tbm/operation_mode"
TOPIC_MOBILITY = "tbm/mobility"
TOPIC_CUTTERHEAD = "tbm/cutterhead"
TOPIC_CONVEYER = "tbm/conveyer"

# ==================================================
# THE COMMAND DICTIONARY
# Add a new row here to add a new command - no firmware changes needed.
# ==================================================
CAN_COMMANDS = {
    # (topic, payload)                          : (can_id, ext, rtr, dlc, [data bytes])
    (TOPIC_EMERGENCY, "EMERGENCY_STOP"):          (0x010, 0, 0, 1, [0x01]),
    (TOPIC_EMERGENCY, "SAFE_MODE"):               (0x010, 0, 0, 1, [0x02]),
    (TOPIC_EMERGENCY, "CLEAR EMERGENCY"):         (0x010, 0, 0, 1, [0x03]),

    (TOPIC_SYS_INIT_START, "INITIALIZE"):         (0x020, 0, 0, 1, [0x01]),
    (TOPIC_SYS_INIT_START, "START_READY"):        (0x020, 0, 0, 1, [0x02]),

    (TOPIC_OPERATION_MODE, "MODE_MANUAL"):        (0x030, 0, 0, 1, [0x01]),
    (TOPIC_OPERATION_MODE, "MODE_AUTO"):          (0x030, 0, 0, 1, [0x02]),
    (TOPIC_OPERATION_MODE, "MODE_SAFE"):          (0x030, 0, 0, 1, [0x03]),

    (TOPIC_MOBILITY, "FORWARD"):                  (0x040, 0, 0, 1, [0x01]),
    (TOPIC_MOBILITY, "LEFT"):                     (0x040, 0, 0, 1, [0x02]),
    (TOPIC_MOBILITY, "STOP"):                     (0x040, 0, 0, 1, [0x03]),
    (TOPIC_MOBILITY, "RIGHT"):                    (0x040, 0, 0, 1, [0x04]),

    (TOPIC_CUTTERHEAD, "active"):                 (0x050, 0, 0, 1, [0x01]),
    (TOPIC_CUTTERHEAD, "deactivate"):             (0x050, 0, 0, 1, [0x02]),
    (TOPIC_CUTTERHEAD, "slow_spin"):              (0x050, 0, 0, 1, [0x03]),
    (TOPIC_CUTTERHEAD, "speed_increase"):         (0x050, 0, 0, 1, [0x04]),
    (TOPIC_CUTTERHEAD, "speed_decrease"):         (0x050, 0, 0, 1, [0x05]),
    (TOPIC_CUTTERHEAD, "stop_spin"):              (0x050, 0, 0, 1, [0x06]),

    # Screw conveyor (BLD-530S, driven by the G4/MCP2515 motor board -
    # matches that firmware's CAN_ID_SCREW_CONVEYER=0x080 command scheme
    # exactly: single ID, first data byte selects the action.
    # SET_SPEED (0x05) is NOT listed here since it carries a dynamic
    # user-entered value rather than a fixed payload string - see
    # encode_conveyer_speed() below, called directly by
    # gtw_mqtt_commands.conveyer_set_speed() instead of going through this
    # static lookup table.
    (TOPIC_CONVEYER, "START"):                    (0x080, 0, 0, 1, [0x01]),
    (TOPIC_CONVEYER, "STOP"):                     (0x080, 0, 0, 1, [0x02]),
    (TOPIC_CONVEYER, "FORWARD"):                  (0x080, 0, 0, 1, [0x03]),
    (TOPIC_CONVEYER, "REVERSE"):                  (0x080, 0, 0, 1, [0x04]),

    # NOTE: "stm32/led" deliberately has NO entry here - LED commands
    # control the STM's own onboard LEDs directly (handled locally in its
    # firmware), not a CAN bus device, so they stay on their own direct
    # topic/payload path rather than going through this relay.
}





# ==================================================
# WIRE FORMAT ENCODE / DECODE
# ==================================================
def encode_can_frame(can_id: int, ext: int, rtr: int, dlc: int, data) -> str:
    """Builds the wire-format string the STM firmware's parser expects."""
    data_hex = "".join(f"{b:02X}" for b in data[:dlc])
    return f"{can_id:X},{ext},{rtr},{dlc},{data_hex}"


def lookup_can_command(topic: str, payload: str):
    """Looks up (topic, payload) in CAN_COMMANDS. Returns the raw
    (can_id, ext, rtr, dlc, data) tuple, or None if this combo isn't
    mapped yet."""
    return CAN_COMMANDS.get((topic, payload))


# SCREW CONVEYER CUSTOM SPEED DEFINE CANBUS FUNCTION
def encode_conveyer_speed(speed: int):
    """SET_SPEED for the screw conveyer (BLD-530S, G4 board, CAN ID
    0x080) - a 2-segment command: [cmd_byte=0x05, speed_hi, speed_lo].
    16-bit big-endian value, clamped 0-999 to match the G4 firmware's own
    MOTOR_SPEED_MAX clamp (matching it here too so the GUI's slider range
    and the firmware's actual behavior stay honest with each other).
    Returns the same (can_id, ext, rtr, dlc, data) shape as a
    CAN_COMMANDS lookup, for encode_can_frame() to use directly."""
    speed = max(0, min(999, int(speed)))
    return (0x080, 0, 0, 3, [0x05, (speed >> 8) & 0xFF, speed & 0xFF])



def decode_can_rx_payload(payload: str):
    """Decodes a TOPIC_CAN_RX payload (same wire format) back into a dict
    - used to react to CAN frames the STM relayed from the bus (e.g. other
    boards indicating status), without needing to know the wire format
    itself. Returns None if malformed."""
    try:
        parts = payload.split(",", 4)
        can_id = int(parts[0], 16)
        ext = int(parts[1])
        rtr = int(parts[2])
        dlc = int(parts[3])
        hexdata = parts[4] if len(parts) > 4 else ""
        data = [int(hexdata[i:i + 2], 16) for i in range(0, min(len(hexdata), dlc * 2), 2)]
        return {"id": can_id, "ext": ext, "rtr": rtr, "dlc": dlc, "data": data}
    except (ValueError, IndexError):
        return None