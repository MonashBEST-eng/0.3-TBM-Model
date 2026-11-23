# camera_streams.py
#
# Background RTSP camera capture for the Dashboard's camera feed panels.
#
# Lifted from the team's standalone cameras_multiview.py test script and
# adapted to run inside the Tk app: instead of owning its own cv2.imshow
# loop, CameraStream just keeps grabbing frames on a background thread, and
# dashboard_panel.py pulls the latest one on a timer, converts it to a
# Tk-displayable image, and draws it onto the feed Canvas.
#
# Needs: opencv-python (cv2), numpy, Pillow (PIL) — Pillow is already used
# elsewhere in this app (splash_panel.py). If cv2 isn't installed, this
# module degrades gracefully: start_all()/get_stream() become no-ops and
# the Dashboard just keeps showing its placeholder graphics.
#
# NOTE ON CREDENTIALS: the DVR/PoE camera login below came from the
# original cameras_multiview.py test script. It's read from settings_store
# (-> ~/.tbm_gui_settings.json on each machine) rather than hardcoded here,
# but the *default* values still originate from that script, so the same
# DVR password that was pasted into this chat is now the default for every
# machine running this file until someone changes it. Worth rotating that
# camera password and/or changing it in settings once this is on real
# hardware — this file is shared/visible to the whole team via the Project.

import os

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import threading
import time
from urllib.parse import quote

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

import GUI_menus.settings_store as settings_store

# =========================
# GUIDELINE REMOVAL
# Verbatim logic from cameras_multiview.py — paints over the DVR's
# on-screen green/yellow/red guide markings so they don't clutter the feed.
# Only cameras flagged supports_guideline_removal=True use this.
# =========================
_mask_cache = {}


def _create_guideline_mask(frame):
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    reference_width = 1644
    reference_height = 878

    segments = [
        # Left green
        [(645, 463), (580, 463), (565, 472)],
        [(550, 499), (516, 511)],
        # Left yellow
        [(499, 537), (464, 551)],
        [(447, 582), (408, 600)],
        [(491, 625), (380, 625), (350, 647)],
        # Left red
        [(331, 678), (279, 713)],
        [(390, 745), (253, 745), (183, 821)],
        # Right green
        [(1002, 463), (1064, 463), (1085, 473)],
        [(1104, 499), (1132, 511)],
        # Right yellow
        [(1158, 537), (1190, 551)],
        [(1210, 582), (1244, 600)],
        [(1164, 625), (1270, 625), (1300, 647)],
        # Right red
        [(1320, 678), (1370, 713)],
        [(1260, 745), (1400, 745), (1480, 828)],
    ]

    thickness = max(3, int(40 * w / reference_width))

    for segment in segments:
        points = np.array(
            [(int(x * w / reference_width), int(y * h / reference_height)) for x, y in segment],
            dtype=np.int32,
        )
        cv2.polylines(mask, [points], False, 255, thickness)

    return mask


def remove_guidelines(frame, camera_index):
    h, w = frame.shape[:2]
    key = (camera_index, h, w)

    if key not in _mask_cache:
        _mask_cache[key] = _create_guideline_mask(frame)

    kernel = np.ones((7, 7), np.uint8)
    region = cv2.dilate(_mask_cache[key], kernel, iterations=2)

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, (0, 100, 50), (12, 255, 255))
    red2 = cv2.inRange(hsv, (165, 100, 50), (179, 255, 255))
    yellow = cv2.inRange(hsv, (15, 100, 50), (40, 255, 255))
    green = cv2.inRange(hsv, (40, 100, 50), (90, 255, 255))
    colours = red1 | red2 | yellow | green

    mask = cv2.bitwise_and(colours, region)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    return cv2.inpaint(frame, mask, 2, cv2.INPAINT_TELEA)


# =========================
# CAMERA SOURCE CONFIG
# Connection info lives in settings_store (-> ~/.tbm_gui_settings.json),
# not hardcoded here. See the credentials note at the top of this file.
# =========================
def _rtsp_url(ip, username, password, path):
    user = quote(username or "", safe="")
    pwd = quote(password or "", safe="")
    return f"rtsp://{user}:{pwd}@{ip}:554{path}"


def get_camera_sources():
    """Returns an ordered list of (name, url, supports_guideline_removal)
    for the 3 feeds shown on the Dashboard."""
    dvr_ip = settings_store.get("cameras", "dvr_ip", default="192.168.1.10")
    dvr_user = settings_store.get("cameras", "dvr_user", default="")
    dvr_pass = settings_store.get("cameras", "dvr_pass", default="")
    poe_ip = settings_store.get("cameras", "poe_ip", default="192.168.1.172")
    poe_user = settings_store.get("cameras", "poe_user", default="")
    poe_pass = settings_store.get("cameras", "poe_pass", default="")

    return [
        ("CAMERA 1  —  Forward View",
         _rtsp_url(dvr_ip, dvr_user, dvr_pass, "/Streaming/Channels/101"), True),
        ("CAMERA 2  —  Cutterhead View",
         _rtsp_url(dvr_ip, dvr_user, dvr_pass, "/cam/realmonitor?channel=2&subtype=0"), True),
        ("CAMERA 3  —  External PoE",
         _rtsp_url(poe_ip, poe_user, poe_pass, "/stream1"), False),
    ]


def guideline_removal_enabled():
    return bool(settings_store.get("cameras", "guideline_removal", default=True))


# =========================
# CAMERA STREAM
# One background thread per camera; keeps the latest decoded frame behind
# a lock. Auto-reconnects on failure/disconnect — same retry behaviour as
# the original standalone cameras_multiview.py script.
# =========================
class CameraStream:
    def __init__(self, name, url, index, supports_guideline_removal):
        self.name = name
        self.url = url
        self.index = index
        self.supports_guideline_removal = supports_guideline_removal
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)

            if not cap.isOpened():
                cap.release()
                self.connected = False
                if self.running:
                    time.sleep(2)
                continue

            self.connected = True

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
                time.sleep(1)

    def read(self):
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def stop(self):
        self.running = False


# =========================
# STREAM MANAGER
# dashboard_panel.py calls start_all() when the Dashboard panel opens and
# stop_all() when it closes, so the RTSP connections (and the DVR/PoE load)
# only exist while someone is actually looking at the Dashboard.
# =========================
_streams = {}


def start_all():
    """Starts (or leaves running) all 3 camera streams. Safe to call
    repeatedly — no-ops for any stream already running, and does nothing
    at all if opencv-python isn't installed."""
    if not CV2_AVAILABLE:
        return
    for i, (name, url, supports_gr) in enumerate(get_camera_sources()):
        if name not in _streams:
            _streams[name] = CameraStream(name, url, i, supports_gr)


def stop_all():
    for stream in _streams.values():
        stream.stop()
    _streams.clear()


def get_stream(name):
    return _streams.get(name)
