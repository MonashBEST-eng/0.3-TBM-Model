import struct
import time

import can

from config import (
    AXIS0_NODE_ID,
    AXIS1_NODE_ID,
    AXIS_STATE_CLOSED_LOOP_CONTROL,
    AXIS_STATE_IDLE,
    BITRATE,
    BUS_CHANNEL,
    BUS_INTERFACE,
    CLOSED_LOOP_TIMEOUT,
    CMD_GET_ENCODER_ESTIMATES,
    CMD_HEARTBEAT,
    CMD_SET_AXIS_STATE,
    CMD_SET_INPUT_VEL,
    NODE_IDS,
)


class ODriveCAN:
    def __init__(self):
        self.bus = can.interface.Bus(
            interface=BUS_INTERFACE,
            channel=BUS_CHANNEL,
            bitrate=BITRATE,
        )

    def send_can(self, node_id, cmd_id, data=b""):
        arbitration_id = (node_id << 5) | cmd_id
        message = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=False,
        )
        self.bus.send(message)

    def set_axis_state(self, node_id, state):
        self.send_can(node_id, CMD_SET_AXIS_STATE, struct.pack("<I", state))

    def send_velocity(self, node_id, velocity, torque_ff=0.0):
        payload = struct.pack("<ff", velocity, torque_ff)
        self.send_can(node_id, CMD_SET_INPUT_VEL, payload)


    def request_encoder_estimates(self, node_id, timeout=0.05):
        """Request and return (position_turns, velocity_turns_per_second).

        ODrive replies to an RTR frame using the same CAN ID. The response
        payload contains two little-endian float32 values: position and
        velocity. Returns None if no valid response arrives before timeout.
        """
        arbitration_id = (node_id << 5) | CMD_GET_ENCODER_ESTIMATES
        request = can.Message(
            arbitration_id=arbitration_id,
            is_extended_id=False,
            is_remote_frame=True,
            dlc=8,
        )
        self.bus.send(request)

        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            remaining = deadline - time.perf_counter()
            message = self.bus.recv(timeout=max(remaining, 0.0))
            if message is None:
                break

            if message.is_remote_frame:
                continue

            if message.arbitration_id != arbitration_id:
                continue

            if len(message.data) < 8:
                continue

            position, velocity = struct.unpack("<ff", message.data[:8])
            return position, velocity

        return None

    def wait_for_axis_states(
        self,
        node_ids,
        target_state,
        timeout=CLOSED_LOOP_TIMEOUT,
    ):
        pending = set(node_ids)
        deadline = time.perf_counter() + timeout

        while pending and time.perf_counter() < deadline:
            message = self.bus.recv(timeout=0.1)
            if message is None:
                continue

            node_id = message.arbitration_id >> 5
            command_id = message.arbitration_id & 0x1F

            if command_id != CMD_HEARTBEAT or node_id not in pending:
                continue

            if len(message.data) < 8:
                continue

            axis_error, axis_state, *_flags = struct.unpack(
                "<IBBBB",
                message.data[:8],
            )

            if axis_error != 0:
                print(
                    f"Warning: axis {node_id} reports "
                    f"error 0x{axis_error:08X}"
                )

            if axis_state == target_state:
                pending.discard(node_id)

        if pending:
            raise TimeoutError(
                f"Axes {sorted(pending)} never confirmed state "
                f"{target_state}"
            )

    def enter_closed_loop(self):
        print("Requesting closed-loop control on both axes...")
        self.set_axis_state(AXIS0_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)
        self.set_axis_state(AXIS1_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)
        self.wait_for_axis_states(NODE_IDS, AXIS_STATE_CLOSED_LOOP_CONTROL)
        print("Both axes confirmed in closed-loop control.")

    def enter_idle(self):
        self.set_axis_state(AXIS0_NODE_ID, AXIS_STATE_IDLE)
        self.set_axis_state(AXIS1_NODE_ID, AXIS_STATE_IDLE)
        print("Both axes set to idle.")

    def setup_idle(self):
        print("Starting with both axes idle...")
        self.enter_idle()
        print("Motors are idle. Use 'start' to enable them.")

    def hard_stop(self):
        print("Stopping motors...")
        for _ in range(10):
            self.send_velocity(AXIS0_NODE_ID, 0.0)
            time.sleep(0.05)
        self.enter_idle()

    def shutdown(self):
        self.bus.shutdown()
