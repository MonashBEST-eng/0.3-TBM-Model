import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
 
import cv2
import threading
import time
from getpass import getpass
from urllib.parse import quote
 
# ---------------- CONFIGURATION ----------------
# Default camera addresses. These are only defaults: the ground station
# can pass its own (e.g. from settings) into build_cameras() without
# editing this file.
 
DVR_IP = "192.168.1.10"
POE_IP = "192.168.1.172"
 
def rtsp_url(ip, username, password, path, port=554):
    user = quote(username, safe="")
    pwd = quote(password, safe="")
    return f"rtsp://{user}:{pwd}@{ip}:{port}{path}"
 
def build_cameras(dvr_user, dvr_pass, poe_user, poe_pass,
                  dvr_ip=DVR_IP, poe_ip=POE_IP):
    """Return {display name: RTSP URL} for all three cameras.
 
    Credentials (and optionally IPs) are injected by the caller rather
    than stored in this module: the standalone viewer prompts for them
    in main(), and the ground station supplies its own when it builds
    its CameraStream objects."""
    return {
        "Internal Camera 1": rtsp_url(
            dvr_ip, dvr_user, dvr_pass,
            "/Streaming/Channels/101"
        ),
        "Internal Camera 2": rtsp_url(
            dvr_ip, dvr_user, dvr_pass,
            "/cam/realmonitor?channel=2&subtype=0"
        ),
        "External PoE Camera": rtsp_url(
            poe_ip, poe_user, poe_pass,
            "/stream1"
        )
    }
 
# ---------------- CAMERA STREAM ----------------
 
class CameraStream:
    def __init__(self, name, url, on_status=print):
        """on_status is called with a short text message whenever the
        stream connects, fails or reconnects. Defaults to print() for the
        standalone viewer. NOTE: it is called from this stream's
        background thread, so a GUI must not touch Tk widgets inside it -
        push onto a queue (e.g. msg_queue) and update widgets from the
        Tk main thread instead."""
        self.name = name
        self.url = url
        self._on_status = on_status
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
                self._on_status(f"{self.name}: connection failed")
                cap.release()
                self.connected = False
                time.sleep(2)
                continue
 
            self.connected = True
            self._on_status(f"{self.name}: connected")
 
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
                self._on_status(f"{self.name}: reconnecting...")
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
 
# ---------------- STANDALONE VIEWER ----------------
# Only runs when this file is executed directly (python three_cameras.py).
# Importing this module defines rtsp_url / build_cameras / CameraStream /
# make_panel only - no prompts, no connections, no display loop.
 
def main():
    import numpy as np
 
    dvr_user = input("DVR username [kafa]: ") or "kafa"
    dvr_pass = getpass("DVR password: ")
 
    poe_user = input("PoE username [admin]: ") or "admin"
    poe_pass = getpass("PoE password: ")
 
    cameras = build_cameras(dvr_user, dvr_pass, poe_user, poe_pass)
 
    streams = [
        CameraStream(name, url)
        for name, url in cameras.items()
    ]
 
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
 
 
if __name__ == "__main__":
    main()