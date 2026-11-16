import subprocess


RTSP_URL = "rtsp://192.168.1.172:554/stream1"


def main():
    subprocess.run(
        [
            r"C:\Users\Chani\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-essentials_build\bin\ffplay.exe",
            "-window_title", "MBEST PoE Camera",
            "-rtsp_transport", "tcp",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-framedrop",
            "-noinfbuf",
            "-an",
            "-threads:v", "1",
            RTSP_URL,
        ],
        check=True,
    )


if __name__ == "__main__":
    main()