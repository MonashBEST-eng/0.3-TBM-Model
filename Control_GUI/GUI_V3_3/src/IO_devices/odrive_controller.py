# odrive_controller.py
# Ramped ODrive velocity control, running over the existing STM
# Ethernet<->CAN relay (STM32H7 + MCP2515; tbm/can_tx published,
# stm32/can_rx received) — not a local PCAN adapter. See
# GTW_Control_Comms/odrive_can.py for the ODrive CAN Simple protocol layer
# and can_command_dictionary.py for the wire format the STM expects.
#
# Same start/stop/ramp state machine as the original bench-test script
# (python-can + PCAN_USBBUS1), rebuilt so that:
#   - CAN I/O goes through gtw_mqtt_commands' publish functions (MQTT
#     relay), not python-can
#   - the ramp loop runs on its own background thread, so it can never
#     block the Tk GUI
#   - button presses (start/stop/set_speed/nudge) just queue an intent and
#     return immediately — safe to call directly from button callbacks
#   - telemetry is PASSIVE: the ODrive broadcasts heartbeat and encoder
#     frames cyclically (configured once on the board, see odrive_can.py),
#     so this controller never polls with RTR frames. It only listens via
#     process_can_frame(), and watches for heartbeat silence to catch a
#     dropped link.
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
#   odrive.start(v) / odrive.stop() / odrive.set_speed(x) / odrive.nudge(d)
#     start(v) ramps to v turns/s; start() alone falls back to CRUISE_VELOCITY
#   odrive.process_can_frame(frame)    # feed decoded stm32/can_rx frames

import threading
import time
import traceback
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
# ODrive broadcasts heartbeats cyclically (100 ms by default per the setup
# in odrive_can.py). If we stop hearing them for this long, the board,
# the CAN wiring, the MCP2515, or the H7 relay has dropped out - which
# matters because with passive telemetry, silence is indistinguishable
# from "everything is fine" unless we check for it explicitly.
HEARTBEAT_TIMEOUT = 1.5

# Velocity frames are only transmitted when the setpoint changes by more
# than this, or when the keepalive period elapses. Without this the loop
# re-sends an identical value at 20 Hz forever once the ramp settles,
# which floods the relay for no benefit.
VELOCITY_SEND_EPSILON = 0.005      # turns/s
VELOCITY_KEEPALIVE_PERIOD = 0.25    # seconds
# MUST stay well below the ODrive's axis.config.watchdog_timeout (currently
# set to 1.0s over USB). This was previously 1.0 - EXACTLY EQUAL to the
# watchdog timeout, with zero margin. Any jitter at all (MQTT round-trip,
# H7 processing, GUI thread scheduling) could push the real gap between
# keepalives past 1.0s, and the ODrive's own watchdog would re-trip
# WATCHDOG_TIMER_EXPIRED (0x800) moments after successfully entering
# closed loop - which is exactly what was observed: clear-errors succeeds,
# closed-loop request succeeds, and the axis is back at the same latched
# error within about a second, every time. 0.25s gives 4x margin.

# Direction multiplier applied to AXIS1's velocity relative to AXIS0's.
# Set to -1.0 if the two motors are mechanically geared/meshed so that
# running them at the same COMMANDED sign would drive them into each
# other or fight - per the original bench script's config.py comment
# ("MIRROR_RATIO = -1.0  # set by direction check: gears mesh opposite
# sides"). CONFIRM THIS AGAINST YOUR ACTUAL MECHANICAL SETUP before
# relying on it - defaulting to 1.0 (same direction) since that's the
# safer assumption for an unconfirmed coupling, but if your two motors
# are geared opposite, leaving this at 1.0 will drive them against each
# other the moment axis1 starts actually receiving commands.
AXIS1_VELOCITY_SCALE = 1.0

