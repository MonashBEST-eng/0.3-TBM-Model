import numpy as np
import time
from can_adapter import send_can_frame, recv_can_frame
from kinematics import NUM_LEGS, VMAX, dt, computeLegs

# ========================= CONSTANTS =========================
PAIRING = [
    (0, 1),   # ECU 0
    (2, 3),   # ECU 1
    (4, 5),   # ECU 2
]
NUM_ECUS = len(PAIRING)

def CAN_ID_PREPARE(ecu_idx): return 0x200 + ecu_idx
CAN_ID_START_BCAST = 0x210
def CAN_ID_STATUS(ecu_idx):  return 0x300 + ecu_idx

STATUS_PREPARED = 0x01
STATUS_DONE     = 0x03
# ============================================================

class StewartController:
    def __init__(self, neutral_pose=None):
        """
        neutral_pose: (x, y, z, phi, theta, psi) in metres/radians.
        If None, use your old default neutral pose from FullSystem.
        """
        if neutral_pose is None:
            # whatever you used in FullSystemPPECU as the “home”
            pos = np.array([0.0, 0.0, 0.35])
            phi = theta = psi = 0.0
        else:
            x, y, z, phi, theta, psi = neutral_pose
            pos = np.array([x, y, z])

        self.l_curr = computeLegs(pos, phi, theta, psi)

        print("Initial leg lengths:")
        for i in range(NUM_LEGS):
            print(f"L{i+1} = {self.l_curr[i]:.4f} m", end="  ")
        print("\n")

    # ------------- CAN helpers -------------

    def _send_prepare_for_ecu(self, ecu_idx, dir1, t1_ms, dir2, t2_ms):
        b1 = dir1 & 0xFF
        b2 = dir2 & 0xFF
        data = bytes([
            b1, b2,
            t1_ms & 0xFF, (t1_ms >> 8) & 0xFF,
            t2_ms & 0xFF, (t2_ms >> 8) & 0xFF,
        ])
        send_can_frame(CAN_ID_PREPARE(ecu_idx), data)

    def _send_start_broadcast(self):
        send_can_frame(CAN_ID_START_BCAST, bytes([0xFF]))

    def _wait_all_status(self, expected_code, timeout_s):
        got = [False] * NUM_ECUS
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            if all(got):
                return True

            frame = recv_can_frame(timeout=0.05)
            if frame is None:
                continue

            cid, data = frame
            if not data:
                continue

            for ecu_idx in range(NUM_ECUS):
                if cid == CAN_ID_STATUS(ecu_idx) and data[0] == expected_code:
                    got[ecu_idx] = True
                    break

        print("Timeout waiting for status", hex(expected_code), "from",
              [i for i, ok in enumerate(got) if not ok])
        return False

    # ------------- main move method -------------

    def send_bangbang_move(self, l_des):
        l_des = np.asarray(l_des).reshape(NUM_LEGS)

        delta = l_des - self.l_curr
        dl = np.abs(delta)
        dirs = np.sign(delta).astype(int)
        dirs[dl < 1e-9] = 0

        times_s = dl / VMAX
        times_s[dl < 1e-9] = 0.0
        t_max = np.max(times_s) if np.any(dl >= 1e-9) else 0.0
        times_ms = np.round(times_s * 1000).astype(int)

        print("Move dirs:", dirs)
        print("Move times (ms):", times_ms)
        print(f"Total move time: {t_max:.3f} s\n")

        # PREPARE each ECU (same pairing logic as FullSystemPPECU, but over CAN)
        for ecu_idx, (leg_a, leg_b) in enumerate(PAIRING):
            d1 = int(dirs[leg_a])
            d2 = int(dirs[leg_b])
            t1 = int(times_ms[leg_a])
            t2 = int(times_ms[leg_b])
            self._send_prepare_for_ecu(ecu_idx, d1, t1, d2, t2)

        if not self._wait_all_status(STATUS_PREPARED, timeout_s=2.0):
            print("ERROR: not all ECUs PREPARED")
            return

        # START broadcast
        self._send_start_broadcast()

        if not self._wait_all_status(STATUS_DONE, timeout_s=t_max + 5.0):
            print("ERROR: not all ECUs DONE")
            return

        # Update current lengths
        prev_l = self.l_curr.copy()
        self.l_curr[:] = l_des[:]

        # Optional: trajectory logging (same style as in FullSystemPPECU)
        if t_max > 0:
            with open("stewart_trajectory_can.txt", "a") as fp:
                fp.write("--- Bang-bang trajectory (6 legs, CAN) ---\n")
                fp.write("t")
                for i in range(NUM_LEGS):
                    fp.write(f"\tL{i+1}")
                fp.write("\n")

                n_steps = int(t_max / dt) + 10
                for step in range(n_steps):
                    t = step * dt
                    if t > t_max + 1.0:
                        break
                    line = f"{t:.2f}"
                    for i in range(NUM_LEGS):
                        if dirs[i] == 0 or times_s[i] == 0:
                            pos = prev_l[i]
                        else:
                            if t >= times_s[i]:
                                pos = l_des[i]
                            else:
                                pos = prev_l[i] + dirs[i] * VMAX * t * dirs[i]
                        line += f"\t{pos:.6f}"
                    fp.write(line + "\n")

            print("Trajectory logged to stewart_trajectory_can.txt\n")