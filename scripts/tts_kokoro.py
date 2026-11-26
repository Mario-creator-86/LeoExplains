"""Leo's narration, made on this PC with Kokoro-82M (Apache-2.0). It sends nothing anywhere and costs nothing.

Owner, 2026-11-15: «Nu mai avem abonament pe huging face, deci vocea se face local.» The Fish voice ran in a
Hugging Face Space that needs the PRO subscription (tts_fish.py); from this day new and corrected episodes are
voiced here. Episodes already voiced keep the voice they have. (History: Kokoro "am_michael" was Leo's voice
for v24 and v25, owner decision 2026-11-01, before the Fish trial of 2026-11-02.)

Writes the SAME files as tts_fish.py, so render.py / shorts.py / make_srt.py need no change:
  vN/voiceover.mp3               44.1 kHz mono, 128 kbps
  vN/voiceover.alignment.json    {characters, character_start_times_seconds, character_end_times_seconds}
                                 over "\\n".join(scene narrations)
Each scene is synthesised on its own (one Kokoro call per scene) with a pause between scenes, so scene
boundaries are exact. Kokoro's word timestamps are spread over the word's characters; spaces and punctuation
take the gap to the next word. The text read is scenes.json "narration"; the "fish" text with its direction
tags is not used.

The team's settings (team_settings.json "voice", the same keys the Fish script reads):
  "speed"   default 1.1; per episode vN/voice.json {"speed": 1.2}, or --speed. It is Kokoro's own speed, which
            gives lengths close to the Fish voice at the same number (v104, 75 words, 1.2: 27.6 s here, 29.4 s there).
  "pause"   seconds of silence between scenes, default 0.30
  "kokoro"  the Kokoro voice, default am_michael
An episode takes about 15 seconds, so the whole episode is voiced again every time; --scene is accepted for
old commands and changes nothing. A voiceover that exists is replaced only with --force, and the old files are
first moved to vN/rejected/voice/ (nothing is deleted).

Runs with the voice venv:  python  
usage: tts_kokoro.py vN [--force] [--speed 1.2] [--pause 0.30] [--voice am_michael] [--out vN/voiceover.mp3]
       tts_kokoro.py --sample "text..." out.wav [--voice ...] [--speed ...]
"""
import argparse
import json
import re
import shutil
import subprocess
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

import team_settings

warnings.filterwarnings("ignore")
SR = 24000
_VOICE = team_settings.section("voice")
VOICE = str(_VOICE.get("kokoro", "am_michael"))   # owner picked am_michael on 2026-11-01; the choice is the team's
if not re.fullmatch(r"[a-z]{2}_[a-z0-9]+", VOICE):
    raise SystemExit(f"team_settings.json: voice.kokoro {VOICE!r} must be a Kokoro voice name, e.g. am_michael")
SPEED_RANGE = (0.5, 2.0)
SPEED = team_settings.number(_VOICE, "speed", 1.1, *SPEED_RANGE)   # the team's value, as for the Fish voice
PAUSE = team_settings.number(_VOICE, "pause", 0.30, 0.0, 2.0)      # seconds of silence between scenes
LEAD = 0.15                # silence before the first word
SCENE_TARGET = 4.0         # seconds per scene in the script rules (narration + the pause after it)
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")   # path to ffmpeg, default: on PATH


def pipeline():
    from kokoro import KPipeline
    return KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")


def synth_scene(pipe, text, voice, speed):
    """(audio float32 @24k, [(word_text, start, end)]) for one scene's narration."""
    chunks, words, offset = [], [], 0.0
    for r in pipe(text, voice=voice, speed=speed):
        audio = r.audio.numpy().astype(np.float32)
        for t in (getattr(r, "tokens", None) or []):
            s, e = getattr(t, "start_ts", None), getattr(t, "end_ts", None)
            if s is not None and e is not None and t.text.strip():
                words.append((t.text, offset + float(s), offset + float(e)))
        chunks.append(audio)
        offset += len(audio) / SR
    return (np.concatenate(chunks) if chunks else np.zeros(0, np.float32)), words


def char_times(text, words, t0, t_end):
    """Per-character (start, end) over `text`, from word timings (times already shifted by t0)."""
    n = len(text)
    starts, ends = [None] * n, [None] * n
    pos = 0
    for w, s, e in words:
        core = w.strip()
        i = text.find(core, pos)
        if i < 0:
            continue
        L = len(core)
        for k in range(L):
            starts[i + k] = s + (e - s) * k / L
            ends[i + k] = s + (e - s) * (k + 1) / L
        pos = i + L
    # fill gaps (spaces, punctuation, unmatched words) between known neighbours
    last_end = t0
    for i in range(n):
        if starts[i] is None:
            nxt = next((starts[j] for j in range(i + 1, n) if starts[j] is not None), t_end)
            starts[i], ends[i] = last_end, nxt
        last_end = ends[i]
    return starts, ends


