import shutil
import subprocess
import time
from pathlib import Path


FFPLAY_FALLBACK = (
    Path.home()
    / "AppData/Local/Microsoft/WinGet/Packages"
    / "Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe"
    / "ffmpeg-9.0.1-essentials_build/bin/ffplay.exe"
)

POE_URL = "rtsp://192.168.1.172:554/stream1"
DVR_URL = (
    "rtsp://192.168.1.10:554/"
    "user=admin&password=&channel=1&stream=0.sdp?real_stream"
)
POE_LOG = Path(__file__).resolve().with_name("poe_ffplay.log")


def main():
    ffplay = shutil.which("ffplay")
    if ffplay is None:
        if not FFPLAY_FALLBACK.is_file():
            raise SystemExit("ffplay.exe not found. Check FFPLAY_FALLBACK in this script.")
        ffplay = str(FFPLAY_FALLBACK)

    feeds = [
        ("MBEST PoE Camera", POE_URL, "20"),
        ("MBEST Reversing Camera - CH1", DVR_URL, "650"),
    ]

    print(f"Using FFplay at {ffplay}", flush=True)
    print(f"PoE log saved to {POE_LOG}", flush=True)

    players = []
    with POE_LOG.open("w", encoding="utf-8") as poe_log:
        try:
            for title, url, left in feeds:
                command = [
                    ffplay,
                    "-rtsp_transport", "tcp",
                    "-window_title", title,
                    "-left", left,
                    "-top", "60",
                    "-x", "600",
                    url,
                ]
                player = subprocess.Popen(
                    command,
                    stderr=poe_log if url == POE_URL else None,
                )
                players.append(player)

            while any(player.poll() is None for player in players):
                time.sleep(0.2)

        except KeyboardInterrupt:
            pass

        finally:
            for player in players:
                if player.poll() is None:
                    player.terminate()
            for player in players:
                player.wait()


if __name__ == "__main__":
    main()