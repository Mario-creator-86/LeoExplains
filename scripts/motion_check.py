"""Does the picture of a rendered clip shake?  python motion_check.py v108/short.mp4 [--json]

Nobody in the production line watches a clip in motion: the critic, the review and the channel agent
look at stills. On 15.11.2026 a Short went out with a camera shake on eight shots and the Owner saw it
first («TREMURA IMAGINEA», «pune regulă că nu avem voie să facem așa ceva»). This script measures what
stills cannot show: how far the whole picture moves from one frame to the next (phase correlation on a
grey, half-size copy of every frame), and whether that movement keeps changing direction.

A smooth push or pan moves the picture by almost the same amount every frame, so the CHANGE of the
movement from one frame to the next is close to zero. A shake reverses the movement again and again,
many times a second. The script reports, for every second, the median change in pixels of the
1080-wide frame, the share of frames above the limit and how many times the movement turned round
(r), and ends with one line:

    MOTION: steady                      -> no second of the clip shakes
    MOTION: SHAKE at 0.0-6.9s, ...      -> the picture shakes there; the file must not be posted

A second shakes when all three are true: the median change is above LIMIT, enough of its frames are
above it, and the movement turned round at least REV_MIN times. The third is what tells a camera shake
from something drawn that sways: in v108 scene 3 a cat tower wobbles slowly in a motion clip (the
movement turns round two or three times a second, on purpose), while the "shake" of the edit turned
round more than ten times a second. So a slow sway of the drawing is NOT reported: this measures a
tremble of the picture, nothing else.

Tried on 15.11.2026 on a file known to shake and on files known to be smooth before it was trusted
(see the numbers in HANDOFF.md of the program). It reads the file and writes nothing.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 540, 960            # analysis size (half of 1080x1920)
TOP, BOTTOM = 0.06, 0.60   # rows used: above the captions, below a title at the very top
LIMIT = 1.0                # px of the 1080-wide frame: median change of movement in a second
SHARE = 0.35               # ... and at least this share of the second's frames above LIMIT
REV_MIN = 6                # ... and the movement turns round at least this many times in the second
REV_PX = 0.7               # a turn counts only when both movements are longer than this (px of 1080)
PEAK_MIN = 0.08            # a weaker correlation peak is a cut or a dissolve: no measurement


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, check=True, text=True).stdout
    j = json.loads(out)
    num, den = j["streams"][0]["r_frame_rate"].split("/")
    return float(num) / float(den), float(j["format"]["duration"]), j["streams"][0]["width"]


def frames(path):
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                             f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                            stdout=subprocess.PIPE)
    size = W * H
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(H, W)
    proc.stdout.close()
    proc.wait()


def shift(a, b, win):
    """Movement of the whole picture from a to b, in analysis pixels (dx, dy), and the peak height."""
    fa, fb = np.fft.rfft2(a * win), np.fft.rfft2(b * win)
    cross = fa * np.conj(fb)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=a.shape)
    py, px = np.unravel_index(np.argmax(corr), corr.shape)
    peak = float(corr[py, px])

    def sub(line, p, n):   # parabola through the peak and its two neighbours
        l, c, r = line[(p - 1) % n], line[p], line[(p + 1) % n]
        d = l - 2 * c + r
        return 0.0 if abs(d) < 1e-12 else 0.5 * (l - r) / d

    dy = py + sub(corr[:, px], py, corr.shape[0])
    dx = px + sub(corr[py, :], px, corr.shape[1])
    if dy > corr.shape[0] / 2:
        dy -= corr.shape[0]
    if dx > corr.shape[1] / 2:
        dx -= corr.shape[1]
    return dx, dy, peak


def measure(path):
    fps, dur, width = probe(path)
    r0, r1 = round(H * TOP), round(H * BOTTOM)
    win = np.outer(np.hanning(r1 - r0), np.hanning(W)).astype(np.float32)
    scale = 1080 / W
    prev, moves = None, []       # moves[k]: (dx, dy) in px of the 1080 frame from frame k to k+1, or None
    for fr in frames(path):
        cur = fr[r0:r1].astype(np.float32)
        cur -= cur.mean()
        if prev is not None:
            dx, dy, peak = shift(prev, cur, win)
            moves.append((dx * scale, dy * scale) if peak >= PEAK_MIN else None)
        prev = cur
    change = []                  # change[k]: |move[k+1] - move[k]|, or None across a cut
    for a, b in zip(moves, moves[1:]):
        change.append(None if a is None or b is None else float(np.hypot(b[0] - a[0], b[1] - a[1])))
    turn = []                    # turn[k]: the movement turned round between pair k and pair k+1
    for a, b in zip(moves, moves[1:]):
        turn.append(a is not None and b is not None and a[0] * b[0] + a[1] * b[1] < 0
                    and np.hypot(*a) > REV_PX and np.hypot(*b) > REV_PX)
    per = max(1, round(fps))
    seconds = []
    for s in range(0, len(change), per):
        vals = [v for v in change[s:s + per] if v is not None]
        rev = int(sum(turn[s:s + per]))
        if len(vals) < per // 3:
            seconds.append({"s": s // per, "frames": len(vals), "median": None, "share": None, "turns": rev,
                            "shake": False})
            continue
        med = float(np.median(vals))
        share = sum(1 for v in vals if v > LIMIT) / len(vals)
        seconds.append({"s": s // per, "frames": len(vals), "median": round(med, 2), "share": round(share, 2),
                        "turns": rev, "shake": med > LIMIT and share >= SHARE and rev >= REV_MIN})
    return {"file": str(path), "fps": round(fps, 3), "seconds_long": round(dur, 2), "seconds": seconds,
            "measured_pairs": sum(1 for m in moves if m is not None), "pairs": len(moves)}


def spans(seconds):
    out, start = [], None
    for row in seconds + [{"s": None, "shake": False}]:
        if row["shake"] and start is None:
            start = row["s"]
        if not row["shake"] and start is not None:
            end = seconds[-1]["s"] + 1 if row["s"] is None else row["s"]
            out.append((start, end))
            start = None
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    path = Path(args[0])
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    res = measure(path)
    bad = spans(res["seconds"])
    res["verdict"] = "shake" if bad else "steady"
    res["shake_at"] = [f"{a}-{b}s" for a, b in bad]
    if "--json" in sys.argv:
        print(json.dumps(res))
        return
    print(f"{path}: {res['seconds_long']} s, {res['fps']} fps, {res['measured_pairs']} of {res['pairs']} "
          "frame pairs measured (the rest are cuts or dissolves)")
    print("second: median change of movement in px (share of frames above the limit) r = turns of the movement")
    line = []
    for row in res["seconds"]:
        cell = "  -  " if row["median"] is None else f"{row['median']:.1f}({round(row['share'] * 100)}%)r{row['turns']}"
        line.append(f"{row['s']:>2}:{cell}{'!' if row['shake'] else ' '}")
    for i in range(0, len(line), 6):
        print("  " + "  ".join(line[i:i + 6]))
    if bad:
        print("MOTION: SHAKE at " + ", ".join(res["shake_at"]) + " -> the picture shakes there; "
              "this file must not be posted (fixed rule of the Owner, 15.11.2026)")
        sys.exit(2)
    print("MOTION: steady")


if __name__ == "__main__":
    main()
