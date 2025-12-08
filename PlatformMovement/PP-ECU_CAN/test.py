from can_adapter import send_can_frame

send_can_frame(0x123, b'\x11\x22\x33\x44')
print("Sent test frame")
