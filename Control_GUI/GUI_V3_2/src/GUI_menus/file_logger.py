# file_logger.py
#
# Minimal, dependency-free logger that appends every comms/control log line
# to outputs/system_log.txt, so the System Log panel (system_log_panel.py)
# has real persistent data to show/search/export — rather than relying on
# dashboard_panel.py's in-memory Text widgets, which only exist while the
# Dashboard panel happens to be open.
#
# Writes are BUFFERED rather than opening/closing the file on every single
# call: telemetry can arrive many times a second, and hitting disk that
# often adds needless I/O overhead and disk wear over a long test session.
# The buffer flushes automatically at most once per second, or immediately
# if forced (e.g. on app shutdown, so nothing buffered is ever lost).
#
# Line format matches what system_log_panel.py's parser expects:
#     [TAG] [HH:MM:SS] message
# e.g. [RX] [14:32:07] tbm/telemetry | TEMP_CUTTERHEAD:52.3

import os
import time
import atexit
import threading

LOG_DIR  = "outputs"
LOG_PATH = os.path.join(LOG_DIR, "system_log.txt")

_FLUSH_INTERVAL_SEC = 1.0

_buffer: list[str] = []
_lock = threading.Lock()
_last_flush = 0.0
_warned_once = False   # avoid spamming stderr if the disk/path is ever unwritable


def log_to_file(msg: str, tag: str = "info"):
    """Queue one line for the system log file. Cheap to call often — actual
    disk writes are batched, not done per-call."""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{tag.upper()}] [{timestamp}] {msg}\n"
    with _lock:
        _buffer.append(line)
    _maybe_flush()


def _maybe_flush(force: bool = False):
    global _last_flush
    now = time.time()
    if not force and (now - _last_flush) < _FLUSH_INTERVAL_SEC:
        return
    _flush()


def _flush():
    global _last_flush, _warned_once
    with _lock:
        if not _buffer:
            _last_flush = time.time()
            return
        pending = _buffer[:]
        _buffer.clear()

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.writelines(pending)
    except Exception as e:
        if not _warned_once:
            _warned_once = True
            print(f"[file_logger] Could not write to {LOG_PATH}: {e}")
    _last_flush = time.time()


def flush_now():
    """Force an immediate flush, bypassing the 1-second batching interval —
    used on app shutdown so nothing buffered is ever silently lost."""
    _maybe_flush(force=True)


# Guarantee buffered-but-unflushed lines make it to disk even if the app
# closes less than a second after its last log line.
atexit.register(flush_now)