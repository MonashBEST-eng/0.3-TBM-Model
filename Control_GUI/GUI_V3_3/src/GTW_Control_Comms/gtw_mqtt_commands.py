## THIS FUNCTION FILE CONTAINS THE MQTT ETHERNET BRAINWORK TO SEND COMMANDS TO THE GATEWAY ECU

# import required modules
import paho.mqtt.client as mqtt
import threading
import time
from queue import Queue
import GTW_Control_Comms.can_command_dictionary as can_dict
import GTW_Control_Comms.odrive_can as odrive_can
from IO_devices.cutterhead_pcan_bridge import get_cutterhead_pcan

# ==================================================
# # ---------------- MQTT CONFIG ----------------
# ==================================================
# STM BROKER ADDRESS
# Defaults below are only used the very first time the app runs — after that
# the Settings panel's Network section calls set_broker() with whatever was
# saved to settings_store before start_mqtt() is ever called, so these two
# lines are really just a fallback for a fresh install.
BROKER = "192.168.1.10"
PORT = 1883

msg_queue = Queue()
client = mqtt.Client()

# ==================================================
# DEFINE_MQTT_topics
# ordrerd based on control panel button order
# ==================================================
TOPIC_EMERGENCY = "tbm/EMERGENCY_STOP"
TOPIC_SYS_INIT_START = "tbm/startup_procedure"
TOPIC_OPERATION_MODE = "tbm/operation_mode"
TOPIC_MOBILITY = "tbm/mobility"
TOPIC_CUTTERHEAD = "tbm/cutterhead"
TOPIC_CONVEYER = "tbm/conveyer"

# H7 TESTING TOPIC :)
TOPIC_LED = "stm32/led"

# Required for subscribing - confirming connection :)
TOPIC_SUB = "stm32/#"

# ==================================================
# HANDSHAKE — proves an actual round trip to the STM gateway, not just
# "broker connection succeeded". Sent once per successful (re)connect from
# on_connect() below; the gateway replies on stm32/handshake_ack, which
# the GUI's update_ui() uses to light the TBM Ready indicator only once
# this specific reply is seen.
# ==================================================
TOPIC_HANDSHAKE_REQ = "tbm/handshake"


def send_handshake():
    """Sends a connection/hello packet to the STM32 gateway. Called
    automatically from on_connect() on every successful (re)connect."""
    client.publish(TOPIC_HANDSHAKE_REQ, "CONNECT_REQUEST")
    msg_queue.put(("mqtt_tx", f"{TOPIC_HANDSHAKE_REQ} | CONNECT_REQUEST"))


# ==================================================
# HEARTBEAT — ongoing 5s deadman's switch, separate from the one-shot
# handshake above. Sent periodically by heartbeat_panel.py's loop, not
# tied to connect/reconnect events. The STM replies on
# stm32/heartbeat_ack, which heartbeat_panel.py watches for.
# ==================================================
TOPIC_HEARTBEAT_REQ = "tbm/heartbeat"


def send_heartbeat():
    """Sends one heartbeat ping. Called every ~5s by heartbeat_panel.py's
    loop (or withheld briefly by its Test button, to genuinely exercise
    the watchdog timeout path)."""
    client.publish(TOPIC_HEARTBEAT_REQ, "PING")
    msg_queue.put(("mqtt_tx", f"{TOPIC_HEARTBEAT_REQ} | PING"))


# ==================================================
# CAN <-> ETHERNET RELAY
# The actual command dictionary (what each action means on the CAN bus)
# now lives in can_command_dictionary.py - this file just uses it to
# publish the encoded frame, keeping the topic-publishing/logging side of
# things here where the rest of the MQTT plumbing already lives.
# ==================================================
TOPIC_CAN_TX = can_dict.TOPIC_CAN_TX
TOPIC_CAN_RX = can_dict.TOPIC_CAN_RX


