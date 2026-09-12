"""Build the silent, looping README preview from the published code-rendered MP4."""
from pathlib import Path
import json
import subprocess
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/media/h3loom-intro.mp4"
DEST = ROOT / "docs/media/h3loom-intro.webp"
WIDTH, HEIGHT, FPS, COUNT = 800, 450, 24, 576


def main():
    frames = []
    command = ["ffmpeg", "-v", "error", "-i", str(SOURCE), "-an", "-vf",
               f"scale={WIDTH}:{HEIGHT}:flags=lanczos,fps={FPS}", "-f", "rawvideo",
               "-pix_fmt", "rgb24", "-"]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as decoder:
        while True:
            raw = decoder.stdout.read(WIDTH * HEIGHT * 3)
            if not raw:
                break
            if len(raw) != WIDTH * HEIGHT * 3:
                raise RuntimeError("Incomplete decoded frame")
            frames.append(Image.frombytes("RGB", (WIDTH, HEIGHT), raw))
        if decoder.wait() != 0:
            raise RuntimeError("FFmpeg decode failed")
    if len(frames) != COUNT:
        raise RuntimeError(f"Expected {COUNT} frames, received {len(frames)}")
    durations = [(i + 1) * 1000 // FPS - i * 1000 // FPS for i in range(COUNT)]
    temporary = DEST.with_suffix(".tmp.webp")
    frames[0].save(temporary, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, quality=76, method=4, lossless=False)
    with Image.open(temporary) as check:
        total = 0
        for i in range(check.n_frames):
            check.seek(i)
            check.load()
            total += check.info["duration"]
        if total != 24000 or check.info.get("loop") != 0:
            raise RuntimeError("Animation timing or loop mismatch")
        print(json.dumps({"frames":check.n_frames,"duration_ms":total,
                          "dimensions":[WIDTH,HEIGHT],"bytes":temporary.stat().st_size}))
    temporary.replace(DEST)


if __name__ == "__main__":
    main()
