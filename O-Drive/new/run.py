import can

import struct

import time
 
BUS_INTERFACE = "pcan"

BUS_CHANNEL = "PCAN_USBBUS1"

BITRATE = 250000
 
AXIS0_NODE_ID = 0  # master — driven by velocity commands

AXIS1_NODE_ID = 1  # follower — mirrors axis0's position in firmware, no commands needed

NODE_IDS = (AXIS0_NODE_ID, AXIS1_NODE_ID)
 
CMD_HEARTBEAT = 0x01

CMD_SET_AXIS_STATE = 0x07

CMD_SET_INPUT_VEL = 0x0D
 
AXIS_STATE_CLOSED_LOOP_CONTROL = 8

AXIS_STATE_IDLE = 1
 
LOOP_PERIOD = 0.05  # 20 Hz

CLOSED_LOOP_TIMEOUT = 5.0  # s to wait for both axes to confirm state
 
bus = can.interface.Bus(

    interface=BUS_INTERFACE,

    channel=BUS_CHANNEL,

    bitrate=BITRATE

)
 
 
def send_can(node_id, cmd_id, data=b""):

    arb_id = (node_id << 5) | cmd_id

    msg = can.Message(

        arbitration_id=arb_id,

        data=data,

        is_extended_id=False

    )

    bus.send(msg)
 
 
def set_axis_state(node_id, state):

    data = struct.pack("<I", state)

    send_can(node_id, CMD_SET_AXIS_STATE, data)
 
 
def send_vel(node_id, velocity, torque_ff=0.0):

    data = struct.pack("<ff", velocity, torque_ff)

    send_can(node_id, CMD_SET_INPUT_VEL, data)
 
 
def wait_for_axis_states(node_ids, target_state, timeout=CLOSED_LOOP_TIMEOUT):

    """

    Block until a Heartbeat message confirming `target_state` has been seen

    for every node in node_ids, or raise TimeoutError. Both axes need to be

    in closed-loop control for mirroring to work — axis1 won't track axis0

    if it's still idle.

    """

    pending = set(node_ids)

    deadline = time.perf_counter() + timeout
 
    while pending and time.perf_counter() < deadline:

        msg = bus.recv(timeout=0.1)

        if msg is None:

            continue
 
        msg_node_id = msg.arbitration_id >> 5

        msg_cmd_id = msg.arbitration_id & 0x1F
 
        if msg_cmd_id != CMD_HEARTBEAT or msg_node_id not in pending:

            continue
 
        # Heartbeat payload (ODrive CAN Simple, fw 0.5.x):

        # axis_error(u32), axis_state(u8), motor_flags(u8),

        # encoder_flags(u8), controller_flags(u8)

        _axis_error, axis_state, *_flags = struct.unpack("<IBBBB", msg.data)
 
        if axis_state == target_state:

            pending.discard(msg_node_id)
 
    if pending:

        raise TimeoutError(

            f"Axes {sorted(pending)} never confirmed state {target_state}"

        )
 
 
def setup_can_control():

    print("Requesting closed-loop control on both axes...")

    # Both axes must enter closed loop — axis1 needs to be active for its

    # mirror-mode following to engage, even though it never gets a velocity

    # command directly.

    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)

    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)
 
    wait_for_axis_states(NODE_IDS, AXIS_STATE_CLOSED_LOOP_CONTROL)

    print("Both axes confirmed in closed-loop control.")
 
 
def stop_motors():

    print("Stopping motors...")

    for _ in range(10):

        send_vel(AXIS0_NODE_ID, 0.0)

        time.sleep(0.05)
 
    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_IDLE)

    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_IDLE)
 
 
def run_velocity_loop(velocity):

    """Fixed-rate loop driving axis0 only. axis1 tracks it automatically

    in firmware via mirror mode — no CAN traffic needed for it."""

    next_tick = time.perf_counter()

    while True:

        send_vel(AXIS0_NODE_ID, velocity)
 
        next_tick += LOOP_PERIOD

        sleep_time = next_tick - time.perf_counter()

        if sleep_time > 0:

            time.sleep(sleep_time)

        else:

            # We're falling behind schedule; resync instead of compounding drift.

            next_tick = time.perf_counter()
 
 
try:

    setup_can_control()

    print("Sending velocity to axis0 (axis1 mirrors it in firmware)... Ctrl+C to stop.")

    run_velocity_loop(velocity=2.0)
 
except KeyboardInterrupt:

    stop_motors()
 
except TimeoutError as e:

    print(f"Sync setup failed: {e}")

    stop_motors()
 
finally:

    bus.shutdown()

    print("CAN bus shutdown.")
 