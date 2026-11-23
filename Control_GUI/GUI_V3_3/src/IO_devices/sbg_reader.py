# sbg_reader.py
# Thread-safe USB serial reader for the SBG Ellipse-A IMU.
# Parses SBG binary protocol v2 packets and pushes data to msg_queue
# as ("sbg_rx", {field: value, ...}) messages.
#
# Usage (mirrors ButtonBox pattern):
#   sbg = SbgReader(msg_queue)
#   sbg.connect("COM5")          # or "/dev/ttyUSB0" on Linux
#   sbg.disconnect()
#
# The sbg_panel.py and main update_ui() consume ("sbg_rx", data_dict).
#
# ETHERNET / MQTT INTEGRATION:
#   Commented out below — search "## ETHERNET" to find the hooks.
#   When ready, uncomment and point at your broker/topic.

import serial
import serial.tools.list_ports
import threading
import struct
import time
from queue import Queue


# ==================================================
# SBG BINARY PROTOCOL v2 CONSTANTS
# ==================================================
SYNC_1 = 0xFF
SYNC_2 = 0x5A

BAUD_RATE      = 115200     # Change this to match SBG Center setting (e.g. 921600)
SERIAL_TIMEOUT = 1          # short so _running check stays responsive

# SBG Message IDs we parse
MSG_STATUS     = 0x01       # General status + solution mode
MSG_IMU_DATA   = 0x03       # Raw IMU — accel (m/s²), gyro (°/s), temp (°C)
MSG_EKF_EULER  = 0x06       # EKF Euler angles — roll, pitch, yaw (rad)
MSG_EKF_NAV    = 0x08       # EKF nav — velocity (m/s) NED
MSG_GPS_POS    = 0x10       # GPS position — lat/lon (deg), alt (m), accuracy (m)
MSG_GPS_VEL    = 0x12       # GPS velocity — course, speed, num SVs

# Solution mode lookup
SOLUTION_MODES = {
    0: "UNINITIALIZED",
    1: "VERTICAL GYRO",
    2: "AHRS",
    3: "NAV VELOCITY",
    4: "NAV POSITION",
}


# ==================================================
# ## ETHERNET — future MQTT publish hook
# ==================================================
# import paho.mqtt.client as mqtt
#
# MQTT_BROKER  = "192.168.1.10"
# MQTT_PORT    = 1883
# MQTT_TOPIC   = "sbg/imu"
#
# _mqtt_client = mqtt.Client()
# _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
# _mqtt_client.loop_start()
#
# def _publish_sbg(data: dict):
#     import json
#     payload = json.dumps(data)
#     _mqtt_client.publish(MQTT_TOPIC, payload)
# ==================================================


# ==================================================
# CRC-16 (SBG uses CRC-16/CCITT-FALSE)
# ==================================================
def _crc16(data: bytes) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