def _relay_can_command(topic: str, payload: str):
    """Looks up (topic, payload) in the command dictionary and, if found,
    publishes the fully-encoded CAN frame on TOPIC_CAN_TX for the STM to
    relay directly onto the bus. Silently logs and does nothing if this
    exact combo isn't mapped yet (existing command functions below still
    publish their own human-readable topic regardless, for logging/decode
    - this just adds the actual CAN-side effect on top)."""
    entry = can_dict.lookup_can_command(topic, payload)
    if entry is None:
        msg_queue.put(("mqtt_tx", f"(no CAN mapping yet for {topic} | {payload})"))
        return

    can_id, ext, rtr, dlc, data = entry
    frame_payload = can_dict.encode_can_frame(can_id, ext, rtr, dlc, data)
    client.publish(TOPIC_CAN_TX, frame_payload)
    msg_queue.put(("mqtt_tx", f"{TOPIC_CAN_TX} | {frame_payload}"))


def decode_can_rx_payload(payload: str):
    """Thin pass-through to can_command_dictionary.decode_can_rx_payload()
    - kept here too so callers (e.g. the main GUI) only need to import
    gtw_mqtt_commands, not the dictionary module directly."""
    return can_dict.decode_can_rx_payload(payload)


# ==================================================
# NETWORK SETTINGS — used by the Settings panel
# ==================================================
def set_broker(ip: str, port):
    """Update the broker address/port. Call this BEFORE start_mqtt() to
    change where the very first connection attempt goes, or any time after
    start_mqtt() + call reconnect() to apply it to a running connection."""
    global BROKER, PORT
    BROKER = ip
    PORT = int(port)


def reconnect():
    """Force the background MQTT loop to drop and reconnect using whatever
    BROKER/PORT are currently set. Safe to call even if not connected yet."""
    try:
        client.disconnect()
    except Exception:
        pass


# ==================================================
# START MQTT THREAD
# ==================================================
def start_mqtt():
    threading.Thread(target=mqtt_loop, daemon=True).start()
    threading.Thread(target=_periodic_handshake_loop, daemon=True).start()


# How often the handshake is re-sent while connected. This exists because
# send_handshake() previously only fired from on_connect() - which only
# refires when THIS (the GUI's) MQTT connection drops and reconnects.
# When the H7 reboots instead (which happens periodically - see the
# RESET CAUSE / IWDG work elsewhere in this codebase), it's the H7's
# connection to the broker that drops and comes back, not the GUI's. The
# GUI's own client.on_connect() never refires, send_handshake() never
# gets called again, and the H7 comes back up freshly DISARMED
# (gateway_armed=0 on every boot, by design - see main.c) with no way to
# receive a fresh handshake short of restarting the whole GUI process.
# That was the actual cause of "I have to restart the GUI every time I
# want to run the motors."
#
# Resending periodically, independent of any connect/disconnect event,
# means the gateway re-arms within one interval after ANY H7 reboot -
# no detection of the reboot is needed on the GUI side, because the H7
# disarming itself on every boot is exactly what re-triggers the need,
# and this simply keeps re-asserting the handshake regardless of whether
# one was "needed" this cycle. Sending an extra handshake to an already-
# armed gateway is a no-op there (see main.c's handshake handler - it
# only logs "GATEWAY ARMED" on the transition, not on every request).
HANDSHAKE_RESEND_INTERVAL_S = 5.0


def _periodic_handshake_loop():
    while True:
        time.sleep(HANDSHAKE_RESEND_INTERVAL_S)
        try:
            if client.is_connected():
                send_handshake()
        except Exception as error:
            msg_queue.put(("odrive_status", f"[Handshake] periodic resend failed: {error}"))

# ==================================================
# CALLBACKS
# ==================================================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        msg_queue.put(("conn", "Connected"))
        client.subscribe(TOPIC_SUB)
        send_handshake()
    else:
        msg_queue.put(("conn", "Connection Failed"))

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()

    # Push full pipeline
    msg_queue.put(("mqtt_rx", f"{topic} | {payload}"))

client.on_connect = on_connect
client.on_message = on_message

# ==================================================
# MQTT LOOP
# ==================================================
def mqtt_loop():
    while True:
        try:
            client.connect(BROKER, PORT, 60)
            client.loop_forever()
        except Exception as e:
            msg_queue.put(("conn", f"Disconnected: {e}"))
            time.sleep(2)


# ===========================================================================
# ================================ COMMANDS =================================
# Each of these still publishes its original human-readable topic/payload
# (unchanged - used for the control log's readable decode), and now ALSO
# relays the actual CAN frame via _relay_can_command() so the command
# genuinely reaches the bus. To add/change what a command does on the CAN
# bus, edit can_command_dictionary.py - nothing here needs to change.
# ===========================================================================

