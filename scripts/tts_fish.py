"""Leo's narration with Fish Audio Drama 3 (owner decision 2026-11-02: one-month test through the
Hugging Face PRO subscription; Kokoro stays installed until the owner decides).

Drama 3 runs in a private ZeroGPU Space (environment variable FISH_SPACE, e.g. <hf-user>/leo-drama3: a
copy of fishaudio/Drama-3 with one extra API, /speak, that clones from the reference WAV sent with every
call). Calls carry the Hugging Face token of the logged-in `hf auth login` user (or HF_TOKEN), so they use
that account's PRO GPU quota; nothing is paid per episode.

Writes the SAME files as tts_kokoro.py, so render.py / shorts.py / make_srt.py need no change:
  vN/voiceover.mp3               44.1 kHz mono, 128 kbps
  vN/voiceover.alignment.json    per-character times over "\\n".join(scene narrations)
Each scene is one take, cloned from the same reference (voice/leo_en_v1.wav), so the timbre stays the
same across episodes, Shorts and single-scene regenerations, including after restarts. The take for
scene N is kept in vN/voice_fish/scene_NN.wav with its record in vN/voice_fish/takes.json: a failed
scene is retried, finished scenes are reused, and `--scene N` regenerates just that scene.

The text sent to Fish is scenes.json "fish" (the narration plus tested direction tags such as
[hesitates]); without it, the plain "narration". Subtitles and timings always come from "narration".
Every take is checked with local Whisper (voice/asr_check.py): no missing words, no tag read aloud.

Runs with the TTS virtualenv python.
usage: tts_fish.py vN [--scene N ...] [--force] [--boundary N] [--ref WAV --ref-text TEXT]
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "voice"))
import asr_check  # noqa: E402
import team_settings  # noqa: E402

# The team owns the voice (owner 2026-11-12: «viteza voce, numele persoanei din Fish» are theirs to choose):
# team_settings.json {"voice": {"reference": "<name of voice/<name>.json>", "speed": 1.1, "pause": 0.30}}.
_VOICE = team_settings.section("voice")
_REF_NAME = str(_VOICE.get("reference", "leo_en_v1"))
if not re.fullmatch(r"[A-Za-z0-9_.-]+", _REF_NAME):
    raise SystemExit(f"team_settings.json: voice.reference {_REF_NAME!r} must be a plain name, e.g. leo_en_v1")

SPACE = os.environ.get("FISH_SPACE", "")   # <hf-user>/<space>: a private copy of fishaudio/Drama-3 with the /speak API
if not SPACE:
    raise SystemExit("FISH_SPACE is not set (the Hugging Face Space that runs Drama 3; see .env.example)")
MODEL = "fishaudio/drama-3@e0a9218aa48888270f06ef1ed9ea67622c0e17d2"
REFERENCE = ROOT / "voice" / (_REF_NAME + ".json")   # {"file", "transcript", ...}, written by voice/pick_voice.py
SR = 44100
# seconds of silence between scenes (owner 2026-11-11: 0.45 felt slow and boring); the team's value, default 0.30
PAUSE = team_settings.number(_VOICE, "pause", 0.30, 0.0, 2.0)
LEAD = 0.15             # silence before the first word
SPEED_RANGE = (0.5, 2.0)   # technical range of one ffmpeg atempo filter (it keeps the pitch); the choice is the team's
# default speed: the team's value, else 1.1 (owner 2026-11-11); per episode vN/voice.json {"speed": 1.2} or --speed
SPEED = team_settings.number(_VOICE, "speed", 1.1, *SPEED_RANGE)
TEMPERATURE, TOP_P, TOP_K = 0.8, 0.9, 0
MAX_TRIES = 3
SCENE_TARGET = 4.0      # seconds per scene in the script rules (narration + the pause after it)
LEVEL_TOLERANCE, LEVEL_MAX = 1.5, 3.0   # dB: scenes further than this from the median are nudged, at most this
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")   # path to ffmpeg, default: on PATH
TAG = re.compile(r"\[[^\]]*\]|<[^>]*>")


def sha(*parts):
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def reference(args):
    if args.ref:
        return Path(args.ref).resolve(), args.ref_text
    if not REFERENCE.exists():
        raise SystemExit(f"the voice {REFERENCE.name} named in team_settings.json does not exist in voice/")
    info = json.loads(REFERENCE.read_text(encoding="utf-8"))
    return (REFERENCE.parent / info["file"]).resolve(), info["transcript"]


def tag_words(fish):
    return {w for t in TAG.findall(fish) for w in asr_check.norm(t)}


def load_take(path):
    wav, rate = sf.read(str(path), dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    if rate != SR:
        import torch
        import torchaudio.functional as F
        wav = F.resample(torch.from_numpy(wav), rate, SR).numpy()
    return wav


def trim(wav, floor_db=-45.0, margin=0.03):
    """Cut leading and trailing silence, keeping a short margin."""
    frame = int(0.01 * SR)
    n = len(wav) // frame
    if n == 0:
        return wav
    rms = np.sqrt(np.mean(wav[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    loud = np.where(20 * np.log10(rms) > floor_db)[0]
    if loud.size == 0:
        return wav
    a = max(0, loud[0] * frame - int(margin * SR))
    b = min(len(wav), (loud[-1] + 1) * frame + int(margin * SR))
    return wav[a:b]


def speech_db(wav):
    frame = int(0.02 * SR)
    n = len(wav) // frame
    if n == 0:
        return -99.0
    rms = np.sqrt(np.mean(wav[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    voiced = db[db > db.max() - 30]
    return float(10 * np.log10(np.mean(10 ** (voiced / 10))))


def check(path, narration, fish, metrics):
    heard = asr_check.words_in(path)
    missing, extra = asr_check.compare(narration, heard)
    literal = sorted(set(extra) & tag_words(fish))
    cut = "went quiet" in (metrics or "")
    # Romanian (LEO_LANG=ro): whisper-small mishears some inflections, so allow ~15 % of the words
    allowed = 1 if asr_check.LANG == "en" else max(1, round(0.15 * len(asr_check.norm(narration))))
    ok = not cut and len(missing) <= allowed and not literal
    return ok, {"heard": " ".join(w for w, _, _ in heard), "missing": missing, "extra": extra,
                "literal_tags": literal, "cut_short": cut,
                "words": [(w, round(s, 3), round(e, 3)) for w, s, e in heard]}


def connect(Client, token, wait=900):
    """The Space sleeps after 48 h without use (11.11: two httpx.ReadTimeout, v67 scene 10 never voiced, the job gave up).
    Wake it, wait until it runs (up to `wait` seconds), then connect with a long timeout and three tries."""
    try:
        from huggingface_hub import HfApi
        api, t0, asked = HfApi(token=token), time.time(), False
        while True:
            stage = str(api.get_space_runtime(SPACE).stage)
            if stage in ("RUNNING", "RUNNING_BUILDING"):
                break
            if stage == "PAUSED":
                raise SystemExit(f"the Space {SPACE} is PAUSED: the owner restarts it on huggingface.co (Settings, Restart)")
            if not asked:
                print(f"Space {SPACE} is {stage}: waking it, this can take a few minutes", flush=True)
                try:
                    api.restart_space(SPACE)
                except Exception as error:
                    print(f"  wake request failed ({error}); waiting for it anyway", flush=True)
                asked = True
            if time.time() - t0 > wait:
                raise SystemExit(f"the Space {SPACE} is still {stage} after {wait} s; run the same command again later")
            time.sleep(20)
    except SystemExit:
        raise
    except Exception as error:  # the status call is a convenience: without it, the retries below still apply
        print(f"could not read the Space status ({error}); connecting directly", flush=True)
    last = None
    for attempt in range(1, 4):
        try:
            return Client(SPACE, token=token, verbose=False, httpx_kwargs={"timeout": 180})
        except Exception as error:
            last = error
            print(f"connect attempt {attempt} failed: {error}", flush=True)
            time.sleep(30 * attempt)
    raise SystemExit(f"could not connect to {SPACE} after 3 tries: {last}")


def generate_scene(client, n, narration, fish, ref, ref_text, folder):
    from gradio_client import handle_file
    best = None
    for attempt in range(1, MAX_TRIES + 1):
        t0 = time.time()
        try:
            path, metrics = client.predict(fish, handle_file(str(ref)), ref_text, TEMPERATURE, TOP_P, TOP_K,
                                           api_name="/speak")
        except Exception as error:  # rate limit, quota, queue or a Space restart: wait, retry, then report
            print(f"  scene {n}: attempt {attempt} failed: {error}", flush=True)
            m = re.search(r"try again in (\d+)\s*s", str(error))
            time.sleep(min(int(m.group(1)) + 5, 900) if m else 30)
            continue
        tmp = folder / f"scene_{n:02d}.try{attempt}.wav"
        shutil.copyfile(path, tmp)
        ok, report = check(tmp, narration, fish, metrics)
        report.update(attempt=attempt, metrics=metrics, seconds=round(time.time() - t0, 1))
        score = (ok, -len(report["missing"]), -len(report["literal_tags"]))
        if best is None or score > best[0]:
            best = (score, tmp, report)
        if ok:
            break
        print(f"  scene {n}: retry ({'cut short' if report['cut_short'] else ''} missing {report['missing']} "
              f"literal {report['literal_tags']})", flush=True)
    if best is None:
        return None
    _, tmp, report = best
    final = folder / f"scene_{n:02d}.wav"
    if final.exists():
        shutil.copyfile(final, folder / f"scene_{n:02d}.prev.wav")
    shutil.move(tmp, final)
    for leftover in folder.glob(f"scene_{n:02d}.try*.wav"):
        leftover.unlink()
    report["ok"] = best[0][0]
    return report


def char_times(text, words, t0, t_end):
    """Per-character (start, end) over `text` from Whisper word timings (already shifted to the episode)."""
    low = text.lower().replace("’", "'")
    n = len(text)
    starts, ends = [None] * n, [None] * n
    pos = 0
    for w, s, e in words:
        core = re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))
        if not core:
            continue
        i = low.find(core, pos)
        if i < 0 or i - pos > 40:      # unmatched (e.g. "2009" heard as words): leave to the gap filler
            continue
        L = len(core)
        for k in range(L):
            starts[i + k] = s + (e - s) * k / L
            ends[i + k] = s + (e - s) * (k + 1) / L
        pos = i + L
    last_end = t0
    for i in range(n):
        if starts[i] is None:
            nxt = next((starts[j] for j in range(i + 1, n) if starts[j] is not None), t_end)
            starts[i], ends[i] = last_end, max(last_end, nxt)
        last_end = ends[i]
    return starts, ends


def leveled(waves):
    levels = [speech_db(w) for w in waves]
    median = float(np.median(levels))
    gains = []
    for lv in levels:
        diff = median - lv
        gains.append(float(np.clip(diff, -LEVEL_MAX, LEVEL_MAX)) if abs(diff) > LEVEL_TOLERANCE else 0.0)
    return [w * 10 ** (g / 20) for w, g in zip(waves, gains)], levels, gains


def episode_speed(vdir, override=None):
    """The episode's voice speed: --speed, else vN/voice.json {"speed": x}, else SPEED; always within SPEED_RANGE."""
    speed = override
    if speed is None:
        try:
            speed = float(json.loads((vdir / "voice.json").read_text(encoding="utf-8")).get("speed", SPEED))
        except (OSError, ValueError, AttributeError):
            speed = SPEED
    if not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
        raise SystemExit(f"voice speed {speed} is outside {SPEED_RANGE}")
    return round(speed, 3)


