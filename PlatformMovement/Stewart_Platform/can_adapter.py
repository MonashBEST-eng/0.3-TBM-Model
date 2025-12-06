import serial
import time

# ==========================
# CONFIG
# ==========================
USB_CAN_PORT = "COM6"        # change if needed
USB_CAN_BAUD = 2000000       # baudrate of USB-CAN serial
CAN_BITRATE = 0x04           # 0x04 = 100k, 0x05 = 125k, 0x06 = 250k, 0x07 = 500k, 0x08 = 1M

# Open serial port
ser = serial.Serial(USB_CAN_PORT, USB_CAN_BAUD, timeout=0.1)
time.sleep(0.5)


# ==========================
# Helper: send raw command
# ==========================
def send_cmd(frame_bytes):
    ser.write(bytes(frame_bytes))
    time.sleep(0.02)


# ==========================
# INITIAL CONFIGURATION
# ==========================

def init_can():
    print("Configuring USB-CAN adapter...")

    # 1. Set variable-length protocol
    send_cmd([0xAA, 0x55, 0x12] + [0x00]*17)

    # 2. Set CAN mode = Normal (0x00)
    send_cmd([0xAA, 0x55, 0x12, 0x00] + [0x00]*16)

    # 3. Set CAN bitrate
    send_cmd([0xAA, 0x55, 0x12, 0x00, 0x00, CAN_BITRATE] + [0x00]*14)

    print("USB-CAN configured for bitrate:", CAN_BITRATE)


init_can()


# ==========================
# SENDING CAN FRAMES
# ==========================

def send_can_frame(can_id, data_bytes):
    dlc = len(data_bytes)

    frame = []
    frame.append(0xAA)
    frame.append(0xC8)          # CAN data frame
    frame.append(dlc + 3)       # length = ID(2) + DLC(1) + data
    frame.append(0x01)          # standard frame

    # ID low/high
    frame.append(can_id & 0xFF)
    frame.append((can_id >> 8) & 0xFF)

    # DLC
    frame.append(dlc)

    # Data bytes
    frame.extend(data_bytes)

    # checksum = sum of bytes excluding header
    checksum = sum(frame[2:]) & 0xFF
    frame.append(checksum)

    ser.write(bytes(frame))


# ==========================
# RECEIVING CAN FRAMES
# ==========================

def recv_can_frame(timeout=0.1):
    t_end = time.time() + timeout

    while time.time() < t_end:
        if ser.in_waiting:
            # Minimum header is 3 bytes: AA C8 len
            b = ser.read(1)
            if b != b'\xAA':
                continue

            cmd = ser.read(1)
            if cmd != b'\xC8':
                continue

            length = ser.read(1)[0]
            payload = ser.read(length)

            # payload layout:
            # [0] = frame_type (0x01 std)
            # [1] = ID low
            # [2] = ID high
            # [3] = dlc
            # [4:4+dlc] = data
            # last = checksum (we ignore)

            fid = payload[1] | (payload[2] << 8)
            dlc = payload[3]
            data = payload[4:4+dlc]

            return (fid, data)

    return None