# safety control buttons
# status is EMERGENCY_STOP, or SAFE_MODE, or deactivate_emergency
def emergency_mode(status):
    client.publish(TOPIC_EMERGENCY, status)
    msg_queue.put(("mqtt_tx", f"{TOPIC_EMERGENCY} | {status}"))
    _relay_can_command(TOPIC_EMERGENCY, status)

    # An E-STOP or SAFE_MODE must also stop the cutterhead. It runs on its
    # own PCAN bus, which the H7 cannot reach, so the message above does
    # not stop it - CutterheadPCAN.emergency_stop() does.
    upper = status.upper()
    if "CLEAR" not in upper and ("STOP" in upper or "SAFE" in upper):
        odrive_emergency_stop()
    elif "CLEAR" in upper:
        # Release the cutterhead's E-STOP latch so START works again.
        # Motion does NOT resume by itself - the operator must press START.
        try:
            get_cutterhead_pcan().clear_emergency()
            msg_queue.put(("odrive_status",
                           "[Cutterhead] E-STOP cleared - press START to run again."))
        except Exception as error:
            msg_queue.put(("odrive_status", f"[Cutterhead] Clear emergency FAILED: {error}"))

# startup initialisation commands - first INITIALISE, then START SYSTEM
# logic implemented on panel side to prevent sending start prior to 15 sec initialisation check period
def system_start_int_mode(state):
    client.publish(TOPIC_SYS_INIT_START, state)
    msg_queue.put(("mqtt_tx", f"{TOPIC_SYS_INIT_START} | {state}"))
    _relay_can_command(TOPIC_SYS_INIT_START, state)

# operation mode commands - manual, auto or safe idle
def operation_mode(mode):
    client.publish(TOPIC_OPERATION_MODE, mode)
    msg_queue.put(("mqtt_tx", f"{TOPIC_OPERATION_MODE} | {mode}"))
    _relay_can_command(TOPIC_OPERATION_MODE, mode)

# mobility commands - most likely for stewart platform control - rn use placeholder eg forward
def mobility_commands(direction):
    client.publish(TOPIC_MOBILITY, direction)
    msg_queue.put(("mqtt_tx", f"{TOPIC_MOBILITY} | {direction}"))
    _relay_can_command(TOPIC_MOBILITY, direction)

# Cutterhead commands - manual, auto or safe idle
def cutterhead_control(instruction):
    client.publish(TOPIC_CUTTERHEAD, instruction)
    msg_queue.put(("mqtt_tx", f"{TOPIC_CUTTERHEAD} | {instruction}"))
    _relay_can_command(TOPIC_CUTTERHEAD, instruction)

# conveyer control - START/STOP/FORWARD/REVERSE (fixed commands, go
# through the normal CAN_COMMANDS dictionary lookup)
def conveyer_control(mode):
    client.publish(TOPIC_CONVEYER, mode)
    msg_queue.put(("mqtt_tx", f"{TOPIC_CONVEYER} | {mode}"))
    _relay_can_command(TOPIC_CONVEYER, mode)


def conveyer_set_speed(speed):
    """Sets the screw conveyer's (BLD-530S, G4 board) target speed,
    0-999. Encodes and publishes the CAN frame directly rather than going
    through _relay_can_command()'s static dictionary lookup, since this
    carries a user-entered numeric value (from the Control Panel's speed
    slider) rather than one of a fixed set of payload strings."""
    can_id, ext, rtr, dlc, data = can_dict.encode_conveyer_speed(speed)
    frame_payload = can_dict.encode_can_frame(can_id, ext, rtr, dlc, data)
    client.publish(TOPIC_CAN_TX, frame_payload)
    msg_queue.put(("mqtt_tx", f"{TOPIC_CAN_TX} | {frame_payload}"))
    msg_queue.put(("mqtt_tx", f"{TOPIC_CONVEYER} | SET_SPEED {speed}"))


