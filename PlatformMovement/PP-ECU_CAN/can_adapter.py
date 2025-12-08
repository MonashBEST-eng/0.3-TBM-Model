import serial
import time

# ==========================
# CONFIG
# ==========================
USB_CAN_PORT = "COM4"      # update if needed
USB_CAN_BAUD = 115200      # matches your working demo script
CAN_BITRATE  = 0x08       # 0x08 = 100 kbps (per Waveshare doc)

ser = None


# ==========================
# Low-level helpers
# ==========================

def _open_serial():
    global ser
    if ser is not None and ser.is_open:
        return
    try:
        ser = serial.Serial(USB_CAN_PORT, USB_CAN_BAUD, timeout=0.1)
        print(f"[can_adapter] Opened {USB_CAN_PORT} @ {USB_CAN_BAUD} bps")
        time.sleep(0.5)
    except Exception as e:
        print(f"[can_adapter] ERROR opening {USB_CAN_PORT}: {e}")
        ser = None


def _checksum(cmd_bytes):
    # Waveshare: checksum = sum(bytes[2:]) & 0xFF
    return sum(cmd_bytes[2:]) & 0xFF


def _send_raw(cmd_bytes):
    if ser is None:
        _open_serial()
    if ser is None:
        print("[can_adapter] Cannot send: serial not open")
        return
    ser.write(bytes(cmd_bytes))
    ser.flush()
    time.sleep(0.02)


# ==========================
# INITIAL CONFIGURATION
# ==========================

def init_can():
    """
    Configure the USB-CAN using the same 20-byte command
    format as in your working example script.
    """
    _open_serial()
    if ser is None:
        print("[can_adapter] init_can aborted: no serial")
        return

    # Disable CAN ID filtering -> accept all messages
    disable_filter_cmd = bytes([0xAA, 0xC8, 0x01, 0x00, 0x55])
    ser.write(disable_filter_cmd)
    time.sleep(0.05)

    print("[can_adapter] Configuring USB-CAN adapter...")

    # 20-byte config (before checksum), same layout as your demo:
    # 0: 0xAA header
    # 1: 0x55 header
    # 2: 0x12  -> 'setting, use variable protocol'
    # 3: CAN baudrate code (0x08 = 100k)
    # 4: frame type: 0x02 extended frame (matches your example; OK for us)
    # 5-8  Filter ID1..4
    # 9-12 Mask ID1..4
    # 13: CAN mode (0x00 normal)
    # 14: auto resend (0x00 auto)
    # 15-18: spare
    cfg = [
        0xAA,
        0x55,
        0x12,
        CAN_BITRATE,  # byte 3: CAN baudrate
        0x00,         # byte 4: Standard frame
        0x00, 0x00, 0x00, 0x00,  # filter ID1..4
        0x00, 0x00, 0x00, 0x00,  # mask ID1..4
        0x00,       # CAN mode: normal
        0x00,       # auto resend on
        0x00, 0x00, 0x00, 0x00,  # spare
    ]
    cfg.append(_checksum(cfg))

    print(f"[can_adapter] Config frame: {cfg}")
    _send_raw(cfg)
    print(f"[can_adapter] USB-CAN configured (CAN bitrate code 0x{CAN_BITRATE:02X})")


# Run config at import
init_can()


# ==========================
# SENDING CAN FRAMES (variable-length protocol)
# ==========================

def send_can_frame(can_id, data_bytes):
    """
    Send a **standard CAN 2.0A frame** using Waveshare variable-length protocol.

    Protocol (from Waveshare PDF, standard frame example):
      AA TYPE ID_LOW ID_HIGH DATA... 55

    TYPE = 0xC0 | (DLC & 0x0F)
      - bit5 = 0 (standard frame, 2-byte ID)
      - bit4 = 0 (data frame)
      - bits0..3 = DLC (0..8)
    ID is little-endian: for ID=0x123 -> 0x23 0x01
    """
    if ser is None:
        _open_serial()
    if ser is None:
        print("[can_adapter] ERROR: serial not open, cannot send CAN frame")
        return

    dlc = len(data_bytes)
    if dlc > 8:
        raise ValueError("CAN data too long (max 8 bytes)")

    type_byte = 0xC0 | (dlc & 0x0F)  # standard, data, DLC

    frame = [
        0xAA,
        type_byte,
        can_id & 0xFF,
        (can_id >> 8) & 0xFF,
    ]
    frame.extend(data_bytes)
    frame.append(0x55)

    print(f"[can_adapter] TX CAN ID=0x{can_id:03X}, DLC={dlc}, raw={frame}")
    ser.write(bytes(frame))
    ser.flush()


# ==========================
# RECEIVING CAN FRAMES
# ==========================

def recv_can_frame(timeout=0.1):
    """
    Receive a CAN frame via the variable-length protocol.

    Expected format:
      AA TYPE ID_LOW ID_HIGH DATA... 55

    Returns (can_id, data_bytes) or None on timeout.
    """
    if ser is None:
        _open_serial()
    if ser is None:
        return None

    t_end = time.time() + timeout

    while time.time() < t_end:
        if ser.in_waiting:
            # Find header 0xAA
            b = ser.read(1)
            if b != b'\xAA':
                continue

            type_byte = ser.read(1)
            if len(type_byte) < 1:
                continue
            type_val = type_byte[0]

            dlc = type_val & 0x0F
            is_std = (type_val & 0x20) == 0      # bit5=0 => standard
            # is_ext = (type_val & 0x20) != 0    # not needed now
            # is_remote = (type_val & 0x10) != 0 # bit4=1 => remote frame

            if not is_std:
                # extended frame – skip ID(4) + data + 0x55
                _ = ser.read(4 + dlc + 1)
                continue

            # Standard frame: 2-byte ID
            id_bytes = ser.read(2)
            if len(id_bytes) < 2:
                continue
            can_id = id_bytes[0] | (id_bytes[1] << 8)

            data = ser.read(dlc)
            if len(data) < dlc:
                continue

            end = ser.read(1)
            if end != b'\x55':
                # bad frame, skip
                continue

            return (can_id, data)

    return None
