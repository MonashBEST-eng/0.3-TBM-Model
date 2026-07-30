ODrive CAN controller with two-terminal telemetry
=================================================

Only main.py opens PCAN_USBBUS1. It publishes encoder telemetry over localhost
UDP to monitor.py, avoiding the PCAN exclusive-access error.

Terminal 1:
  python main.py

Terminal 2:
  python monitor.py

Both terminals must use files from this same folder/version.

Commands in main.py:
  start
  stop
  speed <turns/s>
  +
  -
  quit
