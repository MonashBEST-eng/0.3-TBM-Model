import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
 
import cv2
import time
from getpass import getpass
from urllib.parse import quote
 
IP = "192.168.1.10"
USERNAME = "kafa"
PASSWORD = "58r7ec"
 
# Use the RTSP path that worked previously
PATH = "/Streaming/Channels/101"
 
url = (
    f"rtsp://{quote(USERNAME, safe='')}:"
    f"{quote(PASSWORD, safe='')}@{IP}:554{PATH}"
)
 
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
 
if not cap.isOpened():
    raise RuntimeError("Cannot connect to DVR")
 
frames = 0
start = time.perf_counter()
 
print("Streaming started. Press Q to quit.")
 
while True:
    ret, frame = cap.read()
 
    if not ret:
        print("Failed to retrieve frame")
        break
 
    frames += 1
    elapsed = time.perf_counter() - start
 
    if elapsed >= 1:
        print(f"FPS: {frames / elapsed:.1f}")
        frames = 0
        start = time.perf_counter()
 
    cv2.imshow("MBEST DVR Live Feed", frame)
 
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break
 
cap.release()
cv2.destroyAllWindows()