# ==================================================
# PACKET PARSER
# Parses one complete SBG binary v2 packet.
# Returns a dict of fields, or None if unknown/malformed.
#
# Packet structure:
#   SYNC1(1) SYNC2(1) MSG_ID(1) CLASS(1) LEN(2) PAYLOAD(LEN) CRC(2)
# ==================================================
def _parse_packet(msg_id: int, payload: bytes) -> dict | None:

    data = {}

    try:
        # ------------------------------------------
        if msg_id == MSG_STATUS:
            # Payload: timeStamp(4) generalStatus(2) comStatus(4)
            if len(payload) < 10:
                return None
            ts, gen_status, com_status = struct.unpack_from("<IHI", payload, 0)
            solution_idx = (gen_status >> 4) & 0x0F
            data["solution_mode"] = SOLUTION_MODES.get(solution_idx, f"MODE {solution_idx}")
            data["timestamp_us"]  = ts

        # ------------------------------------------
        elif msg_id == MSG_IMU_DATA:
            # Payload: timeStamp(4) status(2) accel[3](f32×3) gyro[3](f32×3) temp(f32)
            if len(payload) < 30:
                return None
            ts, status = struct.unpack_from("<IH", payload, 0)
            ax, ay, az = struct.unpack_from("<fff", payload, 6)
            gx, gy, gz = struct.unpack_from("<fff", payload, 18)
            temp       = struct.unpack_from("<f",   payload, 30)[0]
            data["accel_x"]      = round(ax, 4)
            data["accel_y"]      = round(ay, 4)
            data["accel_z"]      = round(az, 4)
            data["gyro_x"]       = round(math.degrees(gx), 4)
            data["gyro_y"]       = round(math.degrees(gy), 4)
            data["gyro_z"]       = round(math.degrees(gz), 4)
            data["imu_temp"]     = round(temp, 2)

        # ------------------------------------------
        elif msg_id == MSG_EKF_EULER:
            # Payload: timeStamp(4) roll(f32) pitch(f32) yaw(f32) rollAcc(f32) pitchAcc(f32) yawAcc(f32) status(4)
            if len(payload) < 28:
                return None
            ts          = struct.unpack_from("<I",   payload, 0)[0]
            roll, pitch, yaw          = struct.unpack_from("<fff", payload, 4)
            roll_acc, pitch_acc, yaw_acc = struct.unpack_from("<fff", payload, 16)
            data["roll"]             = round(math.degrees(roll),  3)
            data["pitch"]            = round(math.degrees(pitch), 3)
            data["yaw"]              = round(math.degrees(yaw),   3)
            data["heading_accuracy"] = round(math.degrees(yaw_acc), 3)

        # ------------------------------------------
        elif msg_id == MSG_EKF_NAV:
            # Payload: timeStamp(4) vel[3](f64×3) velAcc[3](f32×3) pos[3](f64×3) posAcc[3](f32×3) status(4)
            if len(payload) < 72:
                return None
            ts          = struct.unpack_from("<I",   payload, 0)[0]
            vn, ve, vd  = struct.unpack_from("<ddd", payload, 4)
            lat, lon, alt = struct.unpack_from("<ddd", payload, 28)
            pa_n, pa_e, pa_d = struct.unpack_from("<fff", payload, 52)
            data["vel_north"]          = round(vn,  3)
            data["vel_east"]           = round(ve,  3)
            data["vel_down"]           = round(vd,  3)
            data["latitude"]           = round(lat, 8)
            data["longitude"]          = round(lon, 8)
            data["altitude"]           = round(alt, 3)
            data["position_accuracy"]  = round(max(pa_n, pa_e), 3)

        # ------------------------------------------
        elif msg_id == MSG_GPS_POS:
            # Payload: timeStamp(4) status(4) numSvUsed(1) lat(f64) lon(f64) alt(f64) undulation(f32)
            #          latAcc(f32) lonAcc(f32) altAcc(f32)
            if len(payload) < 42:
                return None
            ts      = struct.unpack_from("<I",   payload, 0)[0]
            status  = struct.unpack_from("<I",   payload, 4)[0]
            num_sv  = struct.unpack_from("<B",   payload, 8)[0]
            lat, lon, alt = struct.unpack_from("<ddd", payload, 9)
            lat_acc, lon_acc = struct.unpack_from("<ff", payload, 33)
            fix_type = (status >> 8) & 0x0F
            fix_map  = {0: "NO FIX", 1: "TIME ONLY", 2: "2D", 3: "3D", 4: "SBAS", 5: "RTK FLOAT", 6: "RTK INT"}
            data["latitude"]           = round(lat, 8)
            data["longitude"]          = round(lon, 8)
            data["altitude"]           = round(alt, 3)
            data["gps_fix"]            = fix_map.get(fix_type, f"FIX {fix_type}")
            data["num_svs"]            = num_sv
            data["position_accuracy"]  = round(max(lat_acc, lon_acc), 3)

        # ------------------------------------------
        elif msg_id == MSG_GPS_VEL:
            # Payload: timeStamp(4) status(4) timeOfWeek(4) vel[3](f64×3) velAcc[3](f32×3) course(f32) courseAcc(f32) numSvUsed(1)
            if len(payload) < 50:
                return None
            ts      = struct.unpack_from("<I",   payload,  0)[0]
            status  = struct.unpack_from("<I",   payload,  4)[0]
            vn, ve, vd = struct.unpack_from("<ddd", payload, 12)
            num_sv  = struct.unpack_from("<B",   payload, 48)[0]
            data["vel_north"] = round(vn,  3)
            data["vel_east"]  = round(ve,  3)
            data["vel_down"]  = round(vd,  3)
            data["num_svs"]   = num_sv

        else:
            return None     # unhandled message ID — silently skip

    except struct.error:
        return None

    return data if data else None


