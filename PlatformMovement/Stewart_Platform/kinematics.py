import numpy as np

# ========================= CONSTANTS =========================
NUM_LEGS = 6
dt = 0.1  # time resolution for logging (s)

L_min = 0.34
L_max = 0.5

VMAX = 0.006  # m/s - full actuator speed (used for bang-bang timing)

# Geometry (exact values from your original code)
r_p = 0.1563788
r_b = 0.1961415
h_b = 0.004
h_p_joints = 0.0
h_b_joints = 0.0

# ECU pairing - change only if you wire the legs differently
# ECU 0 controls legs 1-2 (indices 0-1), ECU 1 → 3-4, ECU 2 → 5-6
PAIRING = [(0,1), (2,3), (4,5)]

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
    """Inverse kinematics - returns 6 leg lengths (m) for given pose"""
    gamma_p_deg = np.array([22.4615, 97.5385, 142.4615, -97.5385, -142.4615, -22.4615])
    gamma_b_deg = np.array([20.62,   99.38,   140.62,   -99.38,   -140.62,   -20.62])

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