def episode_beat(vdir):
    """Extra seconds of silence (real time) before the last scene: vN/voice.json {"beat": 0.6}, else 0."""
    try:
        beat = float(json.loads((vdir / "voice.json").read_text(encoding="utf-8")).get("beat", 0))
    except (OSError, ValueError, AttributeError):
        beat = 0.0
    return min(max(beat, 0.0), 1.5)


def assemble(vdir, scenes, takes, out, speed=SPEED):
    folder = vdir / "voice_fish"
    waves = [trim(load_take(folder / f"scene_{k:02d}.wav")) for k in range(1, len(scenes) + 1)]
    waves, levels, gains = leveled(waves)
    parts, chars, cs, ce = [np.zeros(int(LEAD * SR), np.float32)], [], [], []
    t = LEAD
    report = []
    for k, (text, wav) in enumerate(zip(scenes, waves), start=1):
        dur = len(wav) / SR
        words = [(w, t + s, t + e) for w, s, e in takes[str(k)]["words"]]
        s, e = char_times(text, words, t, t + dur)
        chars += list(text); cs += s; ce += e
        parts.append(wav.astype(np.float32))
        t += dur
        if k < len(scenes):
            gap = PAUSE + (episode_beat(vdir) * speed if k == len(scenes) - 1 else 0.0)
            chars.append("\n"); cs.append(t); ce.append(t + gap)
            parts.append(np.zeros(int(gap * SR), np.float32))
            t += gap
        report.append((k, dur, levels[k - 1], gains[k - 1]))
    audio = np.concatenate(parts)
    assert "".join(chars) == "\n".join(scenes)
    peak = float(np.abs(audio).max())
    if peak > 0.97:
        audio *= 0.97 / peak
    wav = out.with_suffix(".fish.wav")
    sf.write(wav, audio, SR)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                    "-filter:a", f"atempo={speed}", "-c:a", "libmp3lame", "-b:a", "128k", str(out)], check=True)
    wav.unlink()
    align = {"characters": chars, "character_start_times_seconds": [round(x / speed, 3) for x in cs],
             "character_end_times_seconds": [round(x / speed, 3) for x in ce],
             "engine": f"fish {MODEL} via {SPACE}, temperature {TEMPERATURE}, top_p {TOP_P}, speed {speed}x"}
    t /= speed
    out.with_suffix(".alignment.json").write_text(json.dumps(align, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({t:.1f}s) and {out.with_suffix('.alignment.json').name}")
    return report, t


def boundary(vdir, n, scenes):
    """vN/voice_fish/boundary_NN.wav: scenes n-1, n, n+1 exactly as the episode joins them."""
    folder = vdir / "voice_fish"
    ks = [k for k in (n - 1, n, n + 1) if 1 <= k <= len(scenes)]
    waves = [trim(load_take(folder / f"scene_{k:02d}.wav")) for k in range(1, len(scenes) + 1)]
    waves, _, _ = leveled(waves)
    gap = np.zeros(int(PAUSE * SR), np.float32)
    parts = []
    for k in ks:
        parts += [waves[k - 1], gap]
    out = folder / f"boundary_{n:02d}.wav"
    sf.write(out, np.concatenate(parts[:-1]), SR)
    print("wrote", out)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("episode")
    p.add_argument("--scene", type=int, nargs="*", help="regenerate only these scenes, then reassemble")
    p.add_argument("--force", action="store_true", help="replace an existing voiceover.mp3")
    p.add_argument("--boundary", type=int, help="also write the scene with its two neighbours as a WAV")
    p.add_argument("--ref", help="reference WAV (default: voice/leo_en_v1.json)")
    p.add_argument("--ref-text", help="exact words of the reference WAV")
    p.add_argument("--out", type=Path)
    p.add_argument("--speed", type=float, help="voice speed 0.5-2.0 (default: vN/voice.json speed, else the team's speed, else 1.1)")
    a = p.parse_args()
    vdir = Path(a.episode).resolve()
    out = a.out or vdir / "voiceover.mp3"
    doc = json.loads((vdir / "scenes.json").read_text(encoding="utf-8"))
    narr = [doc[str(k)]["narration"] for k in range(1, len(doc) + 1)]
    fish = [doc[str(k)].get("fish") or doc[str(k)]["narration"] for k in range(1, len(doc) + 1)]
    for k, (n_, f_) in enumerate(zip(narr, fish), start=1):
        if asr_check.norm(TAG.sub(" ", f_)) != asr_check.norm(n_):
            raise SystemExit(f"scene {k}: the fish text must say exactly the narration's words (tags aside)")
    if out.exists() and not a.force and not a.scene:
        raise SystemExit(f"{out} exists; episodes already voiced keep their voice (--force to redo)")
    ref, ref_text = reference(a)
    folder = vdir / "voice_fish"
    folder.mkdir(exist_ok=True)
    rec_path = folder / "takes.json"
    takes = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    ref_sha = hashlib.sha1(ref.read_bytes()).hexdigest()[:16]
    todo = []
    for k in range(1, len(doc) + 1):
        key = sha(fish[k - 1], ref_sha, TEMPERATURE, TOP_P, TOP_K, MODEL)
        have = takes.get(str(k))
        if (a.scene and k in a.scene) or not have or have.get("key") != key or not (folder / f"scene_{k:02d}.wav").exists():
            todo.append((k, key))
    if todo:
        from gradio_client import Client
        from huggingface_hub import get_token
        client = connect(Client, get_token())
    failed = []
    for k, key in todo:
        rep = generate_scene(client, k, narr[k - 1], fish[k - 1], ref, ref_text, folder)
        if rep is None:
            failed.append(k)
            continue
        rep.update(key=key, fish=fish[k - 1], narration=narr[k - 1], reference=ref.name, reference_sha=ref_sha,
                   model=MODEL, space=SPACE, temperature=TEMPERATURE, top_p=TOP_P, top_k=TOP_K,
                   made_at=datetime.now().isoformat(timespec="seconds"))
        takes[str(k)] = rep
        rec_path.write_text(json.dumps(takes, indent=1, ensure_ascii=False), encoding="utf-8")
        flag = "" if rep["ok"] else f"  CHECK: missing {rep['missing']} literal {rep['literal_tags']}"
        print(f"scene {k}: {rep['metrics'].splitlines()[0] if rep['metrics'] else ''}{flag}", flush=True)
    if failed:
        raise SystemExit(f"scenes {failed} failed; finished scenes are kept, run the same command again")
    report, total = assemble(vdir, narr, takes, out, episode_speed(vdir, a.speed))
    longs = [(k, d) for k, d, _, _ in report if d + PAUSE > SCENE_TARGET]
    print(f"total {total:.1f}s; scenes over {SCENE_TARGET:.0f}s with pause: "
          + (", ".join(f"{k} ({d + PAUSE:.1f}s)" for k, d in longs) or "none"))
    lv = [l for _, _, l, _ in report]
    print(f"scene levels: spread {max(lv) - min(lv):.1f} dB, nudged {sum(1 for *_, g in report if g)} scenes")
    bad = [k for k in range(1, len(doc) + 1) if not takes[str(k)]["ok"]]
    if bad:
        print("scenes to listen to (Whisper check not clean):", bad)
    if a.boundary:
        boundary(vdir, a.boundary, narr)


if __name__ == "__main__":
    main()
