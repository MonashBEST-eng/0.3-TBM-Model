"""Unit tests for IO_devices/cutterhead_pcan_bridge.py - E-STOP behaviour.

Related test-suite cases in GUI_test_suite.xlsx:
    REQ-006 E-STOP            TC-038 to TC-045
    REQ-008 PCAN unavailable  TC-054
Each test lists its cases in a "Related test-suite cases:" line. These
automated tests check the CAN frames sent; the test-suite cases check the
cutterhead's physical response, which needs the real hardware.

No PCAN hardware needed. FakeODrive is the real ODriveCAN with only its
lowest-level send_can() replaced, so every real helper (send_velocity,
set_axis_state, enter_idle, hard_stop) runs unchanged and each CAN frame
it would have put on the bus is recorded instead.
"""
import struct

import pytest

import IO_devices.cutterhead_pcan_bridge as cutter_pcan

ODriveCAN = cutter_pcan.ODriveCAN
MotorController = cutter_pcan.MotorController
cfg = cutter_pcan.cutterhead_config
AXES = cfg.NODE_IDS


class FakeODrive(ODriveCAN):
    """Real ODriveCAN logic, no bus. Records (node_id, cmd_id, data)."""

    def __init__(self, fail_velocity=False):
        # Deliberately skips ODriveCAN.__init__, which opens PCAN_USBBUS1.
        self.frames = []
        self.fail_velocity = fail_velocity

    def send_can(self, node_id, cmd_id, data=b""):
        if self.fail_velocity and cmd_id == cfg.CMD_SET_INPUT_VEL:
            raise OSError("simulated CAN bus error")
        self.frames.append((node_id, cmd_id, bytes(data)))


def decoded(odrive):
    """Recorded frames as ("velocity" | "state", node_id, value), in order."""
    result = []
    for node_id, cmd_id, data in odrive.frames:
        if cmd_id == cfg.CMD_SET_INPUT_VEL:
            result.append(("velocity", node_id, struct.unpack("<ff", data)[0]))
        elif cmd_id == cfg.CMD_SET_AXIS_STATE:
            result.append(("state", node_id, struct.unpack("<I", data)[0]))
    return result


def velocities(odrive):
    return [value for kind, _, value in decoded(odrive) if kind == "velocity"]


def drain_queue():
    items = []
    while not cutter_pcan.command_queue.empty():
        items.append(cutter_pcan.command_queue.get_nowait())
    return items


@pytest.fixture(autouse=True)
def empty_command_queue():
    """command_queue is a single module-level queue shared by every test."""
    drain_queue()
    yield
    drain_queue()


@pytest.fixture
def running_cutterhead():
    """A bridge whose cutterhead is turning at cruise speed. The control
    loop thread is NOT started, so anything the E-STOP does must happen
    directly - nothing will ever drain the command queue."""
    odrive = FakeODrive()
    cutterhead = cutter_pcan.CutterheadPCAN()
    cutterhead.odrive = odrive
    cutterhead.controller = MotorController(odrive)
    controller = cutterhead.controller
    controller.running = True
    controller.axes_idle = False
    controller.target_velocity = cfg.CRUISE_VELOCITY
    controller.current_velocity = cfg.CRUISE_VELOCITY
    yield cutterhead
    controller.telemetry.close()       # MotorController opens a UDP socket


# ---- Stopping ----

def test_emergency_stop_sends_zero_velocity_then_idle_to_both_axes(running_cutterhead):
    """Related test-suite cases: TC-038, TC-041, TC-042"""
    assert running_cutterhead.emergency_stop() is True

    frames = decoded(running_cutterhead.odrive)
    for axis in AXES:
        assert ("velocity", axis, 0.0) in frames, f"axis {axis}: no zero velocity sent"
        assert ("state", axis, cfg.AXIS_STATE_IDLE) in frames, f"axis {axis}: not set to idle"
        assert frames.index(("velocity", axis, 0.0)) < frames.index(
            ("state", axis, cfg.AXIS_STATE_IDLE)
        ), f"axis {axis}: idle was sent before zero velocity"


def test_emergency_stop_never_sends_a_nonzero_velocity(running_cutterhead):
    """Related test-suite cases: TC-038, TC-041, TC-042"""
    running_cutterhead.emergency_stop()
    assert all(v == 0.0 for v in velocities(running_cutterhead.odrive))


def test_control_loop_cannot_resume_motion_after_emergency_stop(running_cutterhead):
    """Related test-suite cases: TC-038, TC-044"""
    running_cutterhead.emergency_stop()
    running_cutterhead.odrive.frames.clear()

    # One tick of the real control loop, exactly as its thread would run it.
    running_cutterhead.controller._update_velocity(cfg.LOOP_PERIOD)

    assert all(v == 0.0 for v in velocities(running_cutterhead.odrive))


def test_emergency_stop_discards_commands_queued_before_it(running_cutterhead):
    """Related test-suite cases: none"""
    running_cutterhead.start()            # queued, not yet handled by the loop
    running_cutterhead.emergency_stop()
    assert "start" not in drain_queue()


def test_emergency_stop_still_idles_when_zero_velocity_send_fails(running_cutterhead):
    """Related test-suite cases: none"""
    running_cutterhead.odrive.fail_velocity = True

    result = running_cutterhead.emergency_stop()          # must not raise

    frames = decoded(running_cutterhead.odrive)
    for axis in AXES:
        assert ("state", axis, cfg.AXIS_STATE_IDLE) in frames
    assert result is False, "a partial stop must not be reported as success"


def test_emergency_stop_without_pcan_connection_reports_failure():
    """Related test-suite cases: TC-054"""
    cutterhead = cutter_pcan.CutterheadPCAN()            # start_loop() never ran
    assert cutterhead.emergency_stop() is False


# ---- Latch ----

@pytest.mark.parametrize(
    "method, args",
    [("start", ()), ("set_speed", (10.0,)), ("nudge", (1,))],
    ids=["start", "set_speed", "nudge"],
)
def test_motion_commands_refused_while_emergency_stop_latched(running_cutterhead, method, args):
    """Related test-suite cases: TC-043, TC-044"""
    running_cutterhead.emergency_stop()
    drain_queue()

    getattr(running_cutterhead, method)(*args)

    assert drain_queue() == []


def test_emergency_stop_latches_even_without_pcan_connection():
    """Related test-suite cases: TC-043, TC-054"""
    cutterhead = cutter_pcan.CutterheadPCAN()
    cutterhead.emergency_stop()
    cutterhead.start()
    assert drain_queue() == []


# ---- Clearing ----

def test_clear_emergency_releases_latch(running_cutterhead):
    """Related test-suite cases: TC-045"""
    running_cutterhead.emergency_stop()
    running_cutterhead.clear_emergency()
    drain_queue()

    running_cutterhead.start()

    assert drain_queue() == ["start"]


def test_clear_emergency_does_not_restart_motion(running_cutterhead):
    """Resetting an E-STOP must not by itself restart the machine - the
    operator has to press START separately.

    Related test-suite cases: TC-045"""
    running_cutterhead.emergency_stop()
    running_cutterhead.odrive.frames.clear()
    drain_queue()

    running_cutterhead.clear_emergency()

    frames = decoded(running_cutterhead.odrive)
    assert drain_queue() == []
    assert ("state", 0, cfg.AXIS_STATE_CLOSED_LOOP_CONTROL) not in frames
    assert ("state", 1, cfg.AXIS_STATE_CLOSED_LOOP_CONTROL) not in frames
    assert all(v == 0.0 for v in velocities(running_cutterhead.odrive))
