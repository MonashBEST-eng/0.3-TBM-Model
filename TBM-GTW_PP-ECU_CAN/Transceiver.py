import serial
import time

def calculate_checksum(data):
    # checksum over bytes[2:]
    checksum = sum(data[2:])
    return checksum & 0xFF

def build_can_frame_std(can_id: int, data: bytes) -> bytes:
    """
    Build a variable-length protocol CAN frame for standard ID, data frame.
    can_id: 11-bit ID (0x000 - 0x7FF)
    data: up to 8 bytes
    """
    if len(data) > 8:
        raise ValueError("CAN data too long (max 8 bytes)")

    # Header:
    #  byte0 = 0xAA
    #  byte1: bits 7-6 = 11 (0xC0) => frame marker
    #          bit5   = 0 (standard frame)
    #          bit4   = 0 (data frame)
    #          bits3-0 = DLC (len)
    dlc = len(data)
    second_byte = 0xC0 | (dlc & 0x0F)  # standard, data frame

    id_low  = can_id & 0xFF
    id_high = (can_id >> 8) & 0xFF

    frame = bytearray()
    frame.append(0xAA)
    frame.append(second_byte)
    frame.append(id_low)
    frame.append(id_high)

    frame.extend(data)

    # pad to 8 data bytes if shorter
    while len(frame) < 2 + 2 + 8:
        frame.append(0x00)

    frame.append(0x55)  # end marker

    return bytes(frame)

def configure_can_100kbps_std(ser: serial.Serial):
    # Same as your scripts, but with frame type = 0x01 (standard)
    set_can_baudrate = [
        0xAA,     # 0  Packet header
        0x55,     # 1  Packet header
        0x12,     # 2  Type: variable protocol
        0x08,     # 3  CAN Baud: 0x08 = 100 kbps
        0x01,     # 4  Frame Type: 0x01 = standard frame
        0x00,     # 5  Filter ID1
        0x00,     # 6  Filter ID2
        0x00,     # 7  Filter ID3
        0x00,     # 8  Filter ID4
        0x00,     # 9  Mask ID1
        0x00,     # 10 Mask ID2
        0x00,     # 11 Mask ID3
        0x00,     # 12 Mask ID4
        0x00,     # 13 CAN mode: normal
        0x00,     # 14 auto resend
        0x00,     # 15 Spare
        0x00,     # 16 Spare
        0x00,     # 17 Spare
        0x00,     # 18 Spare
    ]
    checksum = calculate_checksum(set_can_baudrate)
    set_can_baudrate.append(checksum)
    ser.write(bytes(set_can_baudrate))
    print("Sent CAN config (100 kbps, standard frame).")

def read_one_frame(ser: serial.Serial):
    """
    Read a single CAN frame from the adapter using the variable protocol.
    Returns (id_val, data_bytes, frame_type_str, frame_format_str) or None on timeout.
    """
    # Try to get header
    header = ser.read(2)
    if len(header) < 2:
        return None

    if (header[0] != 0xAA) or ((header[1] & 0xC0) != 0xC0):
        # Not a valid CAN frame header – ignore
        return None

    dlc = header[1] & 0x0F
    if (header[1] & 0x10) == 0x00:
        frame_format = "Data Frame"
    else:
        frame_format = "Remote Frame"

    if (header[1] & 0x20) == 0x00:
        frame_type = "Standard Frame"
        extra_len = dlc + 3  # 2 ID + dlc + end
    else:
        frame_type = "Extended Frame"
        extra_len = dlc + 5  # 4 ID + dlc + end

    rest = ser.read(extra_len)
    if len(rest) < extra_len:
        return None

    if rest[-1] != 0x55:
        print("Frame end marker error")
        return None

    if frame_type == "Standard Frame":
        id_val = (rest[1] << 8) | rest[0]
        data_start = 2
    else:
        id_val = ((rest[3] << 24) |
                  (rest[2] << 16) |
                  (rest[1] << 8)  |
                   rest[0])
        data_start = 4

    data_bytes = bytes(rest[data_start:data_start + dlc])

    return id_val, data_bytes, frame_type, frame_format

def main():
    print("Opening COM4...")
    ser = serial.Serial("COM4", 115200, timeout=0.2)
    print("Opened:", ser.portstr)

    # 1) Configure CAN
    configure_can_100kbps_std(ser)
    time.sleep(0.3)

    # 2) Send PING on ID 0x100
    can_id = 0x100
    payload = b"PINGPING"  # 8 bytes
    frame = build_can_frame_std(can_id, payload)
    print("TX frame bytes:", [hex(b) for b in frame])
    ser.write(frame)
    print(f"Sent CAN frame ID=0x{can_id:03X}, data={payload!r}")

    # 3) Listen for frames, look for reply ID 0x101
    print("Listening for reply (ID 0x101)...\n")
    reply_id = 0x101
    timeout_s = 5.0
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        parsed = read_one_frame(ser)
        if parsed is None:
            continue

        rx_id, rx_data, ftype, fformat = parsed
        print(f"RX: ID=0x{rx_id:03X}, data={[hex(b) for b in rx_data]}, {ftype}, {fformat}")

        # Try ASCII decode for fun
        if rx_data:
            try:
                ascii_chunk = rx_data.decode("ascii", errors="ignore")
                if ascii_chunk.strip():
                    print("    ASCII:", repr(ascii_chunk))
            except Exception as e:
                print("    ASCII decode error:", e)

        if ftype == "Standard Frame" and rx_id == reply_id:
            print("\n✅ Got reply from pp-ECU on ID 0x101!")
            break

    else:
        print("\n⏰ Timed out waiting for reply (ID 0x101).")

    ser.close()
    print("Closed COM port.")

if __name__ == "__main__":
    main()
