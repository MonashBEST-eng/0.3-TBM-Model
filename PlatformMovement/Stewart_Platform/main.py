import numpy as np
from controller import StewartController
from kinematics import computeLegs  # your 6-leg IK

def main():
    controller = StewartController()

    while True:
        cmd = input("\n'L' = lengths, 'P' = pose, 'Q' = quit: ").strip().upper()

        if cmd == 'Q':
            break

        elif cmd == 'L':
            vals = list(map(float, input("Enter 6 lengths (m): ").split()))
            if len(vals) != 6:
                print("Need 6 numbers.")
                continue
            l_des = np.array(vals)
            controller.send_bangbang_move(l_des)

        elif cmd == 'P':
            vals = list(map(float, input("x y z (m) psi theta phi (deg): ").split()))
            if len(vals) != 6:
                print("Need 6 numbers.")
                continue
            x, y, z, psi_deg, theta_deg, phi_deg = vals
            pos = np.array([x, y, z])
            l_des = computeLegs(
                pos,
                np.deg2rad(phi_deg),
                np.deg2rad(theta_deg),
                np.deg2rad(psi_deg),
            )
            print("Computed lengths:", l_des)
            controller.send_bangbang_move(l_des)

        else:
            print("Unknown command.")

if __name__ == "__main__":
    main()
