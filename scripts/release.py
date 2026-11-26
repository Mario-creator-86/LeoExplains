"""vN/release.json: the hand-over between production and the scheduled publishing tasks.

PUBLISHING_SCHEDULE.md §1: production agents render everything, then mark the episode ready and
STOP; the publishing tasks post one episode per day (lowest ready N first) and record each step.
Python: any (stdlib only; needs ffprobe on PATH).

PRODUCTION (end of PRODUCTION_BRIEF.md):
  release.py vN ready [--captions FILE.json] [--caption tiktok="..."] [--file key=path]
                      [--dry-run] [--force]
    Verifies the files and the duration rules, then writes vN/release.json:
      {"status": "ready", "ready_at": ..., "files": {key: path}, "captions": {platform: text},
       "checks": {...}, "warnings": [...], "steps": {}}
    Files (paths relative to the project folder; defaults, override with --file key=path):
      long        vN/video.mp4          duration = voiceover + ~4.6 s (+-1.5 s)
      thumbnail   vN/thumbnail.png
      short       vN/short.mp4          1080x1920, under 60 s (25-35 s target, 20-58 s allowed, SHORTS_BRIEF.md)
      tiktok      vN/short_tiktok.mp4   1080x1920, 20-35 s (E-TT1 since 2026-11-03; was 61-90 s)
      reels       vN/short_reels.mp4    same rules; Instagram/Facebook Reels layout (optional, used
                                        instead of the TikTok cut for ig_reel/fb_reel when present)
      srt         vN/captions_en.srt    made by make_srt.py vN if missing
      srt_short   vN/short_captions_en.srt  made by make_srt.py vN --short if missing
      carousel    social/ig/vN/slide_*.jpg  (4-10 slides)
      fb_post     social/fb/vN/*.jpg or social/fb/vN_*.jpg  (optional)
    Captions: vN/captions.json ({platform: text}) if it exists, then --captions FILE, then each
    --caption platform=text. Platforms: tiktok, ig_reel, ig_carousel, fb_reel, fb_post (YouTube
    titles/descriptions live in the upload metadata). Missing captions and rule slips
    (hashtag counts, #fyp, links or "comment A or B" bait on Facebook) are WARNINGS.
    Missing files or broken duration/size rules are ERRORS: nothing is written, exit code 1.
    An existing release.json with steps already done is never overwritten (even with --force,
    which only allows re-marking a release that has no done steps).

PUBLISHING (scheduled tasks):
  release.py next <step> [--released]   lowest ready vN whose <step> is not done (prints vN or
                                        nothing; exit 1 when none)
  release.py vN status                  print release.json
  release.py vN step <step> --url URL [--time ISO] [--note TEXT] [--force]
    Marks a step done: steps[step] = {"done": true, "url": ..., "time": ...}. Refuses a step that
    is already done unless --force (never re-upload; this only corrects the record).
    Steps: yt_long, yt_short, tiktok, ig_reel, ig_carousel, fb_reel, fb_post.
    When every step is done, status becomes "published".
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ("yt_long", "yt_short", "tiktok", "ig_reel", "ig_carousel", "fb_reel", "fb_post")
# SHORT EPISODES (team vote 2026-11-06): a stand-alone Short under 60 s with no long
# video, marked by vN/short_episode.json. The same short.mp4 goes to YouTube Shorts, TikTok and Reels.
SHORT_STEPS = ("yt_short", "tiktok", "ig_reel", "fb_reel")


def short_only(vdir):
    return (vdir / "short_episode.json").exists()


def steps_for(data):
    return SHORT_STEPS if data.get("format") == "short" else STEPS
PLATFORMS = ("tiktok", "ig_reel", "ig_carousel", "fb_reel", "fb_post")
TAIL = 4.6                     # render.py's calm music tail after the voice (was 1.6 until 2026-11-01)


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def rel(p):
    try:
        return Path(p).resolve().relative_to(HERE).as_posix()
    except ValueError:
        return str(p)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height:format=duration", "-of", "json",
                          str(path)], capture_output=True, text=True)
    if out.returncode:
        return None
    data = json.loads(out.stdout)
    v = next((s for s in data.get("streams", []) if s["codec_type"] == "video"), {})
    a = any(s["codec_type"] == "audio" for s in data.get("streams", []))
    return {"duration": round(float(data["format"]["duration"]), 2),
            "size": f"{v.get('width')}x{v.get('height')}", "audio": a}


def load(vdir):
    f = vdir / "release.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save(vdir, data):
    f = vdir / "release.json"
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def make_srt(vdir, short):
    """Call make_srt.py (owned by the YouTube-metadata work) when it exists; never re-implement."""
    tool = HERE / "make_srt.py"
    if not tool.exists():
        return False
    py = Path(sys.executable)
    cmd = [str(py), str(tool), str(vdir)] + (["--short"] if short else [])
    print("running", " ".join(cmd[1:]))
    return subprocess.run(cmd, cwd=HERE).returncode == 0


def lint(platform, text):
    w = []
    tags = re.findall(r"#\w+", text)
    low = text.lower()
    if platform == "tiktok":
        if not 3 <= len(tags) <= 5:
            w.append(f"tiktok: {len(tags)} hashtags (rule: 3-5)")
        bad = [t for t in tags if t.lower() in ("#fyp", "#foryou", "#foryoupage", "#viral",
                                                 "#mentalhealth", "#anhedonia")]
        if bad:
            w.append(f"tiktok: avoid {' '.join(bad)}")
    if platform.startswith("ig") and len(tags) > 5:
        w.append(f"{platform}: {len(tags)} hashtags (max 5)")
    if platform.startswith("fb"):
        if re.search(r"https?://|www\.|youtu\.be", low):
            w.append(f"{platform}: no links in Facebook post text (and no link comment: the owner stopped it on 2026-11-12)")
        if re.search(r"comment (a|b|the number|1|2)\b|reply with (your|a) letter|\bor b\b", low):
            w.append(f"{platform}: engagement-bait wording (use an open question)")
    return w


def cmd_ready(vdir, a):
    n = vdir.name
    old = load(vdir)
    if old and any(s.get("done") for s in old.get("steps", {}).values()):
        raise SystemExit(f"{n}/release.json already has done steps; not overwriting")
    if old and old.get("status") == "ready" and not a.force and not a.dry_run:
        raise SystemExit(f"{n}/release.json is already ready (use --force to re-mark)")

    short_ep = short_only(vdir)
    if short_ep:
        files = {"short": f"{n}/short.mp4", "tiktok": f"{n}/short.mp4", "reels": f"{n}/short.mp4",
                 "srt_short": f"{n}/short_captions_en.srt"}
    else:
        files = {"long": f"{n}/video.mp4", "thumbnail": f"{n}/thumbnail.png",
                 "short": f"{n}/short.mp4", "tiktok": f"{n}/short_tiktok.mp4",
                 "srt": f"{n}/captions_en.srt", "srt_short": f"{n}/short_captions_en.srt"}
    slides = sorted(glob.glob(str(HERE / "social" / "ig" / n / "slide_*.*")),
                    key=lambda p: int(re.findall(r"\d+", Path(p).stem)[-1]))
    files["carousel"] = [rel(p) for p in slides]
    fb = sorted(glob.glob(str(HERE / "social" / "fb" / n / "*.jpg"))
                + glob.glob(str(HERE / "social" / "fb" / f"{n}_*.jpg")))
    if fb:
        files["fb_post"] = rel(fb[0])
    # Instagram/Facebook Reels cut laid out for the Reels interface (shorts.py --reels, 2026-11-03);
    # without it the Reels fall back to the TikTok cut
    if (vdir / "short_reels.mp4").exists() and not short_ep:
        files["reels"] = f"{n}/short_reels.mp4"
    for item in a.file or []:
        k, _, v = item.partition("=")
        files[k] = [x for x in v.split(",") if x] if k == "carousel" else v

    errors, warnings, checks = [], [], {}
    if "srt" in files and not (HERE / files["srt"]).exists() and not a.dry_run:
        make_srt(vdir, False)
    if not (HERE / files["srt_short"]).exists() and not a.dry_run:
        make_srt(vdir, True)
    for k, v in files.items():
        for p in (v if isinstance(v, list) else [v]):
            if not (HERE / p).exists():
                (warnings if k == "fb_post" else errors).append(f"missing {k}: {p}")
    if short_ep and not files["carousel"]:
        del files["carousel"]
    elif not 4 <= len(files["carousel"]) <= 10:
        errors.append(f"carousel: {len(files['carousel'])} slides (need 4-10)")

    voice = vdir / "voiceover.mp3"
    for k in ("long", "short", "tiktok", "reels"):
        if k not in files:
            continue
        p = HERE / files[k]
        if not p.exists():
            continue
        info = probe(p)
        if info is None:
            errors.append(f"{k}: ffprobe cannot read {files[k]}")
            continue
        checks[k] = info
        d = info["duration"]
        if not info["audio"]:
            errors.append(f"{k}: no audio stream")
        if k == "long" and voice.exists():
            vd = probe(voice)["duration"]
            if abs(d - (vd + TAIL)) > 1.5:
                errors.append(f"long: {d} s, expected voiceover {vd} s + {TAIL} s")
        if k in ("short", "tiktok", "reels") and info["size"] != "1080x1920":
            errors.append(f"{k}: {info['size']} (need 1080x1920)")
        if k == "short":
            if d >= 60:
                errors.append(f"short: {d} s (must be under 60 s)")
            elif not 20 <= d <= 58:
                warnings.append(f"short: {d} s (brief: 20-58 s, target 25-35 s)")
        if short_ep and k in ("tiktok", "reels"):
            # 22.11.2026, the agent's request: v116 (6.97 s, review PASS, already on TikTok and Reels) could not be
            # released for YouTube. The length of a clip is the agent's (the Owner, 12.11): only the platforms'
            # 60 s ceiling is an error here; a clip under 20 s is a warning, as it already was for "short".
            if d >= 60:
                errors.append(f"{k}: {d} s (short episode: must be under 60 s)")
            elif d < 20:
                warnings.append(f"{k}: {d} s (under 20 s; the length is the agent's choice)")
            continue
        if k == "tiktok" and not 20 <= d <= 35:
            errors.append(f"tiktok: {d} s (rule since 2026-11-03: 20-35 s, E-TT1)")
        if k == "reels":
            if not 61 <= d <= 90:
                errors.append(f"{k}: {d} s (rule: 61-90 s)")
            elif d < 70:
                warnings.append(f"{k}: {d} s (target 70-90 s)")

    caps = {}
    sources = [vdir / "captions.json"] + [Path(x) for x in (a.captions or [])]
    for src in sources:
        if src.exists():
            caps.update(json.loads(src.read_text(encoding="utf-8")))
        elif src.name != "captions.json":
            errors.append(f"captions file not found: {src}")
    for item in a.caption or []:
        k, _, v = item.partition("=")
        caps[k] = v
    for p in PLATFORMS:
        if short_ep and p in ("ig_carousel", "fb_post") and "carousel" not in files:
            continue
        if not caps.get(p):
            warnings.append(f"no caption for {p}")
    for p, t in caps.items():
        warnings += lint(p, t)

    data = {"status": "ready", "episode": n, "ready_at": now(), "files": files,
            "captions": caps, "checks": checks, "warnings": warnings, "steps": {}}
    if short_ep:
        data["format"] = "short"
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:", e)
    if errors:
        raise SystemExit(f"{n}: not ready ({len(errors)} error(s)); release.json not written")
    if a.dry_run:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"{n}: checks passed (dry run, nothing written)")
        return
    save(vdir, data)
    print(f"wrote {n}/release.json (status ready, {len(warnings)} warning(s))")


def cmd_step(vdir, a):
    if a.step not in STEPS:
        raise SystemExit(f"unknown step {a.step}; steps: {', '.join(STEPS)}")
    data = load(vdir)
    if data is None or data.get("status") not in ("ready", "published"):
        raise SystemExit(f"{vdir.name} has no ready release.json")
    if data["steps"].get(a.step, {}).get("done") and not a.force:
        raise SystemExit(f"{vdir.name}: {a.step} already done ({data['steps'][a.step]})")
    # 2026-11-08 (after v57): an episode on hold is never marked as released. If it was posted anyway, the
    # owner records it on purpose with --force and the team reports it.
    order_file = HERE / "release_order.json"
    order = json.loads(order_file.read_text(encoding="utf-8-sig")) if order_file.exists() else {}
    day = order.get("hold_until", {}).get(vdir.name)
    if day and dt.date.today().isoformat() < day and not a.force:
        raise SystemExit(f"{vdir.name} is on hold until {day} (release_order.json): not recorded. "
                         f"If it really went out, report it; the owner may record it with --force.")
    entry = {"done": True, "url": a.url, "time": a.time or now()}
    if a.note:
        entry["note"] = a.note
    data["steps"][a.step] = entry
    if all(data["steps"].get(s, {}).get("done") for s in steps_for(data)):
        data["status"] = "published"
        data["published_at"] = now()
    save(vdir, data)
    print(f"{vdir.name}: {a.step} done -> {a.url}" + (" (all steps done: published)"
                                                       if data["status"] == "published" else ""))


def cmd_next(step, released=False):
    if step not in STEPS:
        raise SystemExit(f"unknown step {step}; steps: {', '.join(STEPS)}")
    # release_order.json (owner OK 2026-11-01): timely episodes wait for their date, priority first
    order = {}
    if (HERE / "release_order.json").exists():
        order = json.loads((HERE / "release_order.json").read_text(encoding="utf-8"))
    today = dt.date.today().isoformat()
    held = {n for n, day in order.get("hold_until", {}).items() if today < day}
    prio = order.get("priority", [])
    eps = sorted(((prio.index(d.name) if d.name in prio else len(prio), int(m.group(1))), d)
                 for d in HERE.iterdir()
                 if (m := re.fullmatch(r"v(\d+)", d.name)) and (d / "release.json").exists()
                 and d.name not in held)
    for _, d in eps:
        data = load(d)
        if released and not data["steps"].get("yt_short" if data.get("format") == "short" else "yt_long", {}).get("done"):
            continue                       # social cuts follow the episode's YouTube release
        if data.get("status") == "ready" and step in steps_for(data) and not data["steps"].get(step, {}).get("done"):
            print(d.name)
            return
    raise SystemExit(1)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "next":
        p = argparse.ArgumentParser(prog="release.py next")
        p.add_argument("cmd")
        p.add_argument("step")
        p.add_argument("--released", action="store_true",
                       help="only episodes whose yt_long step is done (Reels/TikTok slots)")
        a = p.parse_args()
        cmd_next(a.step, a.released)
        return
    p = argparse.ArgumentParser()
    p.add_argument("vdir", help="episode folder, e.g. v13")
    p.add_argument("cmd", choices=("ready", "step", "status"))
    p.add_argument("step", nargs="?")
    p.add_argument("--file", action="append", help="key=path (carousel: comma-separated)")
    p.add_argument("--captions", action="append", help="JSON file {platform: text}")
    p.add_argument("--caption", action="append", help="platform=text")
    p.add_argument("--url")
    p.add_argument("--time")
    p.add_argument("--note")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    vdir = (HERE / a.vdir).resolve() if not Path(a.vdir).is_absolute() else Path(a.vdir)
    if not vdir.is_dir():
        raise SystemExit(f"no episode folder {vdir}")
    if a.cmd == "ready":
        cmd_ready(vdir, a)
    elif a.cmd == "status":
        data = load(vdir)
        print(json.dumps(data, indent=1, ensure_ascii=False) if data else f"{vdir.name}: none")
    else:
        if not a.step or not a.url:
            raise SystemExit("usage: release.py vN step <step> --url URL [--time ISO]")
        cmd_step(vdir, a)


if __name__ == "__main__":
    main()
