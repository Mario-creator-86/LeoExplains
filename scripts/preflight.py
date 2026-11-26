"""Mandatory check before ANY upload (owner 2026-11-04: "Cum poti sa publici ceva fara sa verifici?").

A compilation went up (private, scheduled) with its first 2:40 black because of a wrong ffmpeg filter. Nobody saw it,
but nothing may reach a platform again without these checks:
  - video and audio streams exist, the size is what the platform expects;
  - no black stretch longer than 1.0 s (ffmpeg blackdetect) and no frozen picture longer than 8 s (freezedetect);
  - no silent stretch longer than 6 s (silencedetect) in a narrated video;
  - a contact sheet <video>_preflight.png (one frame every N s) is written, and the uploader prints its path. It
    must be LOOKED AT before the upload is confirmed.
Upload scripts call check(path) and refuse to upload when it fails.

usage: <py> preflight.py <video.mp4> [--short] [--silent-ok]
--silent-ok (2026-11-04) only for the TikTok comic videos (comic_short.py --tiktok), which are silent by design
(the sound is added in TikTok's editor); it skips the silence check, every other check still runs.
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def run(args):
    return subprocess.run(args, capture_output=True, text=True)


def check(path, short=False, silent_ok=False):
    path = Path(path)
    problems = []
    pr = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                         "-of", "json", str(path)]).stdout or "{}")
    streams = pr.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(pr.get("format", {}).get("duration", 0))
    if not v:
        problems.append("no video stream")
    if not a and not silent_ok:
        problems.append("no audio stream")
    if v and short and (v["width"], v["height"]) != (1080, 1920):
        problems.append(f"vertical cut is {v['width']}x{v['height']}, expected 1080x1920")
    log = run(["ffmpeg", "-nostats", "-i", str(path), "-vf", "blackdetect=d=1.0:pic_th=0.97,freezedetect=n=0.001:d=8",
               "-af", "silencedetect=n=-45dB:d=6", "-f", "null", "-"]).stderr
    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", log):
        problems.append(f"black {float(m.group(1)):.1f}-{float(m.group(2)):.1f}s")
    for m in re.finditer(r"freeze_start: ([\d.]+)", log):
        problems.append(f"frozen picture from {float(m.group(1)):.1f}s")
    for m in re.finditer(r"silence_start: ([\d.]+)", log):
        t = float(m.group(1))
        if t < dur - 7 and not silent_ok:    # the calm music-only tail at the end is fine
            problems.append(f"silence from {t:.1f}s")
    # EVERY frame's brightness (owner 2026-11-04: "Te rog sa te uiți la toate cadrele din video! Toate!"):
    # fail when more than 6 frames (~0.2 s) are nearly black, wherever they are
    stats = run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                 "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"]).stdout
    yavg = [float(x) for x in re.findall(r"YAVG=([\d.]+)", stats)]
    dark = [i for i, y in enumerate(yavg) if y < 16]
    if len(dark) > 6:
        problems.append(f"{len(dark)} nearly black frames (first at frame {dark[0]}, {dark[0] / 30:.1f}s)")
    sheet = path.with_name(path.stem + "_preflight.png")
    step = 3 if dur < 120 else 10
    n = int(dur // step) + 1
    cols = 6 if short else 10
    scale = "180:320" if short else "240:135"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
         f"fps=1/{step},scale={scale},tile={cols}x{-(-n // cols)}:padding=3:color=gray", "-frames:v", "1", str(sheet)])
    ok = not problems
    hold = held(path)
    print(json.dumps({"file": str(path), "duration": round(dur, 2), "ok": ok, "problems": problems,
                      "frames_checked": len(yavg), "darkest_frame_yavg": round(min(yavg), 1) if yavg else None,
                      "sheet": str(sheet), "post_allowed": ok and not hold, **({"hold": hold} if hold else {}),
                      "next": ("DO NOT POST: the episode is on hold (release_order.json). The render check itself is 'ok'."
                               if hold else "LOOK AT THE SHEET before confirming the upload")}, indent=1))
    return ok


# 2026-11-08: v57 went public on TikTok while release_order.json held it (the review had scenes and title RED), from a copy
# re-encoded for the upload. Every upload runs this check first, so a held episode now stops here, before any platform.
def held(path):
    here = Path(__file__).resolve().parent
    try:
        rel = Path(path).resolve().relative_to(here)
    except ValueError:
        return None
    ep = next((p for p in rel.parts if re.fullmatch(r"v\d+", p)), None)
    order_file = here / "release_order.json"
    if not ep or not order_file.exists():
        return None
    order = json.loads(order_file.read_text(encoding="utf-8-sig"))
    day = order.get("hold_until", {}).get(ep)
    import datetime as dt
    if day and dt.date.today().isoformat() < day:
        return {"episode": ep, "until": day, "why": str(order.get("why", {}).get(ep, ""))[:200]}
    return None


if __name__ == "__main__":
    good = check(sys.argv[1], "--short" in sys.argv, "--silent-ok" in sys.argv)
    sys.exit(3 if good and held(sys.argv[1]) else 0 if good else 1)
