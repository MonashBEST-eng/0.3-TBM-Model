# odrive_controller.py
# Ramped ODrive velocity control, running over the existing STM
# Ethernet<->CAN relay (tbm/can_tx published, stm32/can_rx received) —
# not a local PCAN adapter. See GTW_Control_Comms/odrive_can.py for the
# ODrive CAN Simple protocol layer and can_command_dictionary.py for the
# wire format the STM firmware expects.
#
# Same start/stop/ramp state machine as the original bench-test script
# (python-can + PCAN_USBBUS1), rebuilt so that:
#   - CAN I/O goes through gtw_mqtt_commands' publish functions (MQTT
#     relay), not python-can
#   - the ramp loop runs on its own background thread, so it can never
#     block the Tk GUI
#   - button presses (start/stop/set_speed/nudge) just queue an intent and
#     return immediately — safe to call directly from button callbacks
#   - incoming CAN frames are decoded by the main GUI's existing
#     stm32/can_rx handler and handed to process_can_frame(), which pushes
#     structured ("odrive_heartbeat", ...) / ("odrive_encoder", ...)
#     messages onto msg_queue for the main GUI to display — mirrors how
#     SbgReader/ButtonBox report back rather than touching Tk widgets
#     directly.
#
# Usage (mirrors ButtonBox / SbgReader):
#   odrive = OdriveController(msg_queue)
#   odrive.start_loop()                # background thread, call once
#   odrive.start() / odrive.stop() / odrive.set_speed(x) / odrive.nudge(d)
#   odrive.process_can_frame(frame)    # feed decoded stm32/can_rx frames

import threading
import time
from queue import Queue

import GTW_Control_Comms.gtw_mqtt_commands as command
import GTW_Control_Comms.odrive_can as odrive_can

LOOP_PERIOD = 0.05
CRUISE_VELOCITY = 5.0
VELOCITY_STEP = 2.0
MAX_VELOCITY = 35.0
RAMP_RATE = 1.0
ZERO_VELOCITY_THRESHOLD = 0.001
CLOSED_LOOP_TIMEOUT = 5.0
TELEMETRY_PERIOD = 1.0   # how often to request encoder estimates while running


