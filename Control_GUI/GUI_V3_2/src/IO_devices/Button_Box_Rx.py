import serial
import serial.tools.list_ports
import threading
import time
from queue import Queue

# ==================================================
# BUTTON BOX CONFIG
# ==================================================
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1          # seconds — short so the read loop can check _running cleanly

NUM_BUTTONS = 25

# Buttons 0-2 are toggles (column 1 of physical box)
TOGGLE_BUTTONS = set(range(0, 3))


# ==================================================
# BUTTON BOX CLASS
# ==================================================
class ButtonBox:
    """
    Thread-safe serial reader for the Arduino physical button box.

    Usage:
        box = ButtonBox(msg_queue)          # share the same queue as MQTT
        box.connect("COM4")                 # starts background thread
        box.disconnect()                    # stops it cleanly

    Messages pushed to msg_queue:
        ("btn_press",   button_id)          # momentary button pressed
        ("btn_toggle",  (button_id, state)) # toggle flipped — state is 0 or 1
        ("btn_status",  "some message")     # connection info / errors
    """

    def __init__(self, msg_queue: Queue):
        self.msg_queue = msg_queue

        self._ser: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        self._last_states   = [0] * NUM_BUTTONS
        self._toggle_states = [0] * NUM_BUTTONS

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------
    def connect(self, port: str) -> bool:
        """Open serial port and start the read thread. Returns True on success."""
        if self._running:
            self.disconnect()

        try:
            self._ser = serial.Serial(port, BAUD_RATE, timeout=SERIAL_TIMEOUT)
        except serial.SerialException as e:
            self.msg_queue.put(("btn_status", f"[BUTTON BOX] Failed to open {port}: {e}"))
            return False

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self.msg_queue.put(("btn_status", f"[BUTTON BOX] Connected on {port}"))
        return True

    def disconnect(self):
        """Stop the read thread and close the serial port."""
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._ser = None
        self.msg_queue.put(("btn_status", "[BUTTON BOX] Disconnected"))

    @property
    def is_connected(self) -> bool:
        return self._running and self._ser is not None and self._ser.is_open

    # --------------------------------------------------
    # STATIC HELPER
    # --------------------------------------------------
    @staticmethod
    def list_ports() -> list[str]:
        """Return a list of available COM port names."""
        return [p.device for p in serial.tools.list_ports.comports()]

    # --------------------------------------------------
    # BACKGROUND READ LOOP
    # --------------------------------------------------
    def _read_loop(self):
        while self._running:
            try:
                raw = self._ser.readline()
            except serial.SerialException as e:
                self.msg_queue.put(("btn_status", f"[BUTTON BOX] Serial error: {e}"))
                self._running = False
                break

            line = raw.decode(errors="ignore").strip()
            if not line:
                continue

            self._parse_line(line)

        # Fell out of loop — make sure port is closed
        if self._ser and self._ser.is_open:
            self._ser.close()

    def _parse_line(self, line: str):
        """Parse a single serial line in the format:  B <button_id> <state>"""
        parts = line.split()
        if len(parts) != 3:
            return

        tag, raw_id, raw_state = parts
        if tag != "B":
            return

        try:
            button_id = int(raw_id)
            state     = int(raw_state)
        except ValueError:
            return

        if not (0 <= button_id < NUM_BUTTONS):
            return

        prev_state = self._last_states[button_id]
        self._last_states[button_id] = state

        # Rising edge only (0 → 1)
        if state != 1 or prev_state != 0:
            return

        if button_id in TOGGLE_BUTTONS:
            # Flip toggle
            self._toggle_states[button_id] ^= 1
            new_toggle = self._toggle_states[button_id]
            self.msg_queue.put(("btn_toggle", (button_id, new_toggle)))
            self._dispatch_toggle(button_id, new_toggle)
        else:
            self.msg_queue.put(("btn_press", button_id))
            self._dispatch_press(button_id)

    # --------------------------------------------------
    # BUTTON ACTION DISPATCH
    # Fill these in as you wire up the physical buttons
    # --------------------------------------------------
    def _dispatch_press(self, button_id: int):
        """Called on rising edge of a momentary button."""
        # fmt: off
        # button_id  →  action
        # 3          →  command.mobility_commands("FORWARD")
        # 4          →  command.mobility_commands("STOP")
        # ...
        pass
        # fmt: on

    def _dispatch_toggle(self, button_id: int, state: int):
        """Called when a toggle button flips. state is 0 (OFF) or 1 (ON)."""
        # button_id  →  action based on state
        # 0          →  command.cutterhead_control("active" if state else "deactivate")
        # 1          →  command.conveyer_control("CONVEYOR_ON" if state else "CONVEYOR_OFF")
        # 2          →  ...
        pass















# import serial
# import time

# # CONTROL BOX LINKING PANEL CONNECTION
# # integration into GUI to control COM PORT







# ## ONCE SETTINGS SET IN GUI THEN START THE BUTTON BOX CONNECTION VIA THE DEFINED COM PORT

# # BUTTON BOX LOGIC
# # read Arduino button box port
# ser = serial.Serial('COM4', 115200, timeout=100000)

# # Define states
# last_states = [0] * 25
# toggle_states = [0] * 25

# # DEFINE TOGGLE BUTTONS WHICH ARE COLUMN 1
# toggles = set(range(0, 3))


# while True:
#     line = ser.readline().decode(errors='ignore').strip()
#     if not line:
#         continue

#     parts = line.split()
#     if len(parts) != 3:
#         continue

#     tag, button_id, state = parts

#     if tag != "B":
#         continue

#     button_id = int(button_id)
#     state = int(state)

#     # --- NORMAL BUTTONS ---
#     if button_id not in toggles:
#         if state == 1 and last_states[button_id] == 0:
#             print(f"Button {button_id} PRESSED")

#     # --- TOGGLES ---
#     else:
#         if state == 1 and last_states[button_id] == 0:
#             toggle_states[button_id] ^= 1
#             print(f"Toggle {button_id} = {'ON' if toggle_states[button_id] else 'OFF'}")

#     last_states[button_id] = state

#     # BUTTON DEFINITION LOGIC
#     # 1 - 
    


#     # 2 - 


#     # 23

#     # 24


#     # 25



#     time.sleep(0.001)