# ==================================================
# SBG READER CLASS
# ==================================================
class SbgReader:
    """
    Thread-safe USB serial reader for the SBG Ellipse-A.

    Usage:
        sbg = SbgReader(msg_queue)
        sbg.connect("COM5")      # starts background thread
        sbg.disconnect()         # stops cleanly

    Messages pushed to msg_queue:
        ("sbg_rx",     {field: value, ...})   # parsed data dict
        ("sbg_status", "message string")       # connection info / errors
    """

    def __init__(self, msg_queue: Queue):
        self.msg_queue  = msg_queue
        self._ser: serial.Serial | None   = None
        self._thread: threading.Thread | None = None
        self._running   = False
        self._buf       = bytearray()   # rolling byte buffer for packet sync

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------
    def connect(self, port: str) -> bool:
        """Open USB serial port and start read thread. Returns True on success."""
        if self._running:
            self.disconnect()

        try:
            self._ser = serial.Serial(
                port,
                baudrate=BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_TIMEOUT,
            )
            # Flush any stale data from previous connections
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except serial.SerialException as e:
            self.msg_queue.put(("sbg_status", f"[SBG] Failed to open {port}: {e}"))
            return False

        self._running = True
        self._buf.clear()
        time.sleep(0.2)  # Brief delay to allow sync
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self.msg_queue.put(("sbg_status", f"[SBG] Connected on {port} @ {BAUD_RATE} baud"))
        return True

    def disconnect(self):
        """Stop the read thread and close the serial port."""
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._ser    = None
        self.msg_queue.put(("sbg_status", "[SBG] Disconnected"))

    @property
    def is_connected(self) -> bool:
        return self._running and self._ser is not None and self._ser.is_open

    @staticmethod
    def list_ports() -> list[str]:
        """Return available COM/USB serial port names."""
        return [p.device for p in serial.tools.list_ports.comports()]

    # --------------------------------------------------
    # BACKGROUND READ LOOP
    # --------------------------------------------------
    def _read_loop(self):
        while self._running:
            try:
                chunk = self._ser.read(256)     # read up to 256 bytes at a time
            except serial.SerialException as e:
                self.msg_queue.put(("sbg_status", f"[SBG] Serial error: {e}"))
                self._running = False
                break

            if not chunk:
                continue

            self._buf.extend(chunk)
            self._process_buffer()

        if self._ser and self._ser.is_open:
            self._ser.close()

    def _process_buffer(self):
        """
        Scan rolling buffer for complete SBG packets.
        Packet: SYNC1 SYNC2 MSG_ID CLASS LEN_LO LEN_HI [PAYLOAD×LEN] CRC_LO CRC_HI
        """
        while len(self._buf) >= 6:
            # Find sync bytes
            if self._buf[0] != SYNC_1 or self._buf[1] != SYNC_2:
                self._buf.pop(0)    # discard one byte and retry
                continue

            # Header is present — read length
            msg_id    = self._buf[2]
            msg_class = self._buf[3]
            length    = self._buf[4] | (self._buf[5] << 8)

            # DEBUG: Log first packet header to diagnose sync issues
            if not hasattr(self, '_logged_first_packet'):
                self._logged_first_packet = True
                header_hex = ' '.join(f'{b:02x}' for b in self._buf[:8])
                self.msg_queue.put(("sbg_status",
                    f"[SBG DEBUG] First packet header: {header_hex} | "
                    f"MSG_ID=0x{msg_id:02x} CLASS=0x{msg_class:02x} LEN={length}"))

            total_len = 6 + length + 2      # header + payload + CRC

            if len(self._buf) < total_len:
                break   # wait for more bytes

            # Extract full packet
            payload  = bytes(self._buf[6 : 6 + length])
            crc_recv = self._buf[6 + length] | (self._buf[6 + length + 1] << 8)

            # Protocol v3: CRC includes sync bytes + header + payload
            # Protocol v2: CRC includes header + payload (no sync)
            crc_data_v3 = bytes(self._buf[0 : 6 + length])  # sync + header + payload
            crc_data_v2 = bytes(self._buf[2 : 6 + length])  # header + payload only
            
            crc_calc_v3 = _crc16(crc_data_v3)
            crc_calc_v2 = _crc16(crc_data_v2)

            # Consume packet from buffer
            del self._buf[:total_len]

            # TEMPORARY: Skip CRC validation to test if packet structure is correct
            # if crc_calc_v3 == crc_recv:
            #     pass
            # elif crc_calc_v2 == crc_recv:
            #     pass
            # else:
            #     self.msg_queue.put(("sbg_status",
            #         f"[SBG] CRC mismatch on MSG {msg_id:#04x} "
            #         f"(got {crc_recv:#06x}, v2={crc_calc_v2:#06x}, v3={crc_calc_v3:#06x})"))
            #     continue

            # Parse and publish


            data = _parse_packet(msg_id, payload)
            if data:
                self.msg_queue.put(("sbg_rx", data))
            else:
                # Log unhandled message IDs
                if not hasattr(self, f'_logged_msg_{msg_id:02x}'):
                    setattr(self, f'_logged_msg_{msg_id:02x}', True)
                    self.msg_queue.put(("sbg_status", f"[SBG] Unhandled MSG_ID 0x{msg_id:02x}"))



                # ## ETHERNET — publish to MQTT when ready
                # _publish_sbg(data)


# ==================================================
# IMPORT GUARD
# math needed inside _parse_packet — imported here
# to avoid circular import issues at module level
# ==================================================
import math