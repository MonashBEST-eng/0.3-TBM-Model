"""
Run this ONCE over USB to configure axis1 as a position-mirroring follower
of axis0. After this is saved, axis1 needs no runtime commands at all —
it will track axis0's live encoder position automatically in firmware.
 
axis0 stays in velocity control and keeps getting driven over CAN as before.
"""
 
import odrive
from odrive.enums import *
 
print("Connecting over USB...")
odrv0 = odrive.find_any()
 
# axis0: master, unchanged — driven by velocity setpoints over CAN.
odrv0.axis0.controller.config.control_mode = CONTROL_MODE_VELOCITY_CONTROL
 
# axis1: follower — locks its position to axis0's encoder.
odrv0.axis1.controller.config.control_mode = CONTROL_MODE_POSITION_CONTROL
odrv0.axis1.controller.config.circular_setpoints = True
odrv0.axis1.controller.config.input_mode = INPUT_MODE_MIRROR
 
# Confirmed via diagnostic: this firmware exposes it as axis_to_mirror
# (integer axis index), currently unset at 255.
odrv0.axis1.controller.config.axis_to_mirror = 0
odrv0.axis1.controller.config.mirror_ratio = -1.0  # 1:1 following
 
print("Saving configuration...")
odrv0.save_configuration()
 
print("Rebooting to apply...")
try:
    odrv0.reboot()
except Exception:
    pass  # connection drop during reboot is expected
 
print("Done. axis1 is now a mirror-mode follower of axis0.")
print("You only need to drive axis0 from now on (e.g. via your CAN script).")