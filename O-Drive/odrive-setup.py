import time
import odrive
from odrive.enums import *
from odrive.utils import dump_errors

def print_axis_error_codes(axis, axis_name):
    print(f"\n{axis_name} raw error codes:")
    print(f"  axis.error = {axis.error}")
    print(f"  motor.error = {axis.motor.error}")
    print(f"  encoder.error = {axis.encoder.error}")
    print(f"  controller.error = {axis.controller.error}")

def configure_axis(axis):
    axis.motor.config.current_lim = 10
    axis.controller.config.vel_limit = 10
    axis.controller.config.vel_gain = 0.1
    axis.controller.config.vel_integrator_gain = 0.5
    axis.controller.config.control_mode = CONTROL_MODE_VELOCITY_CONTROL
    axis.controller.config.input_mode = INPUT_MODE_PASSTHROUGH
    axis.controller.config.vel_ramp_rate = 5     # turns/s^2, tune as needed

    axis.motor.config.pole_pairs = 4
    axis.motor.config.torque_constant = 0.5
    axis.motor.config.motor_type = 0

    axis.encoder.config.mode = ENCODER_MODE_HALL
    axis.encoder.config.cpr = 24
    axis.encoder.config.calib_scan_distance = 150

    axis.motor.config.calibration_current = 3

def calibrate_axis(axis, odrv, axis_name):
    print(f"Calibrating {axis_name}...")

    axis.requested_state = AXIS_STATE_FULL_CALIBRATION_SEQUENCE

    while axis.current_state != AXIS_STATE_IDLE:
        time.sleep(0.2)

    dump_errors(odrv)
    print_axis_error_codes(axis, axis_name)

    if axis.error != 0 or axis.motor.error != 0 or axis.encoder.error != 0:
        raise RuntimeError(f"{axis_name} calibration failed")

    axis.motor.config.pre_calibrated = True
    axis.encoder.config.pre_calibrated = True

    print(f"{axis_name} calibration complete")

def enter_closed_loop(axis, odrv, axis_name, velocity):
    print(f"Entering closed loop for {axis_name}...")

    axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
    time.sleep(1)

    dump_errors(odrv)

    if axis.current_state != AXIS_STATE_CLOSED_LOOP_CONTROL:
        raise RuntimeError(f"{axis_name} failed to enter closed loop")

    axis.controller.input_vel = velocity
    print(f"{axis_name} running at {velocity} turns/s")

if __name__ == "__main__":
    print("Connecting to ODrive...")
    odrv0 = odrive.find_any()

    print("Clearing errors...")
    odrv0.axis0.error = 0
    odrv0.axis1.error = 0

    odrv0.config.brake_resistance = 2

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

    print("Clearing errors...")
    odrv0.axis0.error = 0
    odrv0.axis1.error = 0
    
    # calibrate_axis(odrv0.axis0, odrv0, "axis0")
    calibrate_axis(odrv0.axis1, odrv0, "axis1")

    print("Saving calibration and CAN config...")
    odrv0.can.set_baud_rate(250000)
    odrv0.axis0.config.can_node_id = 0
    odrv0.axis1.config.can_node_id = 1
    odrv0.save_configuration()

    print(odrv0.axis0.motor.gate_driver.drv_fault)
    print(odrv0.axis1.motor.gate_driver.drv_fault)

    # enter_closed_loop(odrv0.axis0, odrv0, "axis0", velocity=0.5)
    # time.sleep(3)
    enter_closed_loop(odrv0.axis1, odrv0, "axis1", velocity=0.5)
    odrv0.axis1.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
    time.sleep(0.1)
    print(odrv0.axis1.current_state)
    time.sleep(3)
    print(odrv0.axis1.current_state)

    

    print("Setup complete.")
    print("Motors running. Press Ctrl+C to stop.")

    odrv0.axis1.controller.config.control_mode = CONTROL_MODE_TORQUE_CONTROL
    odrv0.axis1.controller.input_torque = 0.1

    try:
        while True:
            odrv0.axis1.controller.input_vel = 1.0

            print("state:", odrv0.axis1.current_state)
            print("input_vel:", odrv0.axis1.controller.input_vel)
            print("vel_estimate:", odrv0.axis1.encoder.vel_estimate)

            print("axis.error:", odrv0.axis1.error)
            print("motor.error:", odrv0.axis1.motor.error)
            print("encoder.error:", odrv0.axis1.encoder.error)
            print("controller.error:", odrv0.axis1.controller.error)
            print()

        time.sleep(0.5)

    except KeyboardInterrupt:
        print("Stopping motors...")
        odrv0.axis0.controller.input_vel = 0
        odrv0.axis1.controller.input_vel = 0