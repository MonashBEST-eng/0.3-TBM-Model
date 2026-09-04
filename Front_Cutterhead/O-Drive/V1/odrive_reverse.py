"""
Slowly rotate uncalibrated axis0 in reverse using LOCKIN_SPIN.

Target:
    -0.05 turns/s for 5 seconds
    ≈ -0.25 motor turns

This does not require successful Hall/encoder calibration, but motor
electrical calibration must succeed first.
"""

import time
import odrive
from odrive.enums import *
from odrive.utils import dump_errors


# ---------------------------------------------------------------------------
# Movement settings
# ---------------------------------------------------------------------------

LOCKIN_VELOCITY = -0.1   # turns/s; negative means reverse
LOCKIN_CURRENT = 2.0      # A; increase cautiously if it cannot overcome load
MOVE_TIME = 5.0           # seconds
POLL_INTERVAL = 0.1
MOTOR_CAL_TIMEOUT = 15.0


def wait_until_idle(axis, timeout):
    start_time = time.time()

    while axis.current_state != AXIS_STATE_IDLE:
        if time.time() - start_time > timeout:
            axis.requested_state = AXIS_STATE_IDLE
            raise TimeoutError("Axis did not return to idle")

        time.sleep(POLL_INTERVAL)


def print_errors(odrv0):
    axis = odrv0.axis0

    dump_errors(odrv0)

    print("\naxis0 raw error codes:")
    print(f"  axis.error       = {axis.error}")
    print(f"  motor.error      = {axis.motor.error}")
    print(f"  encoder.error    = {axis.encoder.error}")
    print(f"  controller.error = {axis.controller.error}")


def main():
    print("Connecting to ODrive...")
    odrv0 = odrive.find_any()
    axis = odrv0.axis0

    print("Clearing errors...")
    axis.error = 0

    # Motor electrical calibration does not rely on Hall position feedback.
    print("Running axis0 motor electrical calibration...")
    axis.requested_state = AXIS_STATE_MOTOR_CALIBRATION
    wait_until_idle(axis, MOTOR_CAL_TIMEOUT)

    print_errors(odrv0)

    if axis.error != 0 or axis.motor.error != 0:
        raise RuntimeError(
            "Motor electrical calibration failed. "
            "Axis0 cannot perform a controlled lock-in spin."
        )

    axis.motor.config.pre_calibrated = True

    # ODrive 0.5.x lock-in configuration.
    lockin = axis.config.general_lockin

    lockin.current = LOCKIN_CURRENT
    lockin.vel = LOCKIN_VELOCITY

    # Reach the very low target velocity gently.
    lockin.accel = 0.02

    # Keep running until we explicitly return the axis to idle.
    lockin.finish_on_vel = False
    lockin.finish_on_distance = False

    print(
        f"\nRotating axis0 in reverse at "
        f"{LOCKIN_VELOCITY} turns/s for {MOVE_TIME} seconds..."
    )

    try:
        axis.requested_state = AXIS_STATE_LOCKIN_SPIN
        time.sleep(MOVE_TIME)

    except KeyboardInterrupt:
        print("\nStop requested.")

    finally:
        axis.requested_state = AXIS_STATE_IDLE
        time.sleep(0.5)

    print("Movement stopped.")
    print(
        f"Requested movement: approximately "
        f"{LOCKIN_VELOCITY * MOVE_TIME:.3f} motor turns"
    )

    print_errors(odrv0)


if __name__ == "__main__":
    main()