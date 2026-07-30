"""

One-shot ODrive dual-axis setup:

  1. Base motor/encoder config for both axes

  2. Save + reboot

  3. Calibrate both axes

  4. Configure axis0 as velocity-controlled master, axis1 as a

     position-mirroring follower of axis0

  5. Configure CAN

  6. Save + reboot

  7. Enter closed loop on both axes and drive axis0 (axis1 follows in firmware)
 
Run this once over USB. After this, axis1 needs no runtime commands —

drive axis0 (e.g. over CAN) and axis1 will track it automatically.

"""
 
import time

import odrive

from odrive.enums import *

from odrive.utils import dump_errors
 
# --- Tunables -------------------------------------------------------------

CURRENT_LIM = 10          # A

VEL_LIMIT = 50            # turns/s

POLE_PAIRS = 4

TORQUE_CONSTANT = 0.5     # Nm/A

CALIB_SCAN_DISTANCE = 150

CALIBRATION_CURRENT = 3   # A

ENCODER_CPR = 24

CAN_BAUD_RATE = 250000

RUN_VELOCITY = 10         # turns/s, sent to axis0 (master)

BRAKE_RESISTANCE = 2      # ohms

MIRROR_RATIO = -1.0       # set by direction check: gears mesh opposite sides
 
REBOOT_SETTLE_TIME = 2    # s

CLOSED_LOOP_SETTLE_TIME = 1  # s

POLL_INTERVAL = 0.2       # s
 
 
def print_axis_error_codes(axis, axis_name):

    print(f"\n{axis_name} raw error codes:")

    print(f"  axis.error = {axis.error}")

    print(f"  motor.error = {axis.motor.error}")

    print(f"  encoder.error = {axis.encoder.error}")

    print(f"  controller.error = {axis.controller.error}")
 
 
def configure_axis_base(axis):

    """Motor/encoder config common to both axes, before calibration."""

    axis.motor.config.current_lim = CURRENT_LIM

    axis.motor.config.pole_pairs = POLE_PAIRS

    axis.motor.config.torque_constant = TORQUE_CONSTANT

    axis.motor.config.motor_type = 0  # raw value; enum name not exposed in this odrive package version

    axis.motor.config.calibration_current = CALIBRATION_CURRENT
 
    axis.controller.config.vel_limit = VEL_LIMIT

    axis.controller.config.control_mode = CONTROL_MODE_VELOCITY_CONTROL

    axis.controller.config.input_mode = INPUT_MODE_PASSTHROUGH
 
    axis.encoder.config.mode = ENCODER_MODE_HALL

    axis.encoder.config.cpr = ENCODER_CPR

    axis.encoder.config.calib_scan_distance = CALIB_SCAN_DISTANCE
 
 
def clear_axis_errors(odrv):

    odrv.axis0.error = 0

    odrv.axis1.error = 0
 
 
def calibrate_axis(axis, odrv, axis_name):

    print(f"Calibrating {axis_name}...")

    axis.requested_state = AXIS_STATE_FULL_CALIBRATION_SEQUENCE

    while axis.current_state != AXIS_STATE_IDLE:

        time.sleep(POLL_INTERVAL)
 
    dump_errors(odrv)

    print_axis_error_codes(axis, axis_name)
 
    if axis.error != 0 or axis.motor.error != 0 or axis.encoder.error != 0:

        raise RuntimeError(f"{axis_name} calibration failed")
 
    axis.motor.config.pre_calibrated = True

    axis.encoder.config.pre_calibrated = True

    print(f"{axis_name} calibration complete")
 
 
def configure_mirror_relationship(odrv0):

    """axis0 stays velocity-controlled (master). axis1 becomes a

    position-mirroring follower, tracking axis0's live encoder position

    at firmware control-loop rate."""

    odrv0.axis0.controller.config.control_mode = CONTROL_MODE_VELOCITY_CONTROL
 
    odrv0.axis1.controller.config.control_mode = CONTROL_MODE_POSITION_CONTROL

    odrv0.axis1.controller.config.circular_setpoints = True

    odrv0.axis1.controller.config.input_mode = INPUT_MODE_MIRROR

    odrv0.axis1.controller.config.axis_to_mirror = 0

    odrv0.axis1.controller.config.mirror_ratio = MIRROR_RATIO
 
 
def enter_closed_loop(axis, odrv, axis_name):

    print(f"Entering closed loop for {axis_name}...")

    axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL

    time.sleep(CLOSED_LOOP_SETTLE_TIME)

    dump_errors(odrv)
 
    if axis.current_state != AXIS_STATE_CLOSED_LOOP_CONTROL:

        raise RuntimeError(f"{axis_name} failed to enter closed loop")
 
    print(f"{axis_name} in closed loop")
 
 
def stop_axes(odrv0):

    print("Stopping motors...")

    odrv0.axis0.requested_state = AXIS_STATE_IDLE

    odrv0.axis1.requested_state = AXIS_STATE_IDLE

    dump_errors(odrv0)
 
 
def main():

    print("Connecting to ODrive...")

    odrv0 = odrive.find_any()
 
    # Uncomment to fully reset the board before reconfiguring:

    # print("Erasing configuration...")

    # try:

    #     odrv0.erase_configuration()

    # except Exception:

    #     pass  # connection drop during reboot is expected

    # time.sleep(5)

    # print("Reconnecting...")

    # odrv0 = odrive.find_any()
 
    print("Clearing errors...")

    clear_axis_errors(odrv0)

    odrv0.config.brake_resistance = BRAKE_RESISTANCE
 
    configure_axis_base(odrv0.axis0)

    configure_axis_base(odrv0.axis1)
 
    print("Saving configuration...")

    odrv0.save_configuration()
 
    print("Rebooting...")

    try:

        odrv0.reboot()

    except Exception:

        pass  # connection drop during reboot is expected

    time.sleep(REBOOT_SETTLE_TIME)
 
    print("Reconnecting...")

    odrv0 = odrive.find_any()
 
    print("Clearing errors...")

    clear_axis_errors(odrv0)
 
    calibrate_axis(odrv0.axis0, odrv0, "axis0")

    calibrate_axis(odrv0.axis1, odrv0, "axis1")
 
    print("Configuring mirror relationship (axis1 follows axis0)...")

    configure_mirror_relationship(odrv0)
 
    print("Configuring CAN...")

    odrv0.can.set_baud_rate(CAN_BAUD_RATE)

    odrv0.axis0.config.can_node_id = 0

    odrv0.axis1.config.can_node_id = 1
 
    print("Saving configuration...")

    odrv0.save_configuration()
 
    print("Rebooting to apply mirror + CAN config...")

    try:

        odrv0.reboot()

    except Exception:

        pass

    time.sleep(REBOOT_SETTLE_TIME)
 
    print("Reconnecting...")

    odrv0 = odrive.find_any()
 
    # Both axes must be in closed loop for mirroring to engage — axis1

    # still needs to reach closed loop even though it never gets a

    # direct velocity command.

    enter_closed_loop(odrv0.axis0, odrv0, "axis0")

    enter_closed_loop(odrv0.axis1, odrv0, "axis1")
 
    odrv0.axis0.controller.input_vel = RUN_VELOCITY

    print(f"axis0 running at {RUN_VELOCITY} turns/s (axis1 mirroring)")
 
    print("Setup complete.")

    print("Motors running. Press Ctrl+C to stop.")

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        stop_axes(odrv0)
 
 
if __name__ == "__main__":

    main()
 