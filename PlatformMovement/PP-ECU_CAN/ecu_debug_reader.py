import serial
import time

# CHANGE THIS to the COM port that the STM32 USB-CDC shows up as
CDC_PORT = "COM5"
CDC_BAUD = 115200  # value doesn't really matter for USB-CDC on most hosts


def main():
    print(f"Opening ECU debug port {CDC_PORT}...")
    ser = serial.Serial(CDC_PORT, CDC_BAUD, timeout=0.1)
    print(f"Opened: {ser.port}")

    try:
        while True:
            line = ser.readline()
            if line:
                try:
                    text = line.decode(errors="replace").rstrip()
                except Exception:
                    text = repr(line)
                print(f"[ECU] {text}")
    except KeyboardInterrupt:
        print("\nStopping ECU debug reader...")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
