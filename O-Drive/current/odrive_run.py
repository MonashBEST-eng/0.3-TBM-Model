import can
import struct
import time
import threading
import queue

# CAN Settings 
BUS_INTERFACE = "pcan"
BUS_CHANNEL = "PCAN_USBBUS1"
BITRATE = 250000
AXIS0_NODE_ID = 0  # master — driven by velocity commands
AXIS1_NODE_ID = 1  # follower — mirrors axis0's position in firmware, no commands needed
NODE_IDS = (AXIS0_NODE_ID, AXIS1_NODE_ID)
CMD_HEARTBEAT = 0x01
CMD_SET_AXIS_STATE = 0x07
CMD_SET_INPUT_VEL = 0x0D

# O-Drive Settings
AXIS_STATE_CLOSED_LOOP_CONTROL = 8
AXIS_STATE_IDLE = 1
LOOP_PERIOD = 0.05  # 20 Hz
CLOSED_LOOP_TIMEOUT = 5.0  # s to wait for both axes to confirm state
CRUISE_VELOCITY = 5.0     # turns/s — target speed used by "start"
VELOCITY_STEP = 1.0      # turns/s — change per "+"/"-" command
MAX_VELOCITY = 25.0       # turns/s — safety ceiling for target speed
RAMP_RATE = 2.0           # turns/s^2 — how fast current_velocity chases target
 
bus = can.interface.Bus(
    interface=BUS_INTERFACE,
    channel=BUS_CHANNEL,
    bitrate=BITRATE
)

command_queue = queue.Queue()

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
    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)
    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_CLOSED_LOOP_CONTROL)
    wait_for_axis_states(NODE_IDS, AXIS_STATE_CLOSED_LOOP_CONTROL)
    print("Both axes confirmed in closed-loop control.")

def stop_motors_hard():
    """Immediate stop — only used on exit/error, not for the "stop" command."""
    print("Stopping motors...")
    for _ in range(10):
        send_vel(AXIS0_NODE_ID, 0.0)
        time.sleep(0.05)
 
    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_IDLE)
    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_IDLE)

def input_thread_fn():
    """Reads terminal lines and pushes commands onto the queue.
    Runs in its own thread so it never blocks the CAN send loop."""
    print_help()

    while True:
        try:
            line = input().strip().lower()
        except EOFError:
            break
        if line:
            command_queue.put(line)

def print_help():
    print(
        "\nCommands:\n"
        "  start         Start at cruise velocity\n"
        "  stop          Ramp down to zero\n"
        "  speed <value> Set target speed in turns/s\n"
        "  +             Increase target speed\n"
        "  -             Decrease target speed\n"
        "  quit          Stop motors and exit\n"
    )

def run_control_loop():
    """Fixed-rate loop. Every tick:
      1. drain any pending terminal commands, updating target_velocity
      2. ramp current_velocity toward target_velocity
      3. send current_velocity to axis0 (axis1 follows via mirror mode)
    """

    target_velocity = 0.0
    current_velocity = 0.0
    running = False  # whether we're in "started" state (target tracks cruise speed)
    next_tick = time.perf_counter()
    last_tick = next_tick
 
    while True:
        now = time.perf_counter()
        dt = now - last_tick
        last_tick = now
        # --- process any queued commands --- #
        while True:
            try:
                cmd = command_queue.get_nowait()
                
            except queue.Empty:
                break
 
            if cmd in ("start", "s"):
                running = True
                target_velocity = CRUISE_VELOCITY
                print(f"Ramping up to {target_velocity} turns/s...")

            elif cmd in ("stop", "x"):
                running = False
                target_velocity = 0.0
                print("Ramping down to stop...")

            elif cmd in ("+", "up", "faster", "increase"):
                if running:
                    target_velocity = min(target_velocity + VELOCITY_STEP, MAX_VELOCITY)
                    print(f"Target velocity now {target_velocity} turns/s")
                else:
                    print("Not running — use 'start' first.")

            elif cmd in ("-", "down", "slower", "decrease"):
                if running:
                    target_velocity = max(target_velocity - VELOCITY_STEP, 0.0)
                    print(f"Target velocity now {target_velocity} turns/s")
                else:
                    print("Not running — use 'start' first.")

            elif cmd.startswith("speed"):
                try:
                    requested_velocity = float(cmd.split(maxsplit=1)[1])
                    
                    if requested_velocity < 0:
                        print("Speed must be 0 or greater.")

                    elif requested_velocity > MAX_VELOCITY:
                        print(
                            f"Speed limited to MAX_VELOCITY "
                            f"({MAX_VELOCITY} turns/s)."
                        )
                        target_velocity = MAX_VELOCITY
                        running = True

                    else:
                        target_velocity = requested_velocity
                        running = requested_velocity > 0.0

                        print(
                            f"Target velocity set to "
                            f"{target_velocity} turns/s"
                        )

                except ValueError:
                    print("Usage: speed <turns/s>")

            elif cmd in ("quit", "q", "exit"):
                raise KeyboardInterrupt
            elif cmd in ("help", "?"):
                print_help()
            else:
                print(f"Unknown command: {cmd!r}")
                print_help()
 
        # --- ramp current_velocity toward target_velocity ---
        max_step = RAMP_RATE * dt
        diff = target_velocity - current_velocity
        if abs(diff) <= max_step:
            current_velocity = target_velocity

        else:
            current_velocity += max_step if diff > 0 else -max_step
 
        send_vel(AXIS0_NODE_ID, current_velocity)
        next_tick += LOOP_PERIOD
        sleep_time = next_tick - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            # Falling behind schedule; resync instead of compounding drift.
            next_tick = time.perf_counter()
 
 
try:
    setup_can_control()
    input_thread = threading.Thread(target=input_thread_fn, daemon=True)
    input_thread.start()
    run_control_loop()
 
except KeyboardInterrupt:
    stop_motors_hard()
 
except TimeoutError as e:
    print(f"Sync setup failed: {e}")
    stop_motors_hard()
 
finally:
    bus.shutdown()
    print("CAN bus shutdown.")