def episode_speed(vdir, override=None):
    """The episode's voice speed: --speed, else vN/voice.json {"speed": x}, else the team's; always within SPEED_RANGE."""
    speed = override
    if speed is None:
        try:
            speed = float(json.loads((vdir / "voice.json").read_text(encoding="utf-8")).get("speed", SPEED))
        except (OSError, ValueError, AttributeError):
            speed = SPEED
    if not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
        raise SystemExit(f"voice speed {speed} is outside {SPEED_RANGE}")
    return round(speed, 3)


def set_aside(out):
    """Move an existing voiceover and its alignment to vN/rejected/voice/ (never deleted). Returns the new paths."""
    moved = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for f in (out, out.with_suffix(".alignment.json")):
        if f.exists():
            folder = out.parent / "rejected" / "voice"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{f.stem}_{stamp}{f.suffix}"
            shutil.move(str(f), str(target))
            moved.append(target)
    return moved


LINE_GAP = 0.15   # seconds of silence between two speakers inside one scene


def voices_on_disk():
    """Kokoro voices that are already on this PC (nothing is downloaded by a run)."""
    import glob
    import os
    pat = os.path.expanduser("~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M/snapshots/*/voices/*.pt")
    return sorted({os.path.basename(f)[:-3] for f in glob.glob(pat)})


def voice_of(who, cast, default):
    """The Kokoro voice of a speaker. Leo (and a scene with no speaker) has the team's voice; every other person has the
    "voice" written for them in vN/cast.json. The Owner, 21.11.2026: «Avem mai multe voci! Avem acces ! De ce ne limitam ?»"""
    who = str(who or "leo").strip().lower()
    if who in ("leo", "narrator"):
        return default
    if who in ("biscuit", "cat"):
        raise SystemExit("Biscuit never speaks: a meow is a sound in the \"motion\" text, not a line")
    for c in cast:
        if str(c.get("id", "")).lower() == who or str(c.get("name", "")).lower() == who:
            v = str(c.get("voice") or "")
            if not re.fullmatch(r"[a-z]{2}_[a-z0-9]+", v):
                raise SystemExit(f"cast.json: {who!r} speaks but has no Kokoro \"voice\" (for example bm_george)")
            have = voices_on_disk()
            if have and v not in have:
                raise SystemExit(f"voice {v!r} of {who!r} is not on this PC (here: {', '.join(have)}). It is fetched once, "
                                 "outside a job, from the Kokoro-82M model's voices folder; ask the channel agent.")
            return v
    raise SystemExit(f"{who!r} speaks in scenes.json but is not in cast.json: give every person who speaks an id and a voice")


def scene_parts(scene, cast, default):
    """[(voice, text)] for one scene: its "lines" when it has them, else its narration in the default voice."""
    lines = scene.get("lines")
    if not lines:
        return [(default, scene["narration"])]
    parts = [(voice_of(l.get("who"), cast, default), str(l.get("text", "")).strip()) for l in lines]
    parts = [(v, t) for v, t in parts if t]
    if not parts:
        raise SystemExit("a scene has \"lines\" but none of them has text")
    return parts


