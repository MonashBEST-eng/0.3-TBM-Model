import numpy as np
import time
from can_adapter import send_can_frame, recv_can_frame

# ========================= CONSTANTS =========================
NUM_LEGS = 2  # Reduced for single ECU testing
dt = 0.1      # time resolution for logging (s)

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
PAIRING = [(0, 1)]
# ============================================================


def rotationMatrix(phi, theta, psi):
    """ZYX Euler rotation matrix (roll-pitch-yaw)."""
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
    """
    Inverse kinematics - returns 2 leg lengths (m) for given pose (subset for testing).
    d_p: translation vector (3,)
    phi, theta, psi: roll, pitch, yaw (rad)
    """
    gamma_p_deg = np.array([22.4615, 97.5385])  # Only legs 1-2
    gamma_b_deg = np.array([20.62,   99.38])    # Only legs 1-2

    gamma_p = np.deg2rad(gamma_p_deg)
    gamma_b = np.deg2rad(gamma_b_deg)

    R = rotationMatrix(phi, theta, psi)
    l_des = np.zeros(NUM_LEGS)

    for i in range(NUM_LEGS):
        p = np.array([
            r_p * np.cos(gamma_p[i]),
            r_p * np.sin(gamma_p[i]),
            -h_p_joints
        ])

        b = np.array([
            r_b * np.cos(gamma_b[i]),
            r_b * np.sin(gamma_b[i]),
            h_b + h_b_joints
        ])

        vec = R @ p + d_p - b
        l_des[i] = np.linalg.norm(vec)

    return l_des


class StewartController:
    def __init__(self):
        # === CAN-only mode: do NOT open any serial ports ===
        # USB-CAN is handled entirely by can_adapter.py
        print("StewartController: CAN-only mode, no COM ports opened.")

        # Assume we always start from neutral pose
        neutral_pose = np.array([0.0, 0.0, 0.35])
        self.l_curr = computeLegs(neutral_pose, 0.0, 0.0, 0.0)

        print("\nInitial leg lengths (neutral pose):")
        for i in range(NUM_LEGS):
            print(f"L{i+1} = {self.l_curr[i]:.4f} m", end="  ")
        print("\n")


    # ===================== CAN HELPERS =====================
    def encode_dir(self, d: int) -> int:
        """
        Map signed direction (-1, 0, +1) to explicit CAN codes:
          0x00 = stop
          0x01 = extend
          0x02 = retract
        """
        if d > 0:
            return 0x01  # extend
        elif d < 0:
            return 0x02  # retract
        else:
            return 0x00  # no move

    def can_send_prepare(self, d1, t1_ms, d2, t2_ms):
        """Send PREPARE command over CAN."""
        b1 = self._encode_dir(d1)
        b2 = self._encode_dir(d2)

        data = bytes([
            b1,
            b2,
            t1_ms & 0xFF,
            (t1_ms >> 8) & 0xFF,
            t2_ms & 0xFF,
            (t2_ms >> 8) & 0xFF
        ])
        send_can_frame(0x100, data)

    def can_send_start(self):
        """Send START command over CAN."""
        send_can_frame(0x100, bytes([0xFF]))

    def can_wait_status(self, expected_code, timeout_s):
        """Block until we see status 'expected_code' from ECU on CAN ID 0x101."""
        t_end = time.time() + timeout_s
        while time.time() < t_end:
            frame = recv_can_frame(timeout=0.1)
            if frame is None:
                continue

            cid, data = frame
            if cid == 0x101 and len(data) >= 1:
                print(f"[PC] Status frame: ID=0x{cid:03X} data={list(data)}")  # debug
                if data[0] == expected_code:
                    return True
        return False

    # ===================== MAIN MOVE =====================
    def send_bangbang_move(self, l_des):
        """Compute bang-bang move, send PREPARE+START over CAN, wait for DONE."""
        # difference in length
        delta = l_des - self.l_curr
        dl = np.abs(delta)

        # direction: -1 = retract, +1 = extend, 0 = no move
        dirs = np.sign(delta).astype(int)
        dirs[dl < 1e-9] = 0

        # time needed for each leg at full speed
        times_s = dl / VMAX
        times_s[dl < 1e-9] = 0.0
        t_max = np.max(times_s) if np.any(dl >= 1e-9) else 0.0

        times_ms = np.round(times_s * 1000).astype(int)

        print(f"Move times (ms): {times_ms}")
        print(f"Directions:       {dirs}")
        print(f"Total move time: {t_max:.3f} s\n")

        # For this single ECU version, we only control the first pair
        leg_a, leg_b = PAIRING[0]
        d1 = int(dirs[leg_a])
        d2 = int(dirs[leg_b])
        t1 = int(times_ms[leg_a])
        t2 = int(times_ms[leg_b])

        # === Step 1: PREPARE over CAN ===
        print("Sending PREPARE via CAN...")
        self.can_send_prepare(d1, t1, d2, t2)

        if not self.can_wait_status(expected_code=0x01, timeout_s=2.0):
            print("ERROR: PREPARED not received")
            return
        print("ECU PREPARED")


        # === Step 2: START over CAN ===
        print("Sending START via CAN...")
        self.can_send_start()

        # Wait for DONE status over CAN
        if not self.can_wait_status(expected_code=0x03, timeout_s=t_max + 5):
            print("ERROR: DONE not received")
            return
        print("ECU DONE")


        print(">>> Actuators completed bang-bang move (CAN status DONE) <<<\n")


        # Update current position
        prev_l = self.l_curr.copy()
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
                            # no movement: stay at previous length
                            pos = prev_l[i]
                        else:
                            if t >= times_s[i]:
                                pos = l_des[i]
                            else:
                                pos = prev_l[i] + dirs[i] * VMAX * t
                        line += f"\t{pos:.6f}"

                    fp.write(line + "\n")


            print("Trajectory logged to stewart_trajectory_single.txt\n")