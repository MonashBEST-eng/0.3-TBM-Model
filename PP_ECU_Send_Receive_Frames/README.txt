In order to run the following code:

1. Program the 0.3m PP-ECU board with the following STM32 Project
2. Hook up a USB-CAN to the De9 connector with wires, it will be pin 3 and 8
4. Open Waveshare USB-CAN-A software and configure the com baud rate to 115200 and the CAN Baud rate to 100kbps
5. Run transceiver.py and make sure you see RXD and TXD on the USB-CAN flash at least once.
6. You should see a message sent and a see the message be received in your terminal when you run the Python program.