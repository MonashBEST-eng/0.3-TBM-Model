import time
import odrive
from odrive.enums import *
from odrive.utils import dump_errors

LOCKIN_CURRENT = 2.0
LOCKIN_SPEED = 1000
LOCKIN_ACCEL = LOCKIN_SPEED * 0.1
RUN_TIME = 10

def configure_lockin(axis, velocity):
    axis.config.general_lockin.current = LOCKIN_CURRENT
    axis.config.general_lockin.vel = velocity
    axis.config.general_lockin.accel = LOCKIN_ACCEL
    axis.config.general_lockin.finish_on_vel = False
    axis.config.general_lockin.finish_on_distance = False

def stop_both(odrv0):
    odrv0.axis0.requested_state = AXIS_STATE_IDLE
    odrv0.axis1.requested_state = AXIS_STATE_IDLE

def main():
    print("Connecting to ODrive...")
    odrv0 = odrive.find_any()

    odrv0.axis0.error = 0
    odrv0.axis1.error = 0

    # Same motor-shaft directions produce the same cutterhead direction.
    configure_lockin(odrv0.axis0, LOCKIN_SPEED)
    configure_lockin(odrv0.axis1, LOCKIN_SPEED)

    print("Starting lock-in spin on both axes...")

    try:
        odrv0.axis0.requested_state = AXIS_STATE_LOCKIN_SPIN
        odrv0.axis1.requested_state = AXIS_STATE_LOCKIN_SPIN

        time.sleep(RUN_TIME)

    except KeyboardInterrupt:
        print("\nStop requested.")

    finally:
        stop_both(odrv0)
        time.sleep(0.5)

    print("Both axes stopped.")
    dump_errors(odrv0)

if __name__ == "__main__":
    main()