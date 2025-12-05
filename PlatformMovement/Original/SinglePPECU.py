import numpy as np
import serial
import serial.tools.list_ports
import time

# ========================= CONSTANTS =========================
NUM_LEGS = 2  # Reduced for single ECU testing
dt = 0.1  # time resolution for logging (s)

L_min = 0.34
L_max = 0.5

VMAX = 0.006  # m/s - full actuator speed (used for bang-bang timing)

# Geometry (subset for legs 1-2)
r_p = 0.1563788
r_b = 0.1961415
h_b = 0.004
h_p_joints = 0.0
h_b_joints = 0.0

# ECU pairing - only first pair for single ECU
PAIRING = [(0,1)]

BAUDRATE = 115200
# ============================================================


def rotationMatrix(phi, theta, psi):
    """ZYX Euler rotation matrix (roll-pitch-yaw)"""
    cp = np.cos(phi)
    sp = np.sin(phi)
    ct = np.cos(theta)
    st = np.sin(theta)
    cy = np.cos(psi)
    sy = np.sin(psi)

    R = np.array([
        [cy * ct,                  cy * st * sp - sy * cp,  cy * st * cp + sy * sp],
        [sy * ct,                  sy * st * sp + cy * cp,  sy * st * cp - cy * sp],
        [-st,                      ct * sp,                 ct * cp]
    ])
    return R


def computeLegs(d_p, phi, theta, psi):
    """Inverse kinematics - returns 2 leg lengths (m) for given pose (subset for testing)"""
    gamma_p_deg = np.array([22.4615, 97.5385])  # Only legs 1-2
    gamma_b_deg = np.array([20.62,   99.38])    # Only legs 1-2

    gamma_p = np.deg2rad(gamma_p_deg)
    gamma_b = np.deg2rad(gamma_b_deg)

    R = rotationMatrix(phi, theta, psi)
    l_des = np.zeros(NUM_LEGS)

    for i in range(NUM_LEGS):
        p = np.array([r_p * np.cos(gamma_p[i]),
                      r_p * np.sin(gamma_p[i]),
                      -h_p_joints])

        b = np.array([r_b * np.cos(gamma_b[i]),
                      r_b * np.sin(gamma_b[i]),
                      h_b + h_b_joints])

        vec = R @ p + d_p - b
        l_des[i] = np.linalg.norm(vec)

    return l_des


