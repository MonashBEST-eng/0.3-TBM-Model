# GUI_V3_2 — Code Overview

Tkinter desktop app for the Monash BEST TBM. It talks to the **STM32H7 gateway over MQTT/Ethernet** for most subsystems, and to the **front cutterhead ODrive directly over a PCAN-USB adapter** (new in V3_2). It also reads a physical **Arduino button box** and an **SBG Ellipse-A IMU**, both over USB serial.

~7.8k lines of Python. Entry point: `src/1_2026_GUI.py`.

---

## 1. How to run

```powershell
cd Control_GUI/GUI_V3_2/src
python 1_2026_GUI.py
```

- **Run from `src/`.** Imports are package-relative to `src` (`GUI_menus.*`, `IO_devices.*`, `GTW_Control_Comms.*`), and the log path `outputs/system_log.txt` is relative to the current directory. That's why both `src/outputs/` and `GUI_V3_2/outputs/` exist.
- **Dependencies:** `paho-mqtt`, `pyserial`, `Pillow`, `python-can` (with the PEAK PCAN driver), and optionally `openpyxl` for Excel export in the System Log panel.
- **Persisted settings:** `~/.tbm_gui_settings.json` (managed by `settings_store.py`). Defaults: broker `192.168.1.10:1883`, shutdown password `0000`.
- **PCAN only allows one process at a time.** Don't run the standalone cutterhead `main.py` while the GUI holds `PCAN_USBBUS1`. Running `monitor.py` (the UDP telemetry viewer) alongside the GUI is fine.

---

## 2. Folder layout

```
src/
├── 1_2026_GUI.py                  Main window, sidebar, message-dispatch loop (update_ui)
├── GTW_Control_Comms/             Everything that goes over MQTT to the H7 gateway
│   ├── gtw_mqtt_commands.py       MQTT client, msg_queue, handshake, all command functions
│   ├── can_command_dictionary.py  (topic, payload) → raw CAN frame table + wire-format encode/decode
│   └── odrive_can.py              ODrive CAN-Simple encoders for the OLD H7-relay path (legacy)
├── GUI_menus/                     One file per Toplevel panel, plus shared helpers
│   ├── dashboard_panel.py         E-STOP mushroom (shared state), comms/control logs, camera placeholders
│   ├── control_panel.py           Grid of control cards: Safety, Heartbeat, Startup, Conveyor, Cutterhead (PCAN), LED test
│   ├── monitoring_panel.py        SENSORS table + thresholds → raises alarms
│   ├── alarms_panel.py            Central alarm registry (raise/clear/ack/dismiss, history)
│   ├── heartbeat_panel.py         5 s GUI↔STM deadman's switch; trips E-STOP after 15 s of silence
│   ├── sbg_panel.py               IMU fields + artificial horizon
│   ├── button_box_link_panel.py   COM-port picker for the physical button box (owns the ButtonBox singleton)
│   ├── settings_panel.py / settings_store.py   Settings UI + JSON persistence
│   ├── system_log_panel.py        Reads outputs/system_log.txt: search, filter, export
│   ├── file_logger.py             Buffered append-only writer for system_log.txt
│   ├── splash_panel.py            Sponsor logos in the main content area
│   └── ui_widgets.py              Round "industrial pushbutton" Canvas widget
└── IO_devices/                    Hardware drivers that run on background threads
    ├── cutterhead_pcan_bridge.py  NEW: wraps cutterhead_pcan/ for in-process use (singleton)
    ├── cutterhead_pcan/           Copied standalone PCAN ODrive controller (deliberately left unmodified)
    │   ├── config.py              Bus, node IDs, MAX_VELOCITY=35, RAMP_RATE=1.0, loop 50 ms
    │   ├── can_interface.py       ODriveCAN: python-can wrapper (set state, velocity, encoder, hard_stop)
    │   ├── controller.py          MotorController.run(): drains command_queue, ramps velocity
    │   ├── commands.py            command_queue (shared) + the old stdin reader
    │   └── telemetry.py           UDP JSON → monitor.py on 127.0.0.1:5055
    ├── Button_Box_Rx.py           Serial reader for "B <id> <state>" lines (25 buttons, 0-2 are toggles)
    ├── sbg_reader.py              SBG binary protocol v2 parser
    └── odrive_controller.py       OLD H7-relay ODrive ramp controller (no longer instantiated)
```

