"""Romanian TikTok version of an episode cut (2026-11-03). TikTok Studio showed 82.9 % of our TikTok viewers are in
Romania, so TikTok gets Romanian voice, title box and captions; the other platforms stay English.

Builds a small stand-alone "episode" folder ro/<vN>_<tag>/ from the picked scenes of vN: the Romanian lines become
its scenes.json narration, the scenes' 16:9 pictures are copied, music.json is reused. Then it voices it with Leo's
cloned Fish voice in Romanian (tts_fish.py with LEO_LANG=ro: multilingual Whisper checks every take) and renders the
band-layout TikTok cut with shorts.py.

usage: <tts_venv python> ro_cut.py vN <tag> --texts ro/<vN>_<tag>.json
       The texts file: {"title": "Romanian title-box question", "scenes": {"<n>": "Romanian line", ...}}
       (scene numbers of vN, in the order they are read). Output: ro/<vN>_<tag>/tiktok_ro.mp4
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TTS_PY = Path(os.environ.get("TTS_PYTHON", sys.executable))      # interpreter with the TTS packages (tts_fish.py)
SHORTS_PY = Path(sys.executable)                                   # interpreter for shorts.py (Pillow, numpy)
FFMPEG_DIR = os.environ.get("FFMPEG_DIR", "")                      # optional folder holding ffmpeg/ffprobe


def main():
    p = argparse.ArgumentParser()
    p.add_argument("episode")
    p.add_argument("tag")
    p.add_argument("--texts", type=Path, required=True)
    a = p.parse_args()
    src = (HERE / a.episode).resolve()
    spec = json.loads(a.texts.read_text(encoding="utf-8"))
    picks = [int(n) for n in spec["scenes"]]
    out = HERE / "ro" / f"{src.name}_{a.tag}"
    (out / "images").mkdir(parents=True, exist_ok=True)
    orig = json.loads((src / "scenes.json").read_text(encoding="utf-8"))
    scenes = {}
    for k, n in enumerate(picks, start=1):
        scenes[str(k)] = {"narration": spec["scenes"][str(n)].strip(), "image": orig[str(n)].get("image", ""),
                          "source_scene": n}
        for pose in ("", "b", "c", "d"):
            for f in sorted((src / "images").glob(f"scene_{n:02d}{pose}.*")):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    shutil.copy(f, out / "images" / f"scene_{k:02d}{pose}{f.suffix}")
                    break
    (out / "scenes.json").write_text(json.dumps(scenes, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy(src / "music.json", out / "music.json")
    (out / "meta.json").write_text(json.dumps({"title": spec["title"], "source": src.name, "lang": "ro"},
                                              ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, LEO_LANG="ro", PYTHONIOENCODING="utf-8")
    if FFMPEG_DIR:
        env["PATH"] = FFMPEG_DIR + os.pathsep + env.get("PATH", "")
    if not (out / "voiceover.mp3").exists():
        subprocess.run([str(TTS_PY), str(HERE / "tts_fish.py"), str(out)], cwd=HERE, env=env, check=True)
    n = len(picks)
    subprocess.run([str(SHORTS_PY), str(HERE / "shorts.py"), str(out), "--tiktok", "--scenes",
                    ",".join(str(k) for k in range(1, n + 1)), "--band", spec["title"], "--out", "tiktok_ro.mp4"],
                   cwd=HERE, env=env, check=True)
    subprocess.run([str(SHORTS_PY), str(HERE / "shorts.py"), str(out), "--tiktok", "--out", "tiktok_ro.mp4",
                    "--check", str(out / "tiktok_ro_sheet.png")], cwd=HERE, env=env, check=True)
    print("wrote", out / "tiktok_ro.mp4")


if __name__ == "__main__":
    sys.exit(main())