# ==================================================
# BENCH_MODE — dry-run validation with NO MOTORS ATTACHED
# ==================================================
# Set True to validate the GUI -> MQTT -> H7 -> MCP2515 -> CAN -> ODrive
# command path without motors. It:
#   - skips waiting for closed-loop heartbeat confirmation, which cannot
#     arrive when heartbeats are disabled and would be refused anyway
#     while the encoder reports ILLEGAL_HALL_STATE (normal with no motors)
#   - suppresses the heartbeat-silence warning
# The ramp loop still runs and still publishes REAL velocity frames, so
# verify over USB that odrv0.axis0.controller.input_vel tracks the ramp.
#
# *** SET BACK TO False BEFORE CONNECTING MOTORS. ***
# With motors attached this would let the GUI believe axes are live
# without any confirmation that they actually are.
BENCH_MODE = False


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
        self._link_lost = False   # latch so the warning logs once, not every tick
        self._estop_latched = False   # blocks all motion until cleared

        # Velocity frames are only sent when the value meaningfully changes,
        # plus a slow keepalive — see _update_velocity(). Re-sending an
        # identical setpoint 20x/second is what flooded the H7 relay.
        self._last_sent_velocity = None
        self._last_send_time = 0.0

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

    def start(self, velocity=None):
        """Wake the axes and ramp to `velocity` turns/s.

        If `velocity` is None, falls back to CRUISE_VELOCITY. The GUI passes
        whatever is in the speed entry box, so START and SET agree rather
        than START silently overriding the displayed value with a constant.
        A velocity of 0 is treated as a stop request, same as set_speed().
        """
        if velocity is None:
            velocity = CRUISE_VELOCITY

        requested = float(velocity)
        velocity = max(0.0, min(requested, MAX_VELOCITY))
        if velocity != requested:
            self._log(
                f"Start speed {requested:.3f} clamped to {velocity:.3f} "
                f"turns/s (limit {MAX_VELOCITY})."
            )
        self._queue_command(("start", velocity))

    def stop(self):
        """Ramp down to zero, then idle the axes."""
        self._queue_command("stop")

    def clear_errors(self):
        """Clear latched ODrive errors (e.g. a tripped watchdog) WITHOUT
        requesting closed loop or starting motion. Safe to call any time,
        including while idle or E-STOP latched (clearing an axis error is
        not the same as clearing the GUI's own E-STOP latch - both must be
        cleared independently: this for the ODrive, CLEAR EMERGENCY for
        the panel). Useful for confirming a fault is actually gone before
        deliberately pressing START."""
        for nid in odrive_can.NODE_IDS:
            command.odrive_clear_errors(nid)
        self._log("Clear-errors sent to both axes.")

    def set_speed(self, velocity: float, quiet: bool = False):
        """Ramp to an explicit target velocity (turns/s). 0 is treated as stop.

        `quiet=True` suppresses the log line - used by the slider, which
        fires continuously while dragging and would otherwise flood the
        control log. (The command queue itself is self-throttling: only the
        most recent pending command survives, so rapid slider updates
        collapse to whatever value the drag ended on.)
        """
        requested = float(velocity)
        velocity = max(0.0, min(requested, MAX_VELOCITY))
        if velocity != requested:
            self._log(
                f"Speed {requested:.3f} clamped to {velocity:.3f} turns/s "
                f"(limit {MAX_VELOCITY})."
            )
        elif not quiet:
            self._log(f"Speed command received: {velocity:.3f} turns/s")
        self._queue_command(("speed", velocity))

    def nudge(self, delta: float):
        """Adjust target velocity by +/- delta turns/s while already running."""
        self._queue_command(("nudge", delta))

    def emergency_halt(self):
        """Immediately zero all internal state AND LATCH the estop so no
        further motion can be commanded until clear_emergency() is called.
        Called by gtw_mqtt_commands.odrive_emergency_stop(), which
        separately publishes the actual zero-velocity and idle CAN frames.

        Unlike stop(), this does NOT queue an intent for the background
        thread to process later - it mutates state directly, so it takes
        effect even if that thread is dead or blocked.

        THE LATCH IS THE POINT: without it, pressing START straight after
        an E-STOP would happily spin the motor back up."""
        self._estop_latched = True
        with self._cmd_lock:
            self._pending_command = None
        self.running = False
        self.target_velocity = 0.0
        self.current_velocity = 0.0
        self.idle_when_stopped = False
        self.axes_idle = True

    def clear_emergency(self):
        """Release the estop latch. Motion stays stopped - the operator
        must still press START deliberately - but START will now work."""
        self._estop_latched = False
        self._log("Emergency cleared. Motion re-enabled (press START).")

    @property
    def estop_latched(self) -> bool:
        return self._estop_latched

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

        # Clear any latched fault BEFORE requesting closed loop. This is
        # required, not optional: a tripped safety watchdog leaves
        # WATCHDOG_TIMER_EXPIRED (0x800) latched on the axis, and the
        # ODrive REFUSES AXIS_STATE_CLOSED_LOOP_CONTROL while any error is
        # latched - sending the closed-loop command alone does nothing.
        # This was observed directly: after an H7 reset tripped the
        # watchdog, repeated closed-loop requests left the axis sitting at
        # state=1/IDLE with error=0x800 unchanged. Clearing first means a
        # normal START recovers from a watchdog trip with no USB step.
        self._log("Clearing any latched ODrive errors before startup...")
        for nid in odrive_can.NODE_IDS:
            command.odrive_clear_errors(nid)

        self._log("Requesting closed-loop control on both axes...")
        for nid in odrive_can.NODE_IDS:
            command.odrive_set_axis_state(nid, odrive_can.AXIS_STATE_CLOSED_LOOP_CONTROL)

        if BENCH_MODE:
            # No heartbeat confirmation available (and, with no motors
            # attached, the ODrive would refuse closed loop anyway because
            # the encoder reports ILLEGAL_HALL_STATE). Proceed as if the
            # axes woke, so the ramp loop still runs and still publishes
            # real velocity frames. Verify over USB in odrivetool that
            # odrv0.axis0.controller.input_vel tracks the ramp.
            self.axes_idle = False
            self._log(
                "BENCH_MODE: skipping closed-loop confirmation. "
                "Velocity frames will be sent but motors will NOT move."
            )
            return True

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

        # E-STOP latch: refuse every motion command until explicitly
        # cleared. "stop" is always allowed through - stopping is never
        # something to block.
        if self._estop_latched and cmd != "stop":
            self._log("REFUSED: emergency stop is latched. Clear emergency first.")
            return

        if isinstance(cmd, tuple) and cmd[0] == "start":
            velocity = cmd[1]

            # Treat a start at 0 as a stop rather than waking the axes only
            # to sit there commanding zero.
            if velocity == 0.0:
                self.running = False
                self.target_velocity = 0.0
                self.idle_when_stopped = True
                self._log("Start requested at 0 turns/s - treating as stop.")
                return

            if self._wake_axes():
                self.running = True
                self.idle_when_stopped = False
                self.target_velocity = velocity
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

    def _link_is_healthy(self) -> tuple:
        """Single source of truth for 'is it safe to command motion right
        now', used by BOTH _update_velocity() (before it will send anything)
        and _check_link_alive() (the periodic checker). Previously only the
        checker looked at this, running AFTER _update_velocity() in the
        loop - meaning a fault detected this tick couldn't stop a send that
        already happened THIS tick, only the next one. Folding the same
        check into the send path itself closes that gap entirely: nothing
        can transmit in the same tick a fault becomes visible, regardless
        of which order the two methods run in.

        Returns (healthy: bool, reason: str | None).
        """
        with self._state_lock:
            snapshot = dict(self._heartbeats)

        for node_id, (axis_error, axis_state, _ts) in snapshot.items():
            if axis_error:
                return False, f"axis {node_id} reports error 0x{axis_error:08X}"
            if axis_state != odrive_can.AXIS_STATE_CLOSED_LOOP_CONTROL:
                return False, f"axis {node_id} left closed-loop control (state {axis_state})"

        if BENCH_MODE:
            return True, None   # heartbeats may be off; silence is expected

        newest = max((hb[2] for hb in snapshot.values()), default=None)
        now = time.time()
        if newest is None or (now - newest) > HEARTBEAT_TIMEOUT:
            return False, "no ODrive heartbeat received within timeout"

        return True, None

    def _update_velocity(self, dt: float):
        if self._estop_latched:
            return   # latched E-STOP: never command motion, at any level
        if self.axes_idle:
            return

        # Redundant, independent check - see _link_is_healthy(). This is
        # deliberately checked here too, not just in _check_link_alive(),
        # so a fault can never be "one tick late": nothing below this line
        # can execute in the same tick the link is found unhealthy.
        healthy, reason = self._link_is_healthy()
        if not healthy:
            self._log(f"ABORTING (pre-send check): {reason} - commanding stop.")
            self._fault_stop()
            return

        max_step = RAMP_RATE * dt
        diff = self.target_velocity - self.current_velocity
        if abs(diff) <= max_step:
            self.current_velocity = self.target_velocity
        else:
            self.current_velocity += max_step if diff > 0 else -max_step

        if self.target_velocity == 0.0 and abs(self.current_velocity) <= ZERO_VELOCITY_THRESHOLD:
            self.current_velocity = 0.0

        # Only transmit when the setpoint actually changed, plus a slow
        # keepalive. While ramping this still sends every tick (the value
        # is changing), but once the target is reached it drops from 20
        # frames/s to 1 - which is what stops the H7 relay being flooded
        # with an identical setpoint forever.
        now = time.perf_counter()
        changed = (
            self._last_sent_velocity is None
            or abs(self.current_velocity - self._last_sent_velocity) > VELOCITY_SEND_EPSILON
        )
        due = (now - self._last_send_time) >= VELOCITY_KEEPALIVE_PERIOD

        if changed or due:
            # AXIS1 MUST be sent here too, on the exact same schedule as
            # AXIS0. Previously only AXIS0 ever received an ongoing
            # velocity command - AXIS1 got its one-time closed-loop
            # request in _wake_axes() and NOTHING after that. Since the
            # ODrive watchdog requires periodic CAN traffic addressed to
            # THAT axis specifically, axis1's watchdog was guaranteed to
            # expire ~1s after entering closed loop on every single run,
            # regardless of axis0's timing - this is what "one motor ran,
            # the other didn't" was: not a fault on axis1, just an axis
            # that was never being fed.
            command.odrive_send_velocity(odrive_can.AXIS0_NODE_ID, self.current_velocity)
            command.odrive_send_velocity(odrive_can.AXIS1_NODE_ID,
                                         self.current_velocity * AXIS1_VELOCITY_SCALE)
            self._last_sent_velocity = self.current_velocity
            self._last_send_time = now
        if self.idle_when_stopped and self.current_velocity == 0.0:
            for _ in range(3):
                command.odrive_send_velocity(odrive_can.AXIS0_NODE_ID, 0.0)
                command.odrive_send_velocity(odrive_can.AXIS1_NODE_ID, 0.0)
                time.sleep(0.01)
            self._enter_idle()
            self.idle_when_stopped = False
            self._log("Motors stopped. Closed-loop holding is disabled.")

    def _check_link_alive(self):
        """Periodic backstop check, run once per loop tick. The SAME check
        also runs inline inside _update_velocity() immediately before any
        send - see _link_is_healthy() for why both call sites exist. This
        one exists to catch a fault even during ticks where nothing would
        otherwise be sent (e.g. between keepalives), so a dead link is
        still noticed and stopped promptly rather than only at the next
        scheduled transmission."""
        if self.axes_idle:
            return

        healthy, reason = self._link_is_healthy()
        if not healthy:
            self._link_lost = True
            self._log(f"ABORTING: {reason} - commanding stop.")
            self._fault_stop()
            return

        if self._link_lost:
            self._link_lost = False
            self._log("ODrive link recovered.")

    def _fault_stop(self):
        """Stop commanding motion immediately after a detected fault.
        Sends zero velocity and idle directly rather than ramping down -
        an axis that has already faulted should not be ramped, and the
        ramp state is no longer trustworthy."""
        self.running = False
        self.target_velocity = 0.0
        self.current_velocity = 0.0
        self.idle_when_stopped = False

        for nid in odrive_can.NODE_IDS:
            command.odrive_send_velocity(nid, 0.0)
        self._enter_idle()

        # Force the next START to redo the closed-loop handshake rather
        # than assuming the axes are still live.
        self.axes_idle = True
        self._last_sent_velocity = None

    def _run(self):
        next_tick = time.perf_counter()
        last_tick = next_tick

        while not self._stop_thread.is_set():
            # A crash inside any of these used to kill this daemon thread
            # silently: the ramp would freeze mid-value and every button
            # would become a no-op, with no traceback anywhere. Catch and
            # REPORT instead, so a failure is visible in the control log
            # rather than looking like a stuck motor.
            try:
                now = time.perf_counter()
                dt = now - last_tick
                last_tick = now

                self._handle_pending()
                self._update_velocity(dt)
                self._check_link_alive()

            except Exception:
                detail = traceback.format_exc().strip().replace("\n", " | ")
                self._log(f"CONTROL LOOP ERROR: {detail}")

                # Fail safe: stop commanding motion, drop back to idle
                # state, and keep the loop alive so STOP still works.
                self.running = False
                self.target_velocity = 0.0
                self.current_velocity = 0.0
                self.idle_when_stopped = False
                self.axes_idle = True

                # Don't spin at full rate re-throwing the same error.
                time.sleep(0.5)
                next_tick = time.perf_counter()
                last_tick = next_tick
                continue

            next_tick += LOOP_PERIOD
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_tick = time.perf_counter()   # resync rather than drift