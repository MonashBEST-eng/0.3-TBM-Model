# cutterhead_pcan_bridge.py
#
# Wraps the provided PCAN-based ODrive control system (config.py,
# can_interface.py, commands.py, controller.py, telemetry.py - all
# UNMODIFIED, copied as-is into IO_devices/cutterhead_pcan/) for use
# directly from inside this GUI's process, replacing the H7/MQTT relay
# path for the front cutterhead specifically. Every other subsystem
# (E-STOP, LEDs, conveyor) keeps using the H7/MQTT path untouched.
#
# WHY THIS SHAPE:
# main.py (the provided entry point) is a single-process CLI: it opens
# PCAN_USBBUS1, starts a stdin-reading thread that pushes command strings
# ("start", "stop", "speed 5.0", "+", "-") into a shared queue.Queue, and
# runs MotorController.run() forever, which drains that queue every tick.
#
# The GUI doesn't need a stdin thread - GUI buttons ARE the new input
# source. So this bridge does exactly what main.py does, MINUS the stdin
# thread, PLUS pushing the exact same command strings from button
# callbacks instead. controller.py and commands.py needed ZERO changes:
# they already decouple "how a command arrives" from "what it means" via
# that shared queue.
#
# CRITICAL CONSTRAINT (from the provided README): a PCAN adapter only
# allows ONE process to hold the bus open at a time ("exclusive-access
# error"). Once this GUI is running and has called start_loop(), do NOT
# also run `python main.py` separately - only one of them can hold
# PCAN_USBBUS1 at once. monitor.py's UDP telemetry listener is unaffected
# either way (it never touches the bus directly), so running
# `python monitor.py` in a separate terminal alongside the GUI is fine
# and still works exactly as documented.

import os
import sys
import threading

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_CUTTERHEAD_DIR = os.path.join(_PACKAGE_DIR, "cutterhead_pcan")
if _CUTTERHEAD_DIR not in sys.path:
    # The provided files use flat imports (`from config import ...`,
    # `from can_interface import ODriveCAN`), not package-relative ones.
    # Adding their folder to sys.path lets them import each other exactly
    # as written, with no modification to any of the five files.
    sys.path.insert(0, _CUTTERHEAD_DIR)

from can_interface import ODriveCAN          # noqa: E402
from controller import MotorController        # noqa: E402
from commands import command_queue            # noqa: E402
import config as cutterhead_config            # noqa: E402


class CutterheadPCAN:
    """Owns the one PCAN connection for the cutterhead ODrive and the
    MotorController's background run loop. Public methods push command
    strings into the same queue commands.input_thread_fn() would have
    used - this class IS the input source now, just driven by GUI button
    callbacks instead of stdin."""

    def __init__(self):
        self.odrive: ODriveCAN | None = None
        self.controller: MotorController | None = None
        self._thread: threading.Thread | None = None
        self._connect_error: str | None = None

    def start_loop(self):
        """Opens PCAN_USBBUS1, sets both axes idle, and starts
        MotorController.run() on a background thread. Call once, e.g. when
        the Control Panel is first built. Idempotent - safe to call again
        (panel reopened) without opening a second connection or thread."""
        if self._thread and self._thread.is_alive():
            return True
        if self._connect_error:
            # Don't keep retrying a PCAN open that already failed this
            # session (e.g. exclusive-access error from main.py also
            # running) - that would just produce the same error repeatedly.
            return False

        try:
            self.odrive = ODriveCAN()
            self.odrive.setup_idle()
        except Exception as error:
            self._connect_error = str(error)
            print(f"[Cutterhead PCAN] Failed to open {cutterhead_config.BUS_CHANNEL}: {error}")
            return False

        self.controller = MotorController(self.odrive)
        self._thread = threading.Thread(target=self._run_safely, daemon=True)
        self._thread.start()
        return True

    def _run_safely(self):
        """MotorController.run() loops forever and has no built-in
        exception handling of its own (main.py's try/except wraps the
        whole process instead). Since this now runs as a background
        thread inside a long-lived GUI rather than as the whole process,
        an uncaught exception here must not silently kill the thread and
        leave the GUI looking fine while the motors are unreachable -
        report it and attempt a hard stop instead."""
        try:
            self.controller.run()
        except Exception as error:
            print(f"[Cutterhead PCAN] Control loop crashed: {error}")
            try:
                self.odrive.hard_stop()
            except Exception as stop_error:
                print(f"[Cutterhead PCAN] hard_stop also failed: {stop_error}")

    @property
    def connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def connect_error(self) -> str | None:
        return self._connect_error

    # ---- Command API - mirrors exactly what commands.py's stdin reader
    # would have sent, so controller.py's _handle_command() needs no
    # changes at all. ----

    def start(self):
        command_queue.put("start")

    def stop(self):
        command_queue.put("stop")

    def set_speed(self, turns_per_sec: float):
        command_queue.put(f"speed {turns_per_sec}")

    def nudge(self, delta: float):
        command_queue.put("+" if delta > 0 else "-")

    # ---- Live status for the GUI display. These read MotorController's
    # own public attributes directly (in-process, no IPC needed) - see
    # controller.py's __init__ for target_velocity/current_velocity/
    # running/axes_idle. Axis-level position/velocity (from
    # request_encoder_estimates) are intentionally NOT duplicated here:
    # they're only ever computed inside _publish_telemetry() right before
    # being sent over UDP to monitor.py, and re-requesting them
    # independently here would double the CAN traffic for the same data.
    # Run `python monitor.py` in a separate terminal for that detail, per
    # the provided README - it still works unmodified alongside the GUI. ----

    def get_status(self):
        if self.controller is None:
            return {
                "connected": False,
                "error": self._connect_error,
                "running": False,
                "axes_idle": True,
                "target_velocity": 0.0,
                "current_velocity": 0.0,
            }
        return {
            "connected": self.connected,
            "error": None,
            "running": self.controller.running,
            "axes_idle": self.controller.axes_idle,
            "target_velocity": self.controller.target_velocity,
            "current_velocity": self.controller.current_velocity,
        }


# Shared instance - same pattern as get_odrive_controller() /
# get_button_box() elsewhere in this project: created once, reused by
# whichever GUI code needs it.
_cutterhead_pcan: CutterheadPCAN | None = None


def get_cutterhead_pcan() -> CutterheadPCAN:
    global _cutterhead_pcan
    if _cutterhead_pcan is None:
        _cutterhead_pcan = CutterheadPCAN()
    return _cutterhead_pcan
