from main import StewartController, computeLegs
import numpy as np

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