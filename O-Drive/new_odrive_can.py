import can
import struct
import time

BUS_INTERFACE = "pcan"
BUS_CHANNEL = "PCAN_USBBUS1"
BITRATE = 250000

AXIS0_NODE_ID = 0
AXIS1_NODE_ID = 1

CMD_SET_AXIS_STATE = 0x07
CMD_SET_INPUT_VEL = 0x0D

AXIS_STATE_CLOSED_LOOP_CONTROL = 8
AXIS_STATE_IDLE = 1

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

def setup_can_control():
    print("Putting both axes into closed-loop control...")

    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)
    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)

    time.sleep(1)

def stop_motors():
    print("Stopping motors...")

    for _ in range(10):
        send_vel(AXIS0_NODE_ID, 0.0)
        send_vel(AXIS1_NODE_ID, 0.0)
        time.sleep(0.05)

    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_IDLE)
    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_IDLE)

try:
    setup_can_control()

    print("Sending velocity to both ODrive axes... Ctrl+C to stop.")

    while True:
        send_vel(AXIS0_NODE_ID, 2.0)
        send_vel(AXIS1_NODE_ID, 2.0)
        time.sleep(0.05)

except KeyboardInterrupt:
    stop_motors()

finally:
    bus.shutdown()
    print("CAN bus shutdown.")