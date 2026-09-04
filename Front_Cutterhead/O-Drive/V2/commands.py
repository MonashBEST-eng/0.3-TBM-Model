import queue


command_queue = queue.Queue()


def print_help():
    print(
        "\nCommands:\n"
        "  start         Start at cruise velocity\n"
        "  stop          Ramp down, then set axes to idle\n"
        "  speed <value> Set target speed in turns/s\n"
        "  +             Increase target speed\n"
        "  -             Decrease target speed\n"
        "  quit          Stop motors and exit\n"
    )


def input_thread_fn():
    print_help()

    while True:
        try:
            line = input().strip().lower()
        except EOFError:
            break

        if line:
            command_queue.put(line)