def voice_episode(vdir, voice, speed, pause, out):
    scenes_doc = json.loads((vdir / "scenes.json").read_text(encoding="utf-8-sig"))
    cast = []
    try:
        cast = json.loads((vdir / "cast.json").read_text(encoding="utf-8-sig")).get("characters", [])
    except (OSError, ValueError):
        pass
    parts_of = [scene_parts(scenes_doc[str(n)], cast, voice) for n in range(1, len(scenes_doc) + 1)]
    scenes = [" ".join(t for _, t in parts) for parts in parts_of]   # the words of a scene, in the order they are spoken
    try:
        vj = json.loads((vdir / "voice.json").read_text(encoding="utf-8"))
        vspeed, vlead = dict(vj.get("voice_speed") or {}), dict(vj.get("voice_lead") or {})
        linepad = {str(k): float(x) for k, x in dict(vj.get("line_pad") or {}).items()}
        say = {str(k): dict(x) for k, x in dict(vj.get("say") or {}).items()}   # {"4": {"reactance": "ree-ACK-tunss"}}: spelling for the TTS only, the subtitle keeps the real word
        sspeed = {str(k): float(x) for k, x in dict(vj.get("scene_speed") or {}).items()}   # {"5": 1.3}: one scene's own speed; "4:am_michael": one voice in one scene
    except (OSError, ValueError, AttributeError):
        vspeed, vlead, sspeed, say, linepad = {}, {}, {}, {}, {}
    pipe = pipeline()
    audio_parts = [np.zeros(int(LEAD * SR), np.float32)]
    chars, cs, ce = [], [], []
    t = LEAD
    longs = []
    for k, text in enumerate(scenes):
        a, words, off = np.zeros(0, np.float32), [], 0.0
        for i, (v, line) in enumerate(parts_of[k]):
            spoken = line
            for a_, b_ in say.get(str(k + 1), {}).items():
                spoken = spoken.replace(a_, b_)
            la, lw = synth_scene(pipe, spoken, v, sspeed.get(f"{k + 1}:{v}", sspeed.get(str(k + 1), float(vspeed.get(v, speed)))))
            if v in vlead:   # optional silence before this voice's line (vN/voice.json "voice_lead")
                la = np.concatenate([np.zeros(int(float(vlead[v]) * SR), np.float32), la])
                lw = [(w, ws + float(vlead[v]), we + float(vlead[v])) for w, ws, we in lw]
            pad = float(linepad.get(f"{k + 1}:{i + 1}", 0))   # vN/voice.json "line_pad" {"3:2": 0.25}: silence before and after one line (scene:line, 1-based)
            if pad:
                la = np.concatenate([np.zeros(int(pad * SR), np.float32), la, np.zeros(int(pad * SR), np.float32)])
                lw = [(w, ws + pad, we + pad) for w, ws, we in lw]
            if i:
                a = np.concatenate([a, np.zeros(int(LINE_GAP * SR), np.float32)])
                off = len(a) / SR
            words += [(w, off + ws, off + we) for w, ws, we in lw]
            a = np.concatenate([a, la])
            off = len(a) / SR
        if len(parts_of[k]) > 1 or parts_of[k][0][0] != voice:
            print(f"scene {k + 1} voices: " + ", ".join(f"{v}: {t[:28]!r}" for v, t in parts_of[k]), flush=True)
        dur = len(a) / SR
        if dur <= 0:
            raise SystemExit(f"scene {k + 1}: Kokoro returned no sound for {text!r}; nothing was written")
        s, e = char_times(text, [(w, t + ws, t + we) for w, ws, we in words], t, t + dur)
        chars += list(text); cs += s; ce += e
        audio_parts.append(a)
        t += dur
        if k < len(scenes) - 1:
            chars.append("\n"); cs.append(t); ce.append(t + pause)
            audio_parts.append(np.zeros(int(pause * SR), np.float32))
            t += pause
        if dur + pause > SCENE_TARGET:
            longs.append((k + 1, dur + pause))
        print(f"scene {k + 1}: {dur:.2f}s, {len(words)} words", flush=True)
    audio = np.concatenate(audio_parts)
    assert "".join(chars) == "\n".join(scenes)
    wav = out.with_suffix(".kokoro.wav")
    sf.write(wav, audio, SR)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(out)], check=True)
    wav.unlink()
    align = {"characters": chars, "character_start_times_seconds": [round(x, 3) for x in cs],
             "character_end_times_seconds": [round(x, 3) for x in ce],
             "engine": f"kokoro-82M {voice} speed {speed}, made on this PC"}
    out.with_suffix(".alignment.json").write_text(json.dumps(align, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({t:.1f}s) and {out.with_suffix('.alignment.json').name}")
    print(f"total {t:.1f}s at speed {speed}; scenes over {SCENE_TARGET:.0f}s with pause: "
          + (", ".join(f"{k} ({d:.1f}s)" for k, d in longs) or "none"))
    return t


def main():
    p = argparse.ArgumentParser()
    p.add_argument("target", help="vN folder, or with --sample the text")
    p.add_argument("sample_out", nargs="?")
    p.add_argument("--sample", action="store_true")
    p.add_argument("--voice", default=VOICE)
    p.add_argument("--speed", type=float, help="voice speed 0.5-2.0 (default: vN/voice.json speed, else the team's, else 1.1)")
    p.add_argument("--pause", type=float, default=PAUSE)
    p.add_argument("--force", action="store_true", help="replace an existing voiceover.mp3 (the old one goes to vN/rejected/voice/)")
    p.add_argument("--scene", type=int, nargs="*", help="accepted for old commands; the whole episode is voiced again")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    if a.sample:
        if not a.sample_out:
            raise SystemExit("--sample needs the text and the output WAV")
        audio, _ = synth_scene(pipeline(), a.target, a.voice, a.speed if a.speed is not None else SPEED)
        sf.write(a.sample_out, audio, SR)
        print("wrote", a.sample_out)
        return
    vdir = Path(a.target).resolve()
    if not (vdir / "scenes.json").exists():
        raise SystemExit(f"{vdir / 'scenes.json'} does not exist")
    out = a.out or vdir / "voiceover.mp3"
    if out.exists() and not a.force and a.scene is None:
        raise SystemExit(f"{out} exists; episodes already voiced keep their voice (--force to redo: the old files go to rejected/voice/)")
    speed = episode_speed(vdir, a.speed)
    for old in set_aside(out):
        print("kept the old file as", old)
    voice_episode(vdir, a.voice, speed, a.pause, out)


if __name__ == "__main__":
    main()
