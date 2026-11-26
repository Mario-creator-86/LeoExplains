"""The contact sheet of a review: the WHOLE clip, the last frame included.

    python review_sheet.py v119/short.mp4            -> writes v119/short.mp4.review.jpg
    python review_sheet.py v46/video.mp4 --step 10   -> a long video, a still every 10 s

22.11.2026, the channel agent: the sheets of the review of v119 had 18 stills that ended near second 15
of a 32-second clip, and the review said PASS and described a last scene nobody had seen («un PASS poate
trece cu jumătate de clip nevăzut, ca la v108 pe 15.11 și acum la v119»). Each review run had built the
sheet with an ffmpeg command of its own. This script builds it the same way every time:

  - a still for every second from 0 to the end (clips up to 90 s; longer ones: every 5 s after the
    first 10 s, or --step N), each with its second written on it;
  - the last frame of the file always, marked END;
  - a second file, <file>.end.jpg: the last frame alone, larger, to judge the ending on.

Its last line says what the sheet covers:

    SHEET: 34 stills, 0.0-32.1 s of 32.1 s, last frame included -> v119/short.mp4.review.jpg

It reads the video and writes only those two pictures.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CELL_W = 270
COLS = 8
PAD = 4
END_W = 720


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,nb_frames,r_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, check=True, text=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return float(j["format"]["duration"]), int(s["width"]), int(s["height"]), float(num) / float(den)


def still(path, t, w, h):
    """One frame at second t, as an RGB image of w x h; None when ffmpeg gives nothing there."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-an",
                          "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if len(out) < w * h * 3:
        return None
    return Image.frombytes("RGB", (w, h), out[:w * h * 3])


def last_frame(path, dur, fps, w, h):
    """The last frame that can be decoded: step back from the end until ffmpeg returns one."""
    step = 1.0 / max(fps, 1.0)
    t = dur - step
    for _ in range(40):
        if t < 0:
            break
        im = still(path, t, w, h)
        if im is not None:
            return im, t
        t -= step
    return None, None


def font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def label(im, text, f):
    d = ImageDraw.Draw(im)
    box = d.textbbox((0, 0), text, font=f)
    d.rectangle([0, 0, box[2] + 10, box[3] + 8], fill=(0, 0, 0))
    d.text((5, 3), text, font=f, fill=(255, 255, 0))
    return im


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    path = Path(argv[0])
    step = None
    if "--step" in argv:
        step = float(argv[argv.index("--step") + 1])
    if not path.exists():
        print(f"SHEET: FAILED, no such file: {path}")
        return 1
    dur, vw, vh, fps = probe(path)
    h = int(round(CELL_W * vh / vw / 2) * 2)
    if step:
        times = [float(t) for t in range(0, 10)] + [10 + i * step for i in range(int(max(0, dur - 10) // step) + 1)]
    elif dur <= 90:
        times = [float(t) for t in range(0, int(math.floor(dur)) + 1)]
    else:
        times = [float(t) for t in range(0, 10)] + [10.0 + i * 5 for i in range(int((dur - 10) // 5) + 1)]
    times = [t for t in times if t < dur - 0.05]
    f = font(20)
    cells, missing = [], []
    for t in times:
        im = still(path, t, CELL_W, h)
        if im is None:
            missing.append(t)
            continue
        cells.append(label(im, f"{t:.0f}s", f))
    end, end_t = last_frame(path, dur, fps, CELL_W, h)
    if end is None:
        print(f"SHEET: FAILED, the last frame of {path} cannot be read (duration {dur:.1f} s)")
        return 1
    cells.append(label(end, f"END {end_t:.1f}s", f))
    rows = math.ceil(len(cells) / COLS)
    sheet = Image.new("RGB", (COLS * CELL_W + (COLS + 1) * PAD, rows * h + (rows + 1) * PAD), (128, 128, 128))
    for i, im in enumerate(cells):
        sheet.paste(im, (PAD + (i % COLS) * (CELL_W + PAD), PAD + (i // COLS) * (h + PAD)))
    out = path.with_name(path.name + ".review.jpg")
    sheet.save(out, quality=85)
    eh = int(round(END_W * vh / vw / 2) * 2)
    big = still(path, end_t, END_W, eh)
    end_out = path.with_name(path.name + ".end.jpg")
    if big is not None:
        label(big, f"END {end_t:.1f}s of {dur:.1f}s", font(28)).save(end_out, quality=90)
    if missing:
        print("no still at: " + ", ".join(f"{t:.0f}s" for t in missing))
    print(f"last frame alone: {end_out}" if big is not None else "last frame alone: not written")
    print(f"SHEET: {len(cells)} stills, 0.0-{end_t:.1f} s of {dur:.1f} s, last frame included -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
