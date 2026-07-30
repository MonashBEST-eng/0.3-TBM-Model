import threading

import can

from can_interface import ODriveCAN
from commands import input_thread_fn
from controller import MotorController


def main():
    odrive = ODriveCAN()

    try:
        odrive.setup_idle()

        input_thread = threading.Thread(
            target=input_thread_fn,
            daemon=True,
        )
        input_thread.start()

        controller = MotorController(odrive)
        controller.run()

    except KeyboardInterrupt:
        odrive.hard_stop()

    except TimeoutError as error:
        print(f"Sync setup failed: {error}")
        odrive.hard_stop()

    except can.CanError as error:
        print(f"CAN error: {error}")
        odrive.hard_stop()

    finally:
        odrive.shutdown()
        print("CAN bus shutdown.")


if __name__ == "__main__":
    main()
