import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
 
import cv2
import threading
import time
from getpass import getpass
from urllib.parse import quote
 
# ---------------- CONFIGURATION ----------------
 
DVR_IP = "192.168.1.10"
POE_IP = "192.168.1.172"
 
DVR_USER = input("DVR username [kafa]: ") or "kafa"
DVR_PASS = getpass("DVR password: ")
 
POE_USER = input("PoE username [admin]: ") or "admin"
POE_PASS = getpass("PoE password: ")
 
def rtsp_url(ip, username, password, path):
    user = quote(username, safe="")
    pwd = quote(password, safe="")
    return f"rtsp://{user}:{pwd}@{ip}:554{path}"
 
CAMERAS = {
    "Internal Camera 1": rtsp_url(
        DVR_IP, DVR_USER, DVR_PASS,
        "/Streaming/Channels/101"
    ),
    "Internal Camera 2": rtsp_url(
        DVR_IP, DVR_USER, DVR_PASS,
        "/cam/realmonitor?channel=2&subtype=0"
    ),
    "External PoE Camera": rtsp_url(
        POE_IP, POE_USER, POE_PASS,
        "/stream1"
    )
}
 
# ---------------- CAMERA STREAM ----------------
 
class CameraStream:
    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
 
        self.thread = threading.Thread(
            target=self.update,
            daemon=True
        )
        self.thread.start()
 
    def update(self):
        while self.running:
            cap = cv2.VideoCapture(
                self.url, cv2.CAP_FFMPEG
            )
 
            if not cap.isOpened():
                print(f"{self.name}: connection failed")
                cap.release()
                self.connected = False
                time.sleep(2)
                continue
 
            self.connected = True
            print(f"{self.name}: connected")
 
            while self.running:
                ret, frame = cap.read()
 
                if not ret:
                    break
 
                with self.lock:
                    self.frame = frame
 
            cap.release()
            self.connected = False
 
            with self.lock:
                self.frame = None
 
            if self.running:
                print(f"{self.name}: reconnecting...")
                time.sleep(1)
 
    def read(self):
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()
 
    def stop(self):
        self.running = False
 
# ---------------- DISPLAY ----------------
 
WIDTH = 640
HEIGHT = 360
 
def make_panel(name, frame, connected):
    if frame is None:
        panel = __import__("numpy").zeros(
            (HEIGHT, WIDTH, 3), dtype="uint8"
        )
        status = "Connecting..." if not connected else "Waiting for frame"
    else:
        panel = cv2.resize(frame, (WIDTH, HEIGHT))
        status = "LIVE"
 
    cv2.rectangle(
        panel, (0, 0), (WIDTH, 42),
        (25, 25, 25), -1
    )
 
    cv2.putText(
        panel, f"{name} - {status}",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65, (255, 255, 255), 2
    )
 
    return panel
 
streams = [
    CameraStream(name, url)
    for name, url in CAMERAS.items()
]
 
import numpy as np
 
selected = 0
 
try:
    while True:
        panels = [
            make_panel(
                stream.name,
                stream.read(),
                stream.connected
            )
            for stream in streams
        ]
 
        if selected == 0:
            # Three feeds in one horizontal dashboard
            dashboard = np.hstack(panels)
        else:
            # Enlarge the selected camera
            dashboard = cv2.resize(
                panels[selected - 1],
                (1280, 720)
            )
 
        cv2.imshow("MBEST Camera Monitoring", dashboard)
 
        key = cv2.waitKey(1) & 0xFF
 
        if key == ord("q"):
            break
        elif key == ord("0"):
            selected = 0
        elif key in [ord("1"), ord("2"), ord("3")]:
            selected = key - ord("0")
 
finally:
    for stream in streams:
        stream.stop()
 
    cv2.destroyAllWindows()