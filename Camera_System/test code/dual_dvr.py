import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
 
import cv2
import threading
from getpass import getpass
from urllib.parse import quote
 
IP = "192.168.1.10"
USERNAME = "kafa"
PASSWORD = "58r7ec"
 
credentials = (
    f"{quote(USERNAME, safe='')}:"
    f"{quote(PASSWORD, safe='')}"
)
 
# Replace with your confirmed working channel paths
CHANNELS = {
    "Channel 1": "/Streaming/Channels/101",
    "Channel 2": "/cam/realmonitor?channel=2&subtype=0"
}

class CameraStream:
    def __init__(self, name, path):
        self.name = name
        self.url = f"rtsp://{credentials}@{IP}:554{path}"
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self.frame = None
        self.running = self.cap.isOpened()
        self.lock = threading.Lock()
 
        if self.running:
            self.thread = threading.Thread(
                target=self.update, daemon=True
            )
            self.thread.start()
        else:
            print(f"Failed to connect: {name}")
 
    def update(self):
        while self.running:
            ret, frame = self.cap.read()
 
            if not ret:
                self.running = False
                break
 
            with self.lock:
                self.frame = frame
 
    def read(self):
        with self.lock:
            return self.frame
 
    def stop(self):
        self.running = False
        self.cap.release()
 
cameras = [
    CameraStream(name, path)
    for name, path in CHANNELS.items()
]
 
try:
    while True:
        for camera in cameras:
            frame = camera.read()
 
            if frame is not None:
                cv2.imshow(camera.name, frame)
 
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
 
finally:
    for camera in cameras:
        camera.stop()
 
    cv2.destroyAllWindows()