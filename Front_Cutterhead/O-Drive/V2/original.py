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
AXIS1_NODE_ID = 1  # follower — mirrors axis0's position in firmware
NODE_IDS = (AXIS0_NODE_ID, AXIS1_NODE_ID)

CMD_HEARTBEAT = 0x01
CMD_SET_AXIS_STATE = 0x07
CMD_SET_INPUT_VEL = 0x0D

# ODrive Settings
AXIS_STATE_IDLE = 1
AXIS_STATE_CLOSED_LOOP_CONTROL = 8

LOOP_PERIOD = 0.05
CLOSED_LOOP_TIMEOUT = 5.0

CRUISE_VELOCITY = 5.0
VELOCITY_STEP = 2.0
MAX_VELOCITY = 30.0
RAMP_RATE = 1.0

# How close to zero is considered completely stopped
ZERO_VELOCITY_THRESHOLD = 0.001

bus = can.interface.Bus(
    interface=BUS_INTERFACE,
    channel=BUS_CHANNEL,
    bitrate=BITRATE,
)

command_queue = queue.Queue()


def send_can(node_id, cmd_id, data=b""):
    arbitration_id = (node_id << 5) | cmd_id

    message = can.Message(
        arbitration_id=arbitration_id,
        data=data,
        is_extended_id=False,
    )

    bus.send(message)


def set_axis_state(node_id, state):
    data = struct.pack("<I", state)
    send_can(node_id, CMD_SET_AXIS_STATE, data)


def send_vel(node_id, velocity, torque_ff=0.0):
    data = struct.pack("<ff", velocity, torque_ff)
    send_can(node_id, CMD_SET_INPUT_VEL, data)


def wait_for_axis_states(
    node_ids,
    target_state,
    timeout=CLOSED_LOOP_TIMEOUT,
):
    """
    Wait until every requested axis reports the target state through its
    heartbeat message.
    """

    pending = set(node_ids)
    deadline = time.perf_counter() + timeout

    while pending and time.perf_counter() < deadline:
        message = bus.recv(timeout=0.1)

        if message is None:
            continue

        message_node_id = message.arbitration_id >> 5
        message_command_id = message.arbitration_id & 0x1F

        if message_command_id != CMD_HEARTBEAT:
            continue

        if message_node_id not in pending:
            continue

        if len(message.data) < 8:
            continue

        # Heartbeat payload:
        # axis_error      u32
        # axis_state      u8
        # motor_flags     u8
        # encoder_flags   u8
        # controller_flags u8
        axis_error, axis_state, *_flags = struct.unpack(
            "<IBBBB",
            message.data[:8],
        )

        if axis_error != 0:
            print(
                f"Warning: axis {message_node_id} reports "
                f"error 0x{axis_error:08X}"
            )

        if axis_state == target_state:
            pending.discard(message_node_id)

    if pending:
        raise TimeoutError(
            f"Axes {sorted(pending)} never confirmed state "
            f"{target_state}"
        )


def enter_closed_loop():
    """
    Put both axes into closed-loop control.

    Both axes must be active because axis1's mirror controller does not
    operate while axis1 is idle.
    """

    print("Requesting closed-loop control on both axes...")

    set_axis_state(
        AXIS0_NODE_ID,
        AXIS_STATE_CLOSED_LOOP_CONTROL,
    )

    set_axis_state(
        AXIS1_NODE_ID,
        AXIS_STATE_CLOSED_LOOP_CONTROL,
    )

    wait_for_axis_states(
        NODE_IDS,
        AXIS_STATE_CLOSED_LOOP_CONTROL,
    )

    print("Both axes confirmed in closed-loop control.")


def enter_idle():
    """
    Disable both motor axes so that they no longer actively hold position.
    """

    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_IDLE)
    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_IDLE)

    print("Both axes set to idle.")

def setup_can_control():
    print("Starting with both axes idle...")
    set_axis_state(AXIS0_NODE_ID, AXIS_STATE_IDLE)
    set_axis_state(AXIS1_NODE_ID, AXIS_STATE_IDLE)
    print("Motors are idle. Use 'start' to enable them.")

def stop_motors_hard():
    """
    Immediate shutdown used when exiting or when an error occurs.
    """

    print("Stopping motors...")

    # Send repeated zero-speed commands before disabling control.
    for _ in range(10):
        send_vel(AXIS0_NODE_ID, 0.0)
        time.sleep(0.05)

    enter_idle()


def input_thread_fn():
    """
    Read commands without blocking the CAN transmission loop.
    """

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
        "  stop          Ramp down, then set axes to idle\n"
        "  speed <value> Set target speed in turns/s\n"
        "  +             Increase target speed\n"
        "  -             Decrease target speed\n"
        "  quit          Stop motors and exit\n"
    )


