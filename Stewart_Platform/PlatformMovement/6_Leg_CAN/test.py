from can_adapter import recv_can_frame

while True:
    frame = recv_can_frame(timeout=1.0)
    if frame is None:
        print("No frame")
    else:
        cid, data = frame
        print(f"RX: ID=0x{cid:03X}, data={list(data)}")