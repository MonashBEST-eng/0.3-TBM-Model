import queue
import time

from can_interface import ODriveCAN
from commands import command_queue, print_help
from telemetry import TelemetryPublisher
from config import (
    AXIS0_NODE_ID,
    AXIS1_NODE_ID,
    CRUISE_VELOCITY,
    LOOP_PERIOD,
    MAX_VELOCITY,
    RAMP_RATE,
    TELEMETRY_PERIOD,
    ENCODER_RESPONSE_TIMEOUT,
    VELOCITY_STEP,
    ZERO_VELOCITY_THRESHOLD,
)


class MotorController:
    def __init__(self, odrive_can: ODriveCAN):
        self.odrive = odrive_can
        self.target_velocity = 0.0
        self.current_velocity = 0.0
        self.running = False
        self.axes_idle = True
        self.idle_when_stopped = False
        self.last_telemetry_publish = time.perf_counter()
        self.telemetry = TelemetryPublisher()

    def _wake_axes(self):
        if not self.axes_idle:
            return True

        try:
            self.odrive.enter_closed_loop()
            self.odrive.send_velocity(AXIS0_NODE_ID, 0.0)
            self.axes_idle = False
            return True
        except TimeoutError as error:
            print(f"Could not restart motors: {error}")
            self.running = False
            self.target_velocity = 0.0
            return False

    def _request_stop(self):
        self.running = False
        self.target_velocity = 0.0
        self.idle_when_stopped = True

        if self.axes_idle:
            print("Motors are already stopped and idle.")
        else:
            print("Ramping down to zero, then entering idle...")

    def _handle_command(self, cmd):
        if cmd in ("start", "s"):
            if not self._wake_axes():
                return

            self.running = True
            self.idle_when_stopped = False
            self.target_velocity = CRUISE_VELOCITY
            print(f"Ramping up to {self.target_velocity} turns/s...")

        elif cmd in ("stop", "x"):
            self._request_stop()

        elif cmd in ("+", "up", "faster", "increase"):
            if self.running and not self.axes_idle:
                self.target_velocity = min(
                    self.target_velocity + VELOCITY_STEP,
                    MAX_VELOCITY,
                )
                print(f"Target velocity now {self.target_velocity} turns/s")
            else:
                print("Not running — use 'start' first.")

        elif cmd in ("-", "down", "slower", "decrease"):
            if self.running and not self.axes_idle:
                self.target_velocity = max(
                    self.target_velocity - VELOCITY_STEP,
                    0.0,
                )
                print(f"Target velocity now {self.target_velocity} turns/s")
            else:
                print("Not running — use 'start' first.")

        elif cmd.startswith("speed"):
            self._handle_speed_command(cmd)

        elif cmd in ("quit", "q", "exit"):
            raise KeyboardInterrupt

        elif cmd in ("help", "?"):
            print_help()

        else:
            print(f"Unknown command: {cmd!r}")
            print_help()

    def _handle_speed_command(self, cmd):
        try:
            parts = cmd.split(maxsplit=1)
            if len(parts) != 2:
                raise ValueError

            requested_velocity = float(parts[1])

            if requested_velocity < 0:
                print("Speed must be 0 or greater.")
                return

            if requested_velocity > MAX_VELOCITY:
                print(
                    f"Speed limited to MAX_VELOCITY "
                    f"({MAX_VELOCITY} turns/s)."
                )
                requested_velocity = MAX_VELOCITY

            if requested_velocity == 0.0:
                self._request_stop()
                return

            if not self._wake_axes():
                return

            self.running = True
            self.idle_when_stopped = False
            self.target_velocity = requested_velocity
            print(f"Target velocity set to {self.target_velocity} turns/s")

        except (ValueError, IndexError):
            print("Usage: speed <turns/s>")

    def _drain_commands(self):
        while True:
            try:
                cmd = command_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_command(cmd)

    def _update_velocity(self, dt):
        if self.axes_idle:
            return

        max_step = RAMP_RATE * dt
        velocity_difference = self.target_velocity - self.current_velocity

        if abs(velocity_difference) <= max_step:
            self.current_velocity = self.target_velocity
        elif velocity_difference > 0:
            self.current_velocity += max_step
        else:
            self.current_velocity -= max_step

        if (
            self.target_velocity == 0.0
            and abs(self.current_velocity) <= ZERO_VELOCITY_THRESHOLD
        ):
            self.current_velocity = 0.0

        self.odrive.send_velocity(AXIS0_NODE_ID, self.current_velocity)

        if self.idle_when_stopped and self.current_velocity == 0.0:
            for _ in range(3):
                self.odrive.send_velocity(AXIS0_NODE_ID, 0.0)
                time.sleep(0.01)

            self.odrive.enter_idle()
            self.axes_idle = True
            self.idle_when_stopped = False
            print("Motors stopped. Closed-loop holding is disabled.")


    def _publish_telemetry(self):
        """Read encoder estimates and send them to monitor.py via UDP."""
        now = time.perf_counter()
        if now - self.last_telemetry_publish < TELEMETRY_PERIOD:
            return

        self.last_telemetry_publish = now

        axis0_feedback = None
        axis1_feedback = None

        if not self.axes_idle:
            axis0_feedback = self.odrive.request_encoder_estimates(
                AXIS0_NODE_ID,
                timeout=ENCODER_RESPONSE_TIMEOUT,
            )
            axis1_feedback = self.odrive.request_encoder_estimates(
                AXIS1_NODE_ID,
                timeout=ENCODER_RESPONSE_TIMEOUT,
            )

        payload = {
            "timestamp": time.time(),
            "running": self.running,
            "axes_idle": self.axes_idle,
            "target_rps": self.target_velocity,
            "command_rps": self.current_velocity,
            "axis0": None,
            "axis1": None,
        }

        if axis0_feedback is not None:
            position0, velocity0 = axis0_feedback
            payload["axis0"] = {
                "position_turns": position0,
                "velocity_rps": velocity0,
            }

        if axis1_feedback is not None:
            position1, velocity1 = axis1_feedback
            payload["axis1"] = {
                "position_turns": position1,
                "velocity_rps": velocity1,
            }

        self.telemetry.publish(payload)

    def run(self):
        next_tick = time.perf_counter()
        last_tick = next_tick

        while True:
            now = time.perf_counter()
            dt = now - last_tick
            last_tick = now

            self._drain_commands()
            self._update_velocity(dt)
            self._publish_telemetry()

            next_tick += LOOP_PERIOD
            sleep_time = next_tick - time.perf_counter()

            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_tick = time.perf_counter()
