import time
import odrive
from odrive.enums import *
from odrive.utils import dump_errors

def configure_axis(axis):
    axis.motor.config.current_lim = 10
    axis.controller.config.vel_limit = 2

    axis.motor.config.pole_pairs = 4
    axis.motor.config.torque_constant = 0.5
    axis.motor.config.motor_type = 0

    axis.encoder.config.mode = ENCODER_MODE_HALL
    axis.encoder.config.cpr = 24
    axis.encoder.config.calib_scan_distance = 150

def calibrate_axis(axis, odrv, axis_name):
    print(f"Calibrating {axis_name}...")

    # axis.requested_state = AXIS_STATE_MOTOR_CALIBRATION #No Hall-sensors
    axis.requested_state = AXIS_STATE_FULL_CALIBRATION_SEQUENCE #Hall-Sensors

    #AXIS_STATE_IDLE = 1
    while axis.current_state != AXIS_STATE_IDLE:
        time.sleep(0.2)

    dump_errors(odrv)

    if axis.motor.error != 0:
        raise RuntimeError(f"{axis_name} motor calibration failed")

    axis.motor.config.pre_calibrated = True
    print(f"{axis_name} motor calibration complete")

def enter_closed_loop(axis, odrv, axis_name, velocity=2):
    print(f"Entering closed loop for {axis_name}...")

    # AXIS_STATE_CLOSED_LOOP_CONTROL = 8
    axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
    time.sleep(1)

    dump_errors(odrv)

    if axis.current_state != 8:
        raise RuntimeError(f"{axis_name} failed to enter closed loop")

    axis.controller.input_vel = velocity
    print(f"{axis_name} running at {velocity} turns/s")

if __name__ == "__main__":
    print("Connecting to ODrive...")
    odrv0 = odrive.find_any()

    odrv0.config.brake_resistance = 2

    # Configuring both axis
    configure_axis(odrv0.axis0)
    configure_axis(odrv0.axis1)

    print("Saving configuration...")
    odrv0.save_configuration()

    print("Rebooting...")
    try:
        odrv0.reboot()
    except Exception:
        pass

    time.sleep(5)

    print("Reconnecting...")
    odrv0 = odrive.find_any()

    calibrate_axis(odrv0.axis0, odrv0, "axis0")
    calibrate_axis(odrv0.axis1, odrv0, "axis1")

    print("Saving calibration...")
    odrv0.can.config.baud_rate = 250000
    odrv0.axis0.config.can.node_id = 0
    odrv0.axis1.config.can.node_id = 1
    odrv0.save_configuration()

    enter_closed_loop(odrv0.axis0, odrv0, "axis0", velocity=2)
    enter_closed_loop(odrv0.axis1, odrv0, "axis1", velocity=2)

    print("Setup complete.")