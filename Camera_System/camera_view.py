import os

# FFmpeg low-latency settings
# Must be configured before importing OpenCV
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|"
    "fflags;nobuffer|"
    "flags;low_delay|"
    "probesize;32768|"
    "analyzeduration;0"
)

import cv2
import threading
from getpass import getpass
from urllib.parse import quote

# Camera configuration
IP = "192.168.1.172"
PORT = 554

USERNAME = input("Camera username [admin]: ") or "admin"
PASSWORD = getpass("Camera password: ")

# Main stream: stream1
# Secondary stream: stream2
STREAM = "stream1"

RTSP_URL = (
    f"rtsp://{quote(USERNAME, safe='')}:"
    f"{quote(PASSWORD, safe='')}@"
    f"{IP}:{PORT}/{STREAM}"
)


class CameraStream:
    def __init__(self, url):
        self.cap = cv2.VideoCapture(
            url,
            cv2.CAP_FFMPEG
        )

        if not self.cap.isOpened():
            raise RuntimeError(
                "Failed to connect to camera"
            )

        # May be ignored by the FFmpeg backend
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.frame = None
        self.running = True
        self.lock = threading.Lock()

        self.thread = threading.Thread(
            target=self.update,
            daemon=True
        )
        self.thread.start()

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
        self.thread.join(timeout=2)
        self.cap.release()


def main():
    camera = CameraStream(RTSP_URL)

    print("Camera connected successfully!")
    print("Press Q to exit.")

    try:
        while camera.running:
            frame = camera.read()

            if frame is not None:
                cv2.imshow(
                    "MBEST - Low Latency PoE Camera",
                    frame
                )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
