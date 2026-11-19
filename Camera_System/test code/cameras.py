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
 
DVR_USER = "kafa"

DVR_PASS = "58r7ec"
 
POE_USER = ""

POE_PASS = ""
 
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

                if self.running:

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
 
streams = [

    CameraStream(name, url)

    for name, url in CAMERAS.items()

]
 
WINDOW = "MBEST Camera Monitoring"

cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

cv2.resizeWindow(WINDOW, 1280, 720)
 
selected = 0

fullscreen = False
 
print("\nCamera controls:")

print("1 - Internal Camera 1")

print("2 - Internal Camera 2")

print("3 - External PoE Camera")

print("F - Toggle fullscreen")

print("Q - Quit")
 
try:

    while True:

        camera = streams[selected]

        frame = camera.read()
 
        if frame is not None:

            display = frame.copy()
 
            # Display camera name

            cv2.rectangle(

                display,

                (0, 0),

                (display.shape[1], 55),

                (25, 25, 25),

                -1

            )
 
            cv2.putText(

                display,

                camera.name,

                (20, 38),

                cv2.FONT_HERSHEY_SIMPLEX,

                1,

                (255, 255, 255),

                2

            )
 
            cv2.imshow(WINDOW, display)
 
        key = cv2.waitKey(1) & 0xFF
 
        if key == ord("q"):

            break
 
        elif key in [ord("1"), ord("2"), ord("3")]:

            selected = key - ord("1")

            print(f"Switched to {streams[selected].name}")
 
        elif key == ord("f"):

            fullscreen = not fullscreen
 
            mode = (

                cv2.WINDOW_FULLSCREEN

                if fullscreen

                else cv2.WINDOW_NORMAL

            )
 
            cv2.setWindowProperty(

                WINDOW,

                cv2.WND_PROP_FULLSCREEN,

                mode

            )
 
finally:

    for camera in streams:

        camera.stop()
 
    cv2.destroyAllWindows()

 