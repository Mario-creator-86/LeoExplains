"""Render one Leo series video without jitter.

Camera moves are computed in floating point and rendered with Pillow's bicubic affine transform
(sub-pixel), eased in/out, so there is no integer-step shake. Scenes cross-dissolve. When a scene
has a second pose (scene_NNb.*), the pose changes mid-scene with a short dissolve (limited
animation). Captions are burned with ffmpeg's subtitles filter; voice + calm music are mixed.

usage: render.py <vdir> [--music yal-calm-angels-dream] [--music-db -30] [--preview SECONDS]
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

W, H, FPS = 1920, 1080, 30
XFADE = 10          # frames of cross-dissolve between scenes
POSE_FADE = 2       # frames of dissolve between the two poses of a scene (near-snap, cartoon style)
CAPTION_STYLE = ("Style: Cap,Arial Black,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,"
                 "100,100,1,0,1,6,3,2,80,80,60,1")  # thick black outline + soft shadow, no box
TAIL = 4.6          # calm music-only end after the voice: ~3 s more room for the end screen (owner OK 2026-11-01)
SFX_TRIM_DB = -8.0  # every sound effect quieter on top of its sfx.json level (owner 2026-11-01: "mai incet").
#                    Since 23:00 the effects are also mixed AFTER loudnorm (sfx_after_loudnorm), so pauses no longer
#                    lift them: a spot effect now sits near -34 LUFS and an ambience near -41, under the -14 voice.
# music beds: <id>.mp3 files plus music_library.json next to them (not included in this repository)
MUSIC_DIR = Path(os.environ.get("LEO_MUSIC_DIR", str(Path(__file__).resolve().parents[1] / "music")))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video_pipeline"))
from assemble import captions, probe_duration, scene_starts  # noqa: E402


def ease(t):
    return t * t * (3 - 2 * t)


# Camera moves: (zoom_start, zoom_end, cx_start, cx_end, cy_start, cy_end), centers as fractions.
MOVES = [
    (1.00, 1.10, 0.50, 0.50, 0.50, 0.48),   # push in
    (1.10, 1.00, 0.50, 0.50, 0.48, 0.50),   # pull out
    (1.10, 1.10, 0.44, 0.56, 0.50, 0.50),   # pan right
    (1.12, 1.04, 0.56, 0.48, 0.50, 0.50),   # pull out drifting left
    (1.02, 1.12, 0.47, 0.53, 0.52, 0.47),   # push in, diagonal up
    (1.10, 1.10, 0.56, 0.44, 0.50, 0.50),   # pan left
]


def load(path):
    img = Image.open(path).convert("RGB")
    scale = max(W * 1.5 / img.width, H * 1.5 / img.height)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def frame(img, zoom, cx, cy):
    """Crop a W/zoom x H/zoom window centred at (cx, cy) (fractions), resampled sub-pixel."""
    sw, sh = img.size
    # window size in source pixels, keeping 16:9 and staying inside the image
    base = min(sw / W, sh / H)
    ww, wh = W * base / zoom, H * base / zoom
    x0 = min(max(cx * sw - ww / 2, 0), sw - ww)
    y0 = min(max(cy * sh - wh / 2, 0), sh - wh)
    a = ww / W
    e = wh / H
    return img.transform((W, H), Image.AFFINE, (a, 0, x0, 0, e, y0), resample=Image.BICUBIC)


def scene_frames(imgs, nframes, move):
    z0, z1, x0, x1, y0, y1 = move
    # poses A, B, C, ... each hold an equal share of the scene and snap to the next one with a
    # very short dissolve (limited animation)
    seg = nframes / len(imgs)
    for i in range(nframes):
        t = ease(i / max(1, nframes - 1))
        z, cx, cy = z0 + (z1 - z0) * t, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        p = min(len(imgs) - 1, int(i / seg))
        a = np.asarray(frame(imgs[p], z, cx, cy), dtype=np.float32)
        into = i - p * seg
        if p > 0 and into < POSE_FADE:
            prev = np.asarray(frame(imgs[p - 1], z, cx, cy), dtype=np.float32)
            k = (into + 1) / (POSE_FADE + 1)
            a = prev * (1 - k) + a * k
        yield a


def clip_frames(path, nframes):
    """Frames of an animated (Veo) clip filling the scene: sped up at most 1.5x when the clip is
    longer than the scene, last frame held when it is shorter."""
    dur = probe_duration(path)
    speed = min(1.5, max(1.0, dur / (nframes / FPS)))
    vf = (f"setpts=PTS/{speed:.4f},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H}")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", vf,
                          "-frames:v", str(nframes), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    for k in range(nframes):
        yield frames[min(k, len(frames) - 1)].astype(np.float32)


def load_sfx(vdir):
    """<vdir>/sfx.json, refusing any video that uses the same sound twice (owner rule 2026-11-01: every
    sound effect at most once per video). The same sound = the same file content, or the same name
    apart from a numbered suffix (footsteps / footsteps_2)."""
    f = vdir / "sfx.json"
    if not f.exists():
        return []
    sfx = json.loads(f.read_text(encoding="utf-8-sig"))
    seen, dup = {}, []
    for fx in sfx:
        path = (vdir / fx["file"]).resolve()
        name = re.sub(r"([_-]v?\d+)+$", "", path.stem.lower())
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        first = seen.get(name) or seen.get(digest)
        if first:
            dup.append(f"{fx['file']} (scene {fx['scene']}) repeats {first}")
        else:
            seen[name] = seen[digest] = f"{fx['file']} (scene {fx['scene']})"
    if dup:
        sys.exit("sfx.json uses the same sound more than once (owner rule: each sound at most once per "
                 "video):\n  " + "\n  ".join(dup)
                 + "\nReplace each repeat with a different sfx_library sound, or drop it.")
    return sfx


def sfx_after_loudnorm(base, effects, norm):
    """Filter-graph tail: voice + music are mixed and normalised with `norm` FIRST, and the effects are
    added AFTER it, then a limiter. Normalising everything together let loudnorm's dynamic mode lift
    the effects in every pause of the voice (owner 2026-11-01: still "destul de tare" after -6 dB);
    now an effect's level is exactly its sfx.json "lufs" + "db" + SFX_TRIM_DB."""
    head = f"{''.join(base)}amix=inputs={len(base)}:duration=first:normalize=0,{norm}"
    if not effects:
        return head + ",aresample=48000[a]"
    return (head + ",aresample=48000[base];"
            f"[base]{''.join(effects)}amix=inputs={1 + len(effects)}:duration=first:normalize=0,"
            "alimiter=limit=0.84:level=false[a]")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("vdir", type=Path)
    p.add_argument("--music", default=None, help="track id; default from <vdir>/music.json")
    p.add_argument("--music-db", type=float, default=None, help="music gain before ducking")
    p.add_argument("--music-start", type=float, default=None, help="seconds to skip in the track")
    p.add_argument("--preview", type=float, default=0.0, help="render only the first N seconds")
    p.add_argument("--out", default="video.mp4")
    p.add_argument("--audio-only", type=Path, help="write just the final mix (voice + music + effects) as MP3")
    a = p.parse_args()
    vdir = a.vdir.resolve()
    data = json.loads((vdir / "scenes.json").read_text(encoding="utf-8"))
    scenes = [data[str(n)]["narration"] for n in range(1, len(data) + 1)]
    align = json.loads((vdir / "voiceover.alignment.json").read_text(encoding="utf-8"))
    voice = vdir / "voiceover.mp3"
    total = probe_duration(voice) + TAIL
    starts = scene_starts(scenes, align) + [total]
    limit = a.preview or total

    work = vdir / "work"
    work.mkdir(exist_ok=True)
    ass = work / "captions.ass"
    captions(align, ass)
    ass.write_text(re.sub(r"^Style: Cap,.*$", CAPTION_STYLE, ass.read_text(encoding="utf-8"),
                          flags=re.M), encoding="utf-8")
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:")
    out = vdir / (f"preview_{int(a.preview)}s.mp4" if a.preview else a.out)

    choice = {}
    if (vdir / "music.json").exists():
        choice = json.loads((vdir / "music.json").read_text(encoding="utf-8-sig"))
    music = a.music or choice.get("track", "yal-calm-angels-dream")
    music_db = a.music_db
    if music_db is None and music != "none":
        # bring every bed to the same loudness (-40 LUFS before ducking; user asked three times for a quieter bed), from the library's
        # own measurement, so a loud track and a quiet one sit equally far under the voice
        lib = json.loads((MUSIC_DIR / "music_library.json").read_text(encoding="utf-8"))
        lufs = next((t.get("measured", {}).get("integrated_lufs") for t in lib["tracks"]
                     if t["id"] == music), None)
        music_db = (-40.0 - lufs) if lufs is not None else -35.0
    music_start = a.music_start if a.music_start is not None else choice.get("start", 0.0)
    inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
              "-i", str(voice)]
    # Optional sound effects (<vdir>/sfx.json: [{"file", "scene", "offset", "db", "lufs", "length"}]):
    # each one is levelled well under the voice and placed at its scene start + offset.
    sfx = load_sfx(vdir)
    if music == "none":
        audio = f"[1:a]apad,atrim=0:{limit:.2f}[v];"
        mix = ["[v]"]
        nxt = 2
    else:
        # The bed sits low and ducks a further ~8 dB while the narrator speaks (sidechain), so it
        # is felt in the pauses and never competes with the voice.
        inputs += ["-ss", f"{music_start:.2f}", "-stream_loop", "-1", "-i",
                   str(MUSIC_DIR / f"{music}.mp3")]
        audio = (f"[1:a]apad,atrim=0:{limit:.2f},asplit=2[v][key];"
                 f"[2:a]atrim=0:{limit:.2f},asetpts=PTS-STARTPTS,volume={music_db}dB,"
                 f"afade=t=in:d=3,afade=t=out:st={max(0, limit - 4):.2f}:d=4[m0];"
                 f"[m0][key]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=700[m];")
        mix = ["[v]", "[m]"]
        nxt = 3
    for k, fx in enumerate(sfx):
        # "lufs" sets the effect's level (-26 for spot effects, about -32 for ambience such as rain
        # or traffic); "length" trims an ambience to its scene, with short fades either side
        at = int((starts[fx["scene"] - 1] + fx.get("offset", 0.0)) * 1000)
        inputs += ["-i", str(vdir / fx["file"])]
        trim = ""
        if fx.get("length"):
            ln = fx["length"]
            trim = f",atrim=0:{ln},afade=t=in:d=0.4,afade=t=out:st={max(0, ln - 0.6)}:d=0.6"
        audio += (f"[{nxt + k}:a]loudnorm=I={fx.get('lufs', -26)}:TP=-3,aresample=48000{trim},"
                  f"volume={fx.get('db', 0) + SFX_TRIM_DB}dB,adelay={at}|{at}[s{k}];")
        mix.append(f"[s{k}]")
    audio += sfx_after_loudnorm(mix[:nxt - 1], mix[nxt - 1:], "loudnorm=I=-14:TP=-1.5:LRA=11")
    if a.audio_only:
        # same mix as the video; a silent placeholder keeps input 0 where the frames would be
        inputs = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"] + inputs[10:]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", audio.rstrip(";"),
                        "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "192k", "-t", f"{limit:.2f}",
                        str(a.audio_only)], check=True)
        print("wrote", a.audio_only, f"({limit:.1f}s, music {music}, {len(sfx)} effects)")
        return
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
           f"[0:v]subtitles='{ass_arg}',format=yuv420p[vo];{audio}", "-map", "[vo]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-tune", "animation",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
           "-t", f"{limit:.2f}", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    imgdir = vdir / "images"
    prev_tail = None
    written = 0
    for i in range(len(scenes)):
        if starts[i] >= limit:
            break
        n = i + 1
        # each scene also covers the dissolve into the next one
        nframes = round((starts[i + 1] - starts[i]) * FPS) + (XFADE if i + 1 < len(scenes) else 0)
        clip = imgdir / f"scene_{n:02d}_clip.mp4"
        if clip.exists():
            imgs = ["veo"]
            gen = clip_frames(clip, nframes)
        else:
            found = sorted(imgdir.glob(f"scene_{n:02d}.*"))
            if not found:
                print(f"scene {n}: no image yet, stopping")
                break
            files = found[:1]
            for pose in "bcde":
                files += sorted(imgdir.glob(f"scene_{n:02d}{pose}.*"))[:1]
            imgs = [load(f) for f in files]
            gen = scene_frames(imgs, nframes, MOVES[i % len(MOVES)])
        buf = []
        for k, fr in enumerate(gen):
            if prev_tail is not None and k < len(prev_tail):
                w = (k + 1) / (len(prev_tail) + 1)
                fr = prev_tail[k] * (1 - w) + fr * w
            if k < nframes - (XFADE if i + 1 < len(scenes) else 0):
                if written >= limit * FPS:
                    break
                ff.stdin.write(fr.astype(np.uint8).tobytes())
                written += 1
            else:
                buf.append(fr)
        prev_tail = buf
        print(f"scene {n}: {starts[i]:.2f}-{starts[i + 1]:.2f}s poses={len(imgs)}", flush=True)
    ff.stdin.close()
    ff.wait()
    print("wrote", out, f"{written / FPS:.1f}s video frames")


if __name__ == "__main__":
    main()