def run_control_loop():
    """
    Fixed-rate motor-control loop.

    When stop is requested:
      1. Ramp current_velocity down to zero.
      2. Send zero velocity.
      3. Put both axes into idle.

    When movement is requested again:
      1. Return both axes to closed-loop control.
      2. Begin ramping toward the requested velocity.
    """

    target_velocity = 0.0
    current_velocity = 0.0

    running = False
    axes_idle = True
    idle_when_stopped = False

    next_tick = time.perf_counter()
    last_tick = next_tick

    while True:
        now = time.perf_counter()
        dt = now - last_tick
        last_tick = now

        # Process all pending commands.
        while True:
            try:
                cmd = command_queue.get_nowait()
            except queue.Empty:
                break

            if cmd in ("start", "s"):
                # Re-enable the axes if the previous stop placed them in idle.
                if axes_idle:
                    try:
                        enter_closed_loop()
                        axes_idle = False
                    except TimeoutError as error:
                        print(f"Could not restart motors: {error}")
                        running = False
                        target_velocity = 0.0
                        continue

                running = True
                idle_when_stopped = False
                target_velocity = CRUISE_VELOCITY

                print(
                    f"Ramping up to {target_velocity} turns/s..."
                )

            elif cmd in ("stop", "x"):
                running = False
                target_velocity = 0.0

                # Once the ramp reaches zero, transition into idle.
                idle_when_stopped = True

                if axes_idle:
                    print("Motors are already stopped and idle.")
                else:
                    print(
                        "Ramping down to zero, then entering idle..."
                    )

            elif cmd in (
                "+",
                "up",
                "faster",
                "increase",
            ):
                if running and not axes_idle:
                    target_velocity = min(
                        target_velocity + VELOCITY_STEP,
                        MAX_VELOCITY,
                    )

                    print(
                        f"Target velocity now "
                        f"{target_velocity} turns/s"
                    )
                else:
                    print("Not running — use 'start' first.")

            elif cmd in (
                "-",
                "down",
                "slower",
                "decrease",
            ):
                if running and not axes_idle:
                    target_velocity = max(
                        target_velocity - VELOCITY_STEP,
                        0.0,
                    )

                    print(
                        f"Target velocity now "
                        f"{target_velocity} turns/s"
                    )
                else:
                    print("Not running — use 'start' first.")

            elif cmd.startswith("speed"):
                try:
                    parts = cmd.split(maxsplit=1)

                    if len(parts) != 2:
                        raise ValueError

                    requested_velocity = float(parts[1])

                    if requested_velocity < 0:
                        print("Speed must be 0 or greater.")
                        continue

                    if requested_velocity > MAX_VELOCITY:
                        print(
                            f"Speed limited to MAX_VELOCITY "
                            f"({MAX_VELOCITY} turns/s)."
                        )

                        requested_velocity = MAX_VELOCITY

                    if requested_velocity == 0.0:
                        running = False
                        target_velocity = 0.0
                        idle_when_stopped = True

                        if axes_idle:
                            print(
                                "Motors are already stopped and idle."
                            )
                        else:
                            print(
                                "Ramping down to zero, then "
                                "entering idle..."
                            )

                        continue

                    # A nonzero speed command should wake the axes.
                    if axes_idle:
                        try:
                            enter_closed_loop()
                            axes_idle = False
                        except TimeoutError as error:
                            print(
                                f"Could not restart motors: {error}"
                            )
                            running = False
                            target_velocity = 0.0
                            continue

                    running = True
                    idle_when_stopped = False
                    target_velocity = requested_velocity

                    print(
                        f"Target velocity set to "
                        f"{target_velocity} turns/s"
                    )

                except (ValueError, IndexError):
                    print("Usage: speed <turns/s>")

            elif cmd in ("quit", "q", "exit"):
                raise KeyboardInterrupt

            elif cmd in ("help", "?"):
                print_help()

            else:
                print(f"Unknown command: {cmd!r}")
                print_help()

        # Only perform velocity control while the axes are enabled.
        if not axes_idle:
            max_step = RAMP_RATE * dt
            velocity_difference = (
                target_velocity - current_velocity
            )

            if abs(velocity_difference) <= max_step:
                current_velocity = target_velocity
            else:
                if velocity_difference > 0:
                    current_velocity += max_step
                else:
                    current_velocity -= max_step

            # Prevent tiny floating-point residual speeds.
            if (
                target_velocity == 0.0
                and abs(current_velocity)
                <= ZERO_VELOCITY_THRESHOLD
            ):
                current_velocity = 0.0

            send_vel(
                AXIS0_NODE_ID,
                current_velocity,
            )

            # The normal stop sequence has now reached zero speed.
            if (
                idle_when_stopped
                and current_velocity == 0.0
            ):
                # Send zero several times to make sure the final velocity
                # command is received before disabling the axes.
                for _ in range(3):
                    send_vel(AXIS0_NODE_ID, 0.0)
                    time.sleep(0.01)

                enter_idle()

                axes_idle = True
                idle_when_stopped = False

                print(
                    "Motors stopped. Closed-loop holding is disabled."
                )

        next_tick += LOOP_PERIOD
        sleep_time = next_tick - time.perf_counter()

        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            # Resynchronise rather than allowing timing drift to accumulate.
            next_tick = time.perf_counter()


try:
    setup_can_control()

    input_thread = threading.Thread(
        target=input_thread_fn,
        daemon=True,
    )
    input_thread.start()

    run_control_loop()

except KeyboardInterrupt:
    stop_motors_hard()

except TimeoutError as error:
    print(f"Sync setup failed: {error}")
    stop_motors_hard()

except can.CanError as error:
    print(f"CAN error: {error}")
    stop_motors_hard()

finally:
    bus.shutdown()
    print("CAN bus shutdown.")