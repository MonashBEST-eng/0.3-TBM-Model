import can
import struct
import time

bus = can.interface.Bus(
    interface="pcan",
    channel="PCAN_USBBUS1",
    bitrate=250000
)

CMD_SET_INPUT_VEL = 0x0D

def send_vel(node_id, velocity, torque_ff=0.0):
    arb_id = (node_id << 5) | CMD_SET_INPUT_VEL
    data = struct.pack("<ff", velocity, torque_ff)

    msg = can.Message(
        arbitration_id=arb_id,
        data=data,
        is_extended_id=False
    )

    bus.send(msg)

print("Sending velocity to both ODrive axes... Ctrl+C to stop.")

try:
    while True:
        send_vel(0, 4)    # axis0 motor
        send_vel(1, 1)    # axis1 motor
        time.sleep(0.05)

except KeyboardInterrupt:
    print("Stopping motors...")
    for _ in range(10):
        send_vel(0, 0.0)
        send_vel(1, 0.0)
        time.sleep(0.05)

bus.shutdown()