---

## 3. Architecture

### Threads and the message queue

Everything except the cutterhead feeds **one shared `queue.Queue`**, `gtw_mqtt_commands.msg_queue`, as `(msg_type, data)` tuples. The Tk main thread drains it in `update_ui()` every 100 ms, handling at most 50 messages per tick so the GUI can't freeze.

```
 MQTT thread (paho loop_forever) ──┐
 Handshake resend thread (5 s)  ───┤
 ButtonBox serial thread        ───┼──► msg_queue ──► update_ui() [Tk thread, 100 ms]
 SbgReader serial thread        ───┘                    │
                                                        ├─► log_comms / log_status (dashboard + file_logger)
                                                        ├─► update_sensor()  → monitoring_panel → alarms
                                                        ├─► update_sbg()     → sbg_panel
                                                        └─► alarms_panel.raise/clear

 Cutterhead (separate path, no msg_queue):
 Control Panel buttons ─► CutterheadPCAN.set_speed/stop ─► commands.command_queue
                                                            └─► MotorController.run() thread ─► PCAN-USB ─► ODrive
 Control Panel polls cutterhead.get_status() every 250 ms
```

`msg_type` values handled in `update_ui()`:

| type | from | effect |
|---|---|---|
| `conn` | MQTT on_connect / loop | MQTT indicator, status card, `MQTT_CONN` alarm |
| `mqtt_rx` | MQTT on_message (`stm32/#`) | Comms log. Handles `stm32/can_rx`, `stm32/handshake_ack` (TBM Ready dot) and `stm32/heartbeat_ack`, then parses `KEY:val,KEY:val` telemetry into `update_sensor()` |
| `mqtt_tx` | every command function | Comms log + human-readable control log. ESTOP/SAFE_MODE/CLEAR also raise or clear alarms |
| `sbg_rx` / `sbg_status` | SbgReader | IMU panel / comms log |
| `btn_status` / `btn_press` / `btn_toggle` | ButtonBox | Control log, `BTNBOX_CONN` alarm |
| anything else (for example `odrive_status`) | various | falls through to the control log |

### Commands to the H7 (MQTT)

Each command function in `gtw_mqtt_commands.py` does three things:

1. Publishes a human-readable topic and payload, such as `tbm/conveyer | START`.
2. Puts a `mqtt_tx` message on the queue for logging.
3. Calls `_relay_can_command()`. This looks up `(topic, payload)` in `can_command_dictionary.CAN_COMMANDS` and publishes a raw frame on `tbm/can_tx` as `"<hex_id>,<ext>,<rtr>,<dlc>,<hex_data>"`. The H7 is a dumb relay that puts the frame straight onto the bus.

CAN ID groups: `0x010` safety, `0x020` startup, `0x030` op mode, `0x040` mobility, `0x050` cutterhead, `0x080` conveyor.

**To add a new command:** add a row to `CAN_COMMANDS` in `can_command_dictionary.py`, add a wrapper in `gtw_mqtt_commands.py` if the topic is new, and add a button tuple in `control_panel._categories()`. No firmware change is needed.

### Link-health protocols with the H7

