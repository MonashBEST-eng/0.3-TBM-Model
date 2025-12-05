import numpy as np

# Constants from your script
NUM_LEGS = 6
L_min = 0.34
L_max = 0.5
r_p = 0.1563788
r_b = 0.1961415
h_b = 0.004
h_p_joints = 0.0
h_b_joints = 0.0

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

# Test cases
# Neutral pose: x=0, y=0, z=0.35 m, angles=0
neutral_pose = np.array([0.0, 0.0, 0.35])
l_neutral = computeLegs(neutral_pose, 0.0, 0.0, 0.0)
print("Neutral leg lengths (should all be ~0.3483 m):", l_neutral)

# Small translation: x=0.01 m
translated_pose = np.array([0.01, 0.0, 0.35])
l_trans = computeLegs(translated_pose, 0.0, 0.0, 0.0)
print("Translated leg lengths (mixed adjustments):", l_trans)

# Small roll: phi=5 degrees
l_roll = computeLegs(neutral_pose, np.deg2rad(5), 0.0, 0.0)
print("Roll leg lengths (asymmetric):", l_roll)

# Verify limits
if np.all((l_neutral >= L_min) & (l_neutral <= L_max)):
    print("All neutral lengths within [0.34, 0.5] m: PASS")
else:
    print("Lengths out of bounds: FAIL")

VMAX = 0.006  # m/s

# Simulate move from neutral to translated pose
l_curr = l_neutral.copy()
l_des = l_trans.copy()
delta = l_des - l_curr
dl = np.abs(delta)
dirs = np.sign(delta).astype(int)
dirs[dl < 1e-9] = 0
times_s = dl / VMAX
times_s[dl < 1e-9] = 0.0
t_max = np.max(times_s) if np.any(dl >= 1e-9) else 0.0
times_ms = np.round(times_s * 1000).astype(int)

print("Directions (should be mixed -1/0/1):", dirs)
print("Move times (ms):", times_ms)
print("Total move time (s):", t_max)