# ==================================================
# ODRIVE MOTOR CONTROL — H7 relay, not a local PCAN adapter
# Uses odrive_can.py (protocol) + can_dict.encode_can_frame() (wire format)
# the same way conveyer_set_speed() above uses can_dict directly for a
# dynamic value rather than the static CAN_COMMANDS lookup table. The
# ramp/start/stop state machine that calls these lives in
# IO_devices/odrive_controller.py.
# ==================================================
def odrive_set_axis_state(node_id, state):
    can_id, ext, rtr, dlc, data = odrive_can.encode_set_axis_state(node_id, state)
    frame_payload = can_dict.encode_can_frame(can_id, ext, rtr, dlc, data)
    client.publish(TOPIC_CAN_TX, frame_payload)
    msg_queue.put(("mqtt_tx", f"{TOPIC_CAN_TX} | {frame_payload}"))


def odrive_clear_errors(node_id):
    """Clear_Errors — releases the latch left behind by a tripped safety
    watchdog (WATCHDOG_TIMER_EXPIRED, 0x800) or any other ODrive error, so
    a subsequent closed-loop request can actually succeed. Logged (not
    high-frequency) so an operator can see recovery happening."""
    can_id, ext, rtr, dlc, data = odrive_can.encode_clear_errors(node_id)
    frame_payload = can_dict.encode_can_frame(can_id, ext, rtr, dlc, data)
    client.publish(TOPIC_CAN_TX, frame_payload)
    msg_queue.put(("mqtt_tx", f"{TOPIC_CAN_TX} | {frame_payload}"))


def odrive_send_velocity(node_id, velocity, torque_ff=0.0):
    """Ramped velocity command — sent by the ODrive control loop. Published
    directly WITHOUT going through msg_queue for the normal case: logging
    every frame would flood the comms log.

    Publish failures ARE reported, though. paho returns a result code
    rather than raising, so an unchecked publish() fails silently — which
    looks exactly like a frozen ramp (the last value sticks on the ODrive
    forever). Returns True if the frame was handed to the broker."""
    can_id, ext, rtr, dlc, data = odrive_can.encode_set_velocity(node_id, velocity, torque_ff)
    frame_payload = can_dict.encode_can_frame(can_id, ext, rtr, dlc, data)

    try:
        result = client.publish(TOPIC_CAN_TX, frame_payload)
    except Exception as error:
        msg_queue.put(("odrive_status", f"[ODrive] PUBLISH EXCEPTION: {error}"))
        return False

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        msg_queue.put((
            "odrive_status",
            f"[ODrive] PUBLISH FAILED rc={result.rc} "
            f"(connected={client.is_connected()}) vel={velocity:.3f}"
        ))
        return False

    return True


def odrive_request_encoder(node_id):
    """DEPRECATED - no longer used. Encoder estimates now arrive as ODrive's
    own cyclic broadcast (see ODRIVE BOARD SETUP in odrive_can.py) rather
    than being polled with an RTR frame. Kept as a no-op stub only so any
    stale import doesn't break; safe to delete once nothing references it."""
    pass


def odrive_emergency_stop():
    """IMMEDIATE cutterhead stop over PCAN - zero velocity then idle, on
    both axes - and latch it until CLEAR. See
    CutterheadPCAN.emergency_stop() for why it bypasses the ramped stop.

    The ODrive is on the PCAN bus, not the H7's, so nothing is sent
    through the H7 relay here. The operator is told the real outcome:
    if the cutterhead could not be confirmed stopped, the message says
    FAILED and points to the hardware E-STOP.
    """
    error = None
    try:
        stopped = get_cutterhead_pcan().emergency_stop()
    except Exception as exc:
        stopped, error = False, exc

    if stopped:
        msg_queue.put(("odrive_status",
                       "[Cutterhead] EMERGENCY STOP - zero velocity + idle sent over PCAN."))
    else:
        reason = f": {error}" if error else " (PCAN not connected, or a CAN frame failed)"
        msg_queue.put(("odrive_status",
                       f"[Cutterhead] EMERGENCY STOP FAILED{reason}. "
                       "The cutterhead may still be moving - use the hardware E-STOP."))


# testing h7 - activate specific led on h7 dev board
# NOT relayed as a CAN frame - the STM handles this directly, controlling
# its own onboard LEDs (see can_command_dictionary.py's note).
def set_led(color):
    client.publish(TOPIC_LED, color)
    msg_queue.put(("mqtt_tx", f"{TOPIC_LED} | {color}"))