class StewartController:
    def __init__(self):
        # Auto-detect 1 STM32 VCP port or ask manually
        ports = [p.device for p in serial.tools.list_ports.comports()
                 if "USB" in p.description or "STM" in p.description or "ACM" in p.device]

        if len(ports) >= 1:
            self.serials = [serial.Serial(p, BAUDRATE, timeout=1) for p in ports[:1]]
            print("Auto-detected port:", ports[0])
        else:
            print("Could not auto-detect STM32 port. Enter it manually.")
            self.serials = []
            p = input("  ECU1 COM port (e.g. COM4): ").strip()
            self.serials.append(serial.Serial(p, BAUDRATE, timeout=1))

        time.sleep(2)  # wait for reset

        for i, ser in enumerate(self.serials):
            ser.flushInput()
            line = ser.readline().decode().strip()
            print(f"ECU{i+1} says: {line}")

        # Assume we always start from neutral pose
        neutral_pose = np.array([0.0, 0.0, 0.35])
        self.l_curr = computeLegs(neutral_pose, 0.0, 0.0, 0.0)

        print("\nInitial leg lengths (neutral pose):")
        for i in range(NUM_LEGS):
            print(f"L{i+1} = {self.l_curr[i]:.4f} m", end="  ")
        print("\n")

    def send_bangbang_move(self, l_des):
        delta = l_des - self.l_curr
        dl = np.abs(delta)
        dirs = np.sign(delta).astype(int)
        dirs[dl < 1e-9] = 0

        times_s = dl / VMAX
        times_s[dl < 1e-9] = 0.0
        t_max = np.max(times_s) if np.any(dl >= 1e-9) else 0.0

        times_ms = np.round(times_s * 1000).astype(int)

        print(f"Move times (ms): {times_ms}")
        print(f"Directions:       {dirs}")
        print(f"Total move time: {t_max:.3f} s\n")

        # === Step 1: PREPARE ECU ===
        for ecu_idx, (leg_a, leg_b) in enumerate(PAIRING):
            cmd = f"PREPARE {dirs[leg_a]} {times_ms[leg_a]} {dirs[leg_b]} {times_ms[leg_b]}\n"
            self.serials[ecu_idx].write(cmd.encode())

        # Wait for PREPARED
        prepared = [False] * 1
        timeout = time.time() + 5
        while not all(prepared) and time.time() < timeout:
            for i, ser in enumerate(self.serials):
                if ser.in_waiting and not prepared[i]:
                    line = ser.readline().decode().strip()
                    if "PREPARED" in line:
                        prepared[i] = True
                        print(f"ECU{i+1} prepared")
            time.sleep(0.001)

        if not all(prepared):
            print("ERROR: ECU did not respond PREPARED")
            return

        # === Step 2: START ECU ===
        for ser in self.serials:
            ser.write(b"START\n")

        print(">>> Actuators started (full speed bang-bang) <<<\n")

        # === Step 3: Wait for DONE ===
        done = [False] * 1
        timeout = time.time() + t_max + 5
        while not all(done) and time.time() < timeout:
            for i, ser in enumerate(self.serials):
                if ser.in_waiting and not done[i]:
                    line = ser.readline().decode().strip()
                    if "DONE" in line:
                        done[i] = True
                        print(f"ECU{i+1} finished")
            time.sleep(0.01)

        print("*** Movement complete ***\n")

        # Update current position
        self.l_curr[:] = l_des[:]

        # === Log the actual hardware trajectory (bang-bang) ===
        if t_max > 0:
            with open("stewart_trajectory_single.txt", "a") as fp:
                fp.write("--- Bang-bang trajectory (hardware - single ECU) ---\n")
                fp.write("t(s)")
                for i in range(1, NUM_LEGS + 1):
                    fp.write(f"\tL{i}(m)")
                fp.write("\n")

                n_steps = int(t_max / dt) + 10  # a bit extra
                for step in range(n_steps):
                    t = step * dt
                    if t > t_max + 1.0:
                        break
                    line = f"{t:.2f}"
                    for i in range(NUM_LEGS):
                        if dirs[i] == 0 or times_s[i] == 0:
                            pos = self.l_curr[i] - delta[i]  # previous pos
                        else:
                            if t >= times_s[i]:
                                pos = l_des[i]
                            else:
                                pos = self.l_curr[i] - delta[i] + dirs[i] * VMAX * t
                        line += f"\t{pos:.6f}"
                    fp.write(line + "\n")
            print("Trajectory logged to stewart_trajectory_single.txt\n")


def main():
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

            except:
                print("Invalid input - need exactly 2 numbers.")

        elif cmd == 'P':
            try:
                vals = list(map(float, input("Enter desired pose x y z (m) psi(°) theta(°) phi(°): ").split()))
                if len(vals) != 6:
                    raise ValueError
                x, y, z, psi_deg, theta_deg, phi_deg = vals

                l_des = computeLegs(np.array([x, y, z]),
                                    np.deg2rad(phi_deg),
                                    np.deg2rad(theta_deg),
                                    np.deg2rad(psi_deg))  # Computes for legs 1-2 only

                print("Computed actuator lengths (for legs 1-2):")
                for i in range(2):
                    print(f"L{i+1} = {l_des[i]:.4f} m", end="  ")
                print("\n")

                controller.send_bangbang_move(l_des)

            except:
                print("Invalid input - need exactly 6 numbers.")

        else:
            print("Unknown command.")


if __name__ == "__main__":
    main()