- **Handshake:** the GUI sends `tbm/handshake` on connect and again every 5 s. When `stm32/handshake_ack` comes back, the TBM Ready dot turns green. The periodic resend re-arms the gateway after the H7 reboots.
- **Heartbeat (deadman's switch):** the GUI sends `tbm/heartbeat` every 5 s and the STM replies on `stm32/heartbeat_ack`. If 15 s pass with no ACK, `dashboard_panel.trip_emergency_external()` trips the E-STOP. Recovery needs the RESUME button, which goes through the same password-gated reset as the mushroom.

### E-STOP

The armed/tripped state is the module global `_estop_active` in `dashboard_panel.py`. It's shared by the sidebar mushroom, the Dashboard mushroom and the heartbeat watchdog. Every trigger ends up calling `gtw_mqtt_commands.emergency_mode("EMERGENCY_STOP" | "SAFE_MODE" | "CLEAR EMERGENCY")`.

---

## 4. What changed from V3_1

- **The cutterhead ODrive moved off the H7 relay onto direct PCAN.** New files: `IO_devices/cutterhead_pcan_bridge.py` and `IO_devices/cutterhead_pcan/`. The Control Panel's cutterhead card now drives that path.
- The H7-based `OdriveController` and the `odrive_*` message handlers were removed from the main loop on purpose, to avoid two CAN masters on one bus. `odrive_controller.py` and `odrive_can.py` were kept but aren't used.
- `update_ui()` now limits how many messages it processes per tick, and the handshake is resent every 5 s.

---

## 5. Known issues and loose ends (start here)

### ⚠️ Safety: E-STOP does not stop the PCAN cutterhead

`emergency_mode()` → `odrive_emergency_stop()` (`GTW_Control_Comms/gtw_mqtt_commands.py` ~L219 and ~L348) still targets the **old H7 path**:

- `from GUI_menus.control_panel import get_odrive_controller` fails. That function no longer exists, so the error is caught and only logged.
- It then sends zero-velocity and idle frames over **MQTT to the H7**. The cutterhead is now on PCAN, so those frames don't reach it unless the H7 still shares the bus, which is the exact two-master setup V3_2 was trying to avoid.
- **Nothing calls `get_cutterhead_pcan()` from any E-STOP path.** That covers the mushroom buttons, the Safety card, SAFE MODE and the heartbeat watchdog. **The cutterhead keeps spinning after an E-STOP.**
- Even an ordinary `stop` ramps down at `RAMP_RATE = 1.0` turns/s², so stopping from 35 turns/s takes about 35 s. An E-STOP should use `ODriveCAN.hard_stop()` (or zero velocity followed by idle) instead of the ramped `stop`, and should hold off further commands until it's cleared.
- `CLEAR EMERGENCY` hits the same dead import (`get_odrive_controller().clear_emergency()`).
- `safe_close()` destroys the window without stopping the cutterhead. The daemon thread just dies, and the ODrive keeps its last setpoint unless its CAN watchdog is configured.

### Other loose ends

- **Button box actions are stubs.** `_dispatch_press` and `_dispatch_toggle` in `Button_Box_Rx.py` are empty (`pass`), so physical buttons only log.
- **Cameras are placeholders.** `dashboard_panel.make_camera_panel` only draws a "CAMERA DISCONNECTED" canvas, and `update_graph` is a no-op.
- **Monitoring values are placeholders** until real `KEY:val` telemetry topics come from the H7.
- **Telemetry parse errors are silent.** A bare `except: pass` in `update_ui()` swallows any malformed payload, including every non-telemetry `stm32/*` message.
- **Some Display settings aren't applied.** Accent colour and splash autorotate are saved but not wired up (noted in `settings_panel.py`).
- **No CLEAR ERRORS for the cutterhead.** The PCAN package has no `Clear_Errors` command, so ODrive faults have to be cleared with `odrivetool` over USB.
- **Cutterhead connection failures are permanent for the session.** `CutterheadPCAN.start_loop()` won't retry after a failed open until the GUI restarts. It only connects when the Control Panel is first opened.
- **Leftover dead code:** `odrive_request_encoder` stub, `odrive_status` messages that only reach the fallback log, `_Stub` labels in the main file, and commented-out legacy code at the bottom of `Button_Box_Rx.py`.
- **`__pycache__` and `outputs/*.txt` are committed to git.** They should probably go in `.gitignore`.
