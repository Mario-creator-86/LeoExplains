"""A long YouTube video (8-15 min) from several finished episodes on one theme (2026-11-04: YouTube leans long, see
strategy/YT_LESSONS.md). Each part is the episode's video.mp4. Every part except the last is cut just before its
scene 40 (the "Subscribe to Leo Explains" line), so the call to subscribe comes once, at the very end. Parts join
with a short cross-fade. Writes <out>/video.mp4, <out>/chapters.txt and the chapter list for the description, then
runs preflight.py (black, frozen and silent checks + contact sheet), which must pass and must be LOOKED AT before
any upload. Use only episodes that passed the house-style review (stickmen only, no twist lead-ins).

usage: python compile_long.py c2 v41 v42 v40 v37
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "video_pipeline"))
from assemble import scene_starts  # noqa: E402
import preflight  # noqa: E402

XF = 0.5   # cross-fade between parts (s)


def probe(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(p)], capture_output=True, text=True).stdout)


def cut_point(vdir):
    """Video time where scene 40 (the subscribe line) starts."""
    data = json.loads((vdir / "scenes.json").read_text(encoding="utf-8"))
    scenes = [data[str(n)]["narration"] for n in range(1, len(data) + 1)]
    align = json.loads((vdir / "voiceover.alignment.json").read_text(encoding="utf-8"))
    starts = scene_starts(scenes, align)
    assert "subscribe" in scenes[-1].lower(), f"{vdir.name}: last scene is not the subscribe line"
    return starts[len(scenes) - 1] - 0.15


def main():
    out = HERE / sys.argv[1]
    parts = [HERE / v for v in sys.argv[2:]]
    out.mkdir(exist_ok=True)
    lens = []
    for k, v in enumerate(parts):
        full = probe(v / "video.mp4")
        lens.append(full if k == len(parts) - 1 else cut_point(v))
    inputs, chain, t, chapters = [], [], 0.0, []
    for k, (v, ln) in enumerate(zip(parts, lens)):
        inputs += ["-t", f"{ln:.3f}", "-i", str(v / "video.mp4")]
        title = json.loads((v / "meta.json").read_text(encoding="utf-8"))["title"].split("?")[0] + "?"
        chapters.append((t, title))
        t += ln - (XF if k < len(parts) - 1 else 0)
    # cross-fade chain
    vlab, alab = "[0:v]", "[0:a]"
    off = 0.0
    for k in range(1, len(parts)):
        off += lens[k - 1] - XF
        chain.append(f"{vlab}[{k}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{k}]")
        chain.append(f"{alab}[{k}:a]acrossfade=d={XF}[a{k}]")
        vlab, alab = f"[v{k}]", f"[a{k}]"
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", vlab, "-map", alab,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out / "video.mp4")]
    subprocess.run(cmd, check=True)
    lines = [f"{int(s // 60)}:{int(s % 60):02d} {name}" for s, name in chapters]
    (out / "chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("duration", round(probe(out / "video.mp4"), 2))
    ok = preflight.check(out / "video.mp4")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