class OdriveController:
    """
    Messages pushed to msg_queue:
        ("odrive_status",    "message string")
        ("odrive_heartbeat", (node_id, axis_error, axis_state))
        ("odrive_encoder",   (node_id, position_turns, velocity_turns_s))
    """

    def __init__(self, msg_queue: Queue):
        self.msg_queue = msg_queue

        self.target_velocity = 0.0
        self.current_velocity = 0.0
        self.running = False
        self.axes_idle = True
        self.idle_when_stopped = False

        self._pending_command = None
        self._cmd_lock = threading.Lock()

        self._heartbeats = {}   # node_id -> (axis_error, axis_state, timestamp)
        self._state_lock = threading.Lock()

        self._thread = None
        self._stop_thread = threading.Event()

    # --------------------------------------------------
    # PUBLIC API — safe to call from the Tk main thread
    # --------------------------------------------------
    def start_loop(self):
        """Start the background control thread. Call once, e.g. at GUI startup.
        Idempotent — safe to call again (e.g. every time the Control Panel
        is opened) without spawning a second thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_thread.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def shutdown(self):
        """Stop the background thread. Does NOT itself stop the motors —
        call stop() first and give it time to ramp down for a safe stop."""
        self._stop_thread.set()
        if self._thread:
            self._thread.join(timeout=2)

    def start(self):
        """Wake the axes and ramp to cruise velocity."""
        self._queue_command("start")

    def stop(self):
        """Ramp down to zero, then idle the axes."""
        self._queue_command("stop")

    def set_speed(self, velocity: float):
        """Ramp to an explicit target velocity (turns/s). 0 is treated as stop."""
        velocity = max(0.0, min(float(velocity), MAX_VELOCITY))
        self._queue_command(("speed", velocity))

    def nudge(self, delta: float):
        """Adjust target velocity by +/- delta turns/s while already running."""
        self._queue_command(("nudge", delta))

    def _queue_command(self, cmd):
        with self._cmd_lock:
            self._pending_command = cmd

    # --------------------------------------------------
    # INCOMING CAN FRAMES — call from the main GUI's stm32/can_rx handler.
    # frame: dict as returned by gtw_mqtt_commands.decode_can_rx_payload()
    #        {"id":, "ext":, "rtr":, "dlc":, "data": [int,...]}
    # --------------------------------------------------
    def process_can_frame(self, frame: dict) -> bool:
        """Returns True if this frame belonged to the ODrive and was
        handled, False otherwise (so the caller can fall back to its
        generic raw-frame log for anything else)."""
        can_id = frame.get("id")
        if can_id is None or not odrive_can.is_odrive_frame(can_id):
            return False

        node_id, cmd_id = odrive_can.identify_frame(can_id)
        data = frame.get("data", [])

        if cmd_id == odrive_can.CMD_HEARTBEAT:
            decoded = odrive_can.decode_heartbeat(data)
            if decoded is None:
                return True
            axis_error, axis_state = decoded
            with self._state_lock:
                self._heartbeats[node_id] = (axis_error, axis_state, time.time())
            self.msg_queue.put(("odrive_heartbeat", (node_id, axis_error, axis_state)))
            return True

        if cmd_id == odrive_can.CMD_GET_ENCODER_ESTIMATES:
            decoded = odrive_can.decode_encoder_estimates(data)
            if decoded is None:
                return True
            position, velocity = decoded
            self.msg_queue.put(("odrive_encoder", (node_id, position, velocity)))
            return True

        return True   # recognised as ODrive, just not a frame we interpret

    # --------------------------------------------------
    # LOGGING
    # --------------------------------------------------
    def _log(self, msg):
        self.msg_queue.put(("odrive_status", f"[ODrive] {msg}"))

    # --------------------------------------------------
    # BACKGROUND THREAD — everything below runs off the Tk thread
    # --------------------------------------------------
    def _wake_axes(self) -> bool:
        if not self.axes_idle:
            return True

        self._log("Requesting closed-loop control on both axes...")
        for nid in odrive_can.NODE_IDS:
            command.odrive_set_axis_state(nid, odrive_can.AXIS_STATE_CLOSED_LOOP_CONTROL)

        deadline = time.perf_counter() + CLOSED_LOOP_TIMEOUT
        pending = set(odrive_can.NODE_IDS)
        while pending and time.perf_counter() < deadline:
            time.sleep(0.05)
            with self._state_lock:
                for nid in list(pending):
                    hb = self._heartbeats.get(nid)
                    if hb and hb[1] == odrive_can.AXIS_STATE_CLOSED_LOOP_CONTROL:
                        pending.discard(nid)

        if pending:
            self._log(
                f"Could not restart motors: axes {sorted(pending)} never "
                f"confirmed closed-loop control"
            )
            self.running = False
            self.target_velocity = 0.0
            return False

        self.axes_idle = False
        self._log("Both axes confirmed in closed-loop control.")
        return True

    def _enter_idle(self):
        for nid in odrive_can.NODE_IDS:
            command.odrive_set_axis_state(nid, odrive_can.AXIS_STATE_IDLE)
        self.axes_idle = True
        self._log("Both axes set to idle.")

    def _handle_pending(self):
        with self._cmd_lock:
            cmd = self._pending_command
            self._pending_command = None
        if cmd is None:
            return

        if cmd == "start":
            if self._wake_axes():
                self.running = True
                self.idle_when_stopped = False
                self.target_velocity = CRUISE_VELOCITY
                self._log(f"Ramping up to {self.target_velocity} turns/s...")

        elif cmd == "stop":
            self.running = False
            self.target_velocity = 0.0
            self.idle_when_stopped = True
            if self.axes_idle:
                self._log("Motors are already stopped and idle.")
            else:
                self._log("Ramping down to zero, then entering idle...")

        elif isinstance(cmd, tuple) and cmd[0] == "speed":
            velocity = cmd[1]
            if velocity == 0.0:
                self.running = False
                self.target_velocity = 0.0
                self.idle_when_stopped = True
                self._log("Ramping down to zero, then entering idle...")
            elif self._wake_axes():
                self.running = True
                self.idle_when_stopped = False
                self.target_velocity = velocity
                self._log(f"Target velocity set to {velocity} turns/s")

        elif isinstance(cmd, tuple) and cmd[0] == "nudge":
            if self.running and not self.axes_idle:
                self.target_velocity = max(
                    0.0, min(self.target_velocity + cmd[1], MAX_VELOCITY)
                )
                self._log(f"Target velocity now {self.target_velocity} turns/s")
            else:
                self._log("Not running — use Start first.")

    def _update_velocity(self, dt: float):
        if self.axes_idle:
            return

        max_step = RAMP_RATE * dt
        diff = self.target_velocity - self.current_velocity
        if abs(diff) <= max_step:
            self.current_velocity = self.target_velocity
        else:
            self.current_velocity += max_step if diff > 0 else -max_step

        if self.target_velocity == 0.0 and abs(self.current_velocity) <= ZERO_VELOCITY_THRESHOLD:
            self.current_velocity = 0.0

        command.odrive_send_velocity(odrive_can.AXIS0_NODE_ID, self.current_velocity)

        if self.idle_when_stopped and self.current_velocity == 0.0:
            for _ in range(3):
                command.odrive_send_velocity(odrive_can.AXIS0_NODE_ID, 0.0)
                time.sleep(0.01)
            self._enter_idle()
            self.idle_when_stopped = False
            self._log("Motors stopped. Closed-loop holding is disabled.")

    def _publish_telemetry(self):
        for node_id in odrive_can.NODE_IDS:
            command.odrive_request_encoder(node_id)

    def _run(self):
        next_tick = time.perf_counter()
        last_tick = next_tick
        last_telemetry = time.perf_counter()

        while not self._stop_thread.is_set():
            now = time.perf_counter()
            dt = now - last_tick
            last_tick = now

            self._handle_pending()
            self._update_velocity(dt)

            if not self.axes_idle and (now - last_telemetry) >= TELEMETRY_PERIOD:
                last_telemetry = now
                self._publish_telemetry()

            next_tick += LOOP_PERIOD
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_tick = time.perf_counter()   # resync rather than drift
