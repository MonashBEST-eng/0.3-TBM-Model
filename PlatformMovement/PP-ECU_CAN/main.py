# from controller import StewartController, computeLegs
# import numpy as np

# def main():
#     controller = StewartController()

#     while True:
#         cmd = input("\nEnter 'L' for actuator lengths, 'P' for pose, 'Q' to quit: ").strip().upper()

#         if cmd == 'Q':
#             print("Goodbye!")
#             break

#         elif cmd == 'L':
#             try:
#                 vals = list(map(float, input("Enter 2 actuator lengths (m) separated by space: ").split()))
#                 if len(vals) != 2:
#                     raise ValueError
#                 l_des = np.array(vals)

#                 print("Target actuator lengths:")
#                 for i in range(2):
#                     print(f"L{i+1} = {l_des[i]:.4f} m", end="  ")
#                 print("\n")


#                 controller.send_bangbang_move(l_des)

#             except Exception as e:
#                 print(f"Invalid input - need exactly 2 numbers. Error: {e}")

#         elif cmd == 'P':
#             try:
#                 vals = list(map(float, input("Enter desired pose x y z (m) psi(°) theta(°) phi(°): ").split()))
#                 if len(vals) != 6:
#                     raise ValueError
#                 x, y, z, psi_deg, theta_deg, phi_deg = vals

#                 l_des = computeLegs(np.array([x, y, z]),
#                                     np.deg2rad(phi_deg),
#                                     np.deg2rad(theta_deg),
#                                     np.deg2rad(psi_deg))  # Computes for legs 1-2 only

#                 print("Computed actuator lengths (for legs 1-2):")
#                 for i in range(2):
#                     print(f"L{i+1} = {l_des[i]:.4f} m", end="  ")
#                 print("\n")


#                 controller.send_bangbang_move(l_des)

#             except Exception as e:
#                 print(f"Invalid input - need exactly 6 numbers. Error: {e}")

#         else:
#             print("Unknown command.")


# if __name__ == "__main__":
#     main()


import threading
import serial
import serial.tools.list_ports
import time

from controller import StewartController, computeLegs
import numpy as np


# =========================
# ECU USB-CDC DEBUG PORT AUTO-DETECT WITH FALLBACK
# =========================

def list_ports():
    ports = list(serial.tools.list_ports.comports())
    print("[ECU-DBG] Available ports:")
    if not ports:
        print("  (none)")
    for p in ports:
        print(f"  - {p.device}: {p.description}")
    return ports


def rank_ports(ports):
    """
    Return a list of ports ordered by how likely they are to be the STM32 ECU.
    We don't just pick one; we'll try them in order until one opens.
    """
    def score(p):
        desc = p.description.upper()
        s = 0
        # Very STM-looking
        if "STM" in desc or "STMICRO" in desc or "VIRTUAL COM" in desc or "CDC" in desc:
            s += 100
        # Generic USB / serial
        if "USB" in desc or "SERIAL" in desc:
            s += 10
        # De-prioritise known Waveshare CH340 a bit
        if "CH340" in desc:
            s -= 5
        return s

    return sorted(ports, key=score, reverse=True)


def ecu_debug_worker(baud: int):
    """
    Background thread:
    - auto-detect a candidate list of ports
    - try to open them one by one until one works
    - read USB-CDC debug and print with [ECU] prefix
    """
    ports = list_ports()
    if not ports:
        print("[ECU-DBG] No serial ports found at all. Debug disabled.")
        return

    ordered = rank_ports(ports)
    ser = None

    for p in ordered:
        port_name = p.device
        desc = p.description
        print(f"[ECU-DBG] Trying port {port_name} ({desc})...")
        try:
            ser = serial.Serial(port_name, baud, timeout=0.1)
            print(f"[ECU-DBG] Using ECU debug port {port_name} ({desc})")
            break
        except Exception as e:
            print(f"[ECU-DBG] Failed to open {port_name}: {e}")
            ser = None

    if ser is None:
        print("[ECU-DBG] Could not open any port for ECU debug. Continuing without it.")
        return

    try:
        while True:
            try:
                line = ser.readline()
            except Exception as e:
                print(f"[ECU-DBG] Serial read error: {e}")
                break

            if line:
                try:
                    text = line.decode(errors="replace").rstrip()
                except Exception:
                    text = repr(line)
                print(f"[ECU] {text}")
            else:
                time.sleep(0.01)
    finally:
        try:
            ser.close()
        except Exception:
            pass
        print("[ECU-DBG] Debug reader thread exiting")


def main():
    # Start ECU debug reader thread (non-blocking)
    dbg_thread = threading.Thread(
        target=ecu_debug_worker,
        args=(115200,),   # baud is irrelevant for USB-CDC but pyserial needs something
        daemon=True,
    )
    dbg_thread.start()

    controller = StewartController()

    while True:
        cmd = input("\nEnter 'L' for actuator lengths, 'P' for pose, 'Q' to quit: ").strip().upper()

        if cmd == 'Q':
            print("Goodbye!")
            break

        elif cmd == 'L':
            try:
                vals = list(map(float, input("Enter 2 actuator lengths (m) separated by space: ").split()))
                if len(vals) != 2:
                    raise ValueError
                l_des = np.array(vals)

                print("Target actuator lengths:")
                for i in range(2):
                    print(f"L{i+1} = {l_des[i]:.4f} m", end="  ")
                print("\n")

                controller.send_bangbang_move(l_des)

            except Exception as e:
                print(f"Invalid input - need exactly 2 numbers. Error: {e}")

        elif cmd == 'P':
            try:
                vals = list(map(float, input("Enter desired pose x y z (m) psi(°) theta(°) phi(°): ").split()))
                if len(vals) != 6:
                    raise ValueError
                x, y, z, psi_deg, theta_deg, phi_deg = vals

                l_des = computeLegs(
                    np.array([x, y, z]),
                    np.deg2rad(phi_deg),
                    np.deg2rad(theta_deg),
                    np.deg2rad(psi_deg)
                )  # Computes for legs 1-2 only

                print("Computed actuator lengths (for legs 1-2):")
                for i in range(2):
                    print(f"L{i+1} = {l_des[i]:.4f} m", end="  ")
                print("\n")

                controller.send_bangbang_move(l_des)

            except Exception as e:
                print(f"Invalid input - need exactly 6 numbers. Error: {e}")

        else:
            print("Unknown command.")


if __name__ == "__main__":
    main()
