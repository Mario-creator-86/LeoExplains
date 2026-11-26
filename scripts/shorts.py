"""Cut the vertical cuts (1080x1920) of a finished Leo series video: the YouTube Short and the
TikTok / Reels cut.

Both are a SHORT VERSION of the whole video: a hand-picked list of complete scenes (PLANS, or the
first line of the cut's existing plan file) that carries the arc question -> why it happens ->
twist -> what to do -> closing line. Nothing new is generated: the voiceover segments of those
scenes are cut on scene boundaries and concatenated (0.12 s fades, 0.25 s gaps; the very first
segment starts at 0.0 s with no fade-in), captions are rebuilt from exactly those segments'
alignment, and the pictures re-render the same scenes (render.py's sub-pixel camera moves, poses,
Veo clips and cross-dissolves) over the same music track (-40 LUFS before ducking) and the
effects of sfx.json that belong to the picked scenes.

YouTube Short (default 25-35 s since 2026-11-03, allowed 20-58 s): since 2026-11-01 the picture FILLS the 9:16 frame like the
TikTok cut (below), with the video's question as the hook text for the first ~2.5 s, captions in
the safe area, and in the last ~2 s a pointer to the full episode ("Full episode on the channel /
tap the link above the title" = the Short's Related video link).
Both cuts use their OWN vertical 9:16 images (vN/images_v/, Flow redraws each picked scene
vertically from its 16:9 image; owner decision 2026-11-01): nothing is cropped, no character is
ever cut, every frame is full screen. A picked scene without a vertical image stops the render.

TikTok cut (--tiktok, 20-35 s since 2026-11-03, experiment E-TT1) / Reels cut (--reels, 70-90 s): the picture FILLS the 9:16 frame: a
9:16 window of each 16:9 scene, centred on Leo (found by his yellow cap above his white head) with
a slow pan + gentle zoom; a bold hook text (<= ~8 words, from topics.json "tiktok_hook" / "hook"
or the scene-1 narration) in the top third from frame 1 to ~2.5 s; captions in the lower third
inside TikTok's safe area (clear of the right-hand buttons and the bottom caption block); and in
the last ~2 s an on-TikTok action line (follow / share / comment; never a YouTube pointer, that goes
in a pinned comment per PUBLISHING_SCHEDULE.md). Encoded 1080x1920 at a proper bitrate
(CRF 17, capped at 12 Mbps). `--small` additionally writes <out>_small.mp4 under 9.5 MB, only for
an upload tool that truly cannot take the full file.

The plan file is named after the output: short.mp4 -> short_plan.txt, short_tiktok.mp4 ->
short_tiktok_plan.txt, test_x.mp4 -> test_x_plan.txt (make_srt.py --short reads short_plan.txt).
The long video and its files are only read, never written.

usage: shorts.py <vdir> --plan [--tiktok]          write the plan file only
       shorts.py <vdir> [--scenes 1,4,21] [--out short.mp4]
       shorts.py <vdir> --tiktok [--scenes ...] [--out short_tiktok.mp4] [--hook "..."]
                 [--end "..."] [--small]
       shorts.py <vdir> [--tiktok] [--out FILE] --check <contact_sheet.png>
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont

import render
import safe_zones
import team_settings
from assemble import ass_time, captions, probe_duration, scene_starts
from render import FPS, XFADE, load

HERE = Path(__file__).resolve().parent
SW, SH = 1080, 1920           # Short frame
TAIL = 1.5                    # music-only tail; the end line shows during it
END_LEAD = 2.2                # the end line appears this long before the end (~2 s on screen)
# 2026-11-04: NO end line by default. vidIQ ("How to Escape EVERY YouTube Shorts View Jail"): "shorts should just
# end... don't ask them to subscribe, don't beg them to go watch your long-form videos". Viewers swipe at the
# sign-off, which hurts retention. Pass --end "..." to put a line back on one cut.
SHOW_END = False
NO_TITLE = False   # --notitle (2026-11-14): no on-screen title in the Short
FADE = 0.12                   # voice fade in/out per segment
FIRST_FADE = 0.01             # the first segment starts at 0.0 s: (almost) no fade-in
GAP = 0.25                    # silence between two segments
GAPS = {}                     # scene -> silence before it, from montage.json "gaps" (default GAP)
LEAD, BREATH = 0.04, 0.18     # segment = first char - LEAD .. last char + BREATH (never overlaps)
FONT = Path(os.environ.get("LEO_FONT", r"C:\Windows\Fonts\ariblk.ttf"))   # Arial Black (any bold TTF works)
EM = 1.411                    # Arial Black: ASS font size / em size (win ascent + descent)
# Scene numbers per Short, read as a mini-story (see <vdir>/short_plan.txt). Episodes not listed
# here use the first line of their existing plan file (short_plan.txt / short_tiktok_plan.txt).
PLANS = {
    "v1": [1, 4, 21, 22, 23, 24, 25, 30, 31, 39, 40],
    "v2": [1, 2, 5, 14, 19, 20, 26, 27, 28, 38, 39],
    "v3": [1, 15, 16, 17, 21, 22, 29, 30, 32, 39, 40],
    "v4": [1, 2, 3, 12, 13, 14, 15, 16, 17, 31, 34, 39, 40],
    "v5": [1, 5, 7, 8, 15, 20, 21, 22, 24, 37, 38, 39],
    "v6": [1, 2, 13, 14, 15, 16, 20, 21, 28, 29, 39, 40],
    "v7": [1, 6, 8, 10, 12, 14, 15, 16, 19, 30, 38, 40],
    "v8": [1, 4, 6, 15, 18, 20, 21, 30, 31, 37, 38, 39, 40],
    "v9": [1, 8, 14, 16, 18, 19, 20, 22, 23, 24, 35, 39, 40],
    "v10": [1, 2, 3, 7, 16, 18, 19, 20, 21, 30, 31, 39, 40],
    "v11": [1, 3, 4, 6, 7, 15, 19, 20, 34, 36, 37, 39, 40],
}
TIKTOK_PLANS = {}             # same idea for the 70-90 s cut (default: short_tiktok_plan.txt)
# Shorter on-screen hook where the full question would shrink below a bold size on 2 lines.
TITLES = {
    "v10": "Why Your Brain Replays Embarrassing Moments",
    "v64": "Doomscrolling and Your Mood",
    "v112": "The Tower Breaks",
    "v120": "Why is everything funnier together?",
    "v122": "Why does your cat meow at a closed door?",
}
CAP_STYLE = ("Style: Cap,Arial Black,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,"
             "100,100,1,0,1,7,3,8,90,90,1170,1")
TITLE_STYLE = ("Style: Title,Arial Black,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,"
               "0,100,100,1,0,1,8,3,8,60,60,170,1")
END_STYLE = ("Style: End,Arial Black,66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,"
             "100,100,1,0,1,6,3,8,60,60,1430,1")
END_TEXT = ("Full episode on the channel", "tap the link above the title")

# --- TikTok / Reels cut ------------------------------------------------------------------------
# Each platform gets its own file laid out for its own interface (owner 2026-11-03: "Tot contentul
# trebuie adaptat platformei"): short.mp4 for YouTube Shorts, short_tiktok.mp4 for TikTok and
# short_reels.mp4 (--reels: same scenes as the TikTok cut) for Instagram and Facebook Reels. The safe
# areas live in safe_zones.py. Captions are bottom-anchored just above that platform's covered bottom
# strip (owner 2026-11-03: lower than the old y ~1160, "poate cu 20%"), a second line grows upwards;
# hook and end line sit just under its covered top strip.
TT_HOOK_STYLE = ("Style: Hook,Arial Black,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,"
                 "0,100,100,1,0,1,10,4,8,80,80,{top},1")
TT_END_STYLE = ("Style: End,Arial Black,82,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,"
                "100,100,1,0,1,9,4,8,80,80,{top},1")
TT_HOOK_END = 2.5             # hook text on screen 0 .. 2.5 s (fade-out 0.3 s)
TT_HOOK_WORDS = 8
# On-TikTok actions for the last ~2 s, rotated by episode number (PUBLISHING_SCHEDULE.md §3)
TT_CTAS = ("Follow for more Leo", "Send this to someone who needs it",
           "Comment: does this happen to you?")
TT_ZOOM = (1.0, 1.06)
# 2026-11-14: Meta refused v78/short.mp4 as a Reel ("Video Transcoding Error: both HD and SD progressive failed to
# transcode") and v72/short.mp4 as a Story on 12.11. Its published Reels specification asks for a closed GOP of 2-5
# seconds and stereo AAC at 48 kHz, 128 kbps or more; our Shorts had a key frame every 250 frames (8.3 s, the x264
# default) and mono sound. The refused file and the accepted ones had the same parameters, so the cause is not
# proven; from now on the file is inside the specification: a key frame at least every 2 seconds, stereo sound.
GOP = ["-g", str(2 * FPS), "-keyint_min", str(FPS)]
STEREO = ["-ac", "2"]
TT_VIDEO = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-maxrate", "12M",
            "-bufsize", "24M", "-profile:v", "high", "-level:v", "4.2", "-tune", "animation", *GOP]


CTA = None    # set by make() when <vdir>/short_cta.json exists: the spoken follow CTA that closes the cut
LIFT_FILE = None   # set by make() to <vdir>/caption_lift.json
TITLE_OPTS = {}    # montage.json "title": {"size": max px, "top": MarginV px, "start": s, "end": s}; "cap_size": caption px


def load_video(vdir):
    if CTA:
        return CTA["scenes"], CTA["align"]
    return load_long(vdir)


def load_long(vdir):
    data = json.loads((vdir / "scenes.json").read_text(encoding="utf-8"))
    scenes = [data[str(n)]["narration"] for n in range(1, len(data) + 1)]
    align = json.loads((vdir / "voiceover.alignment.json").read_text(encoding="utf-8"))
    text = "\n".join(scenes)
    chars = "".join(align["characters"])
    if len(chars) > len(text) and chars.startswith(text + "\n"):
        # scenes dropped from the end of scenes.json after the voice was made (13.11: spoken CTA scene
        # removed): the voice file stays, the cuts use only the scenes that are left
        align = {k: v[:len(text)] for k, v in align.items()}
    assert "".join(align["characters"]) == text, "alignment text differs"
    return scenes, align


CTA_GAP = 0.5     # silence between the long voiceover and the CTA take in the combined voice file


def load_cta(vdir, tmp):
    """<vdir>/short_cta.json (the team's repair of 2026-11-06): the LAST picked scene of every cut is replaced
    by a spoken follow CTA (its own Fish take in <vdir>/cta/, the long's voiceover is only read), with a short
    text on screen. Returns a dict with the long's scenes + the CTA as one extra scene, the matching alignment
    and a combined voice file (long voiceover + CTA take), or None when the episode has no short_cta.json."""
    f = vdir / "short_cta.json"
    if not f.exists():
        return None
    spec = json.loads(f.read_text(encoding="utf-8"))
    scenes, align = load_long(vdir)
    cta_align = json.loads((vdir / spec["align"]).read_text(encoding="utf-8"))
    assert "".join(cta_align["characters"]) == spec["text"], "CTA alignment differs from its text"
    long_len = probe_duration(vdir / "voiceover.mp3")
    offset = long_len + CTA_GAP
    chars = align["characters"] + ["\n"] + cta_align["characters"]
    st = (align["character_start_times_seconds"] + [long_len]
          + [t + offset for t in cta_align["character_start_times_seconds"]])
    en = (align["character_end_times_seconds"] + [offset]
          + [t + offset for t in cta_align["character_end_times_seconds"]])
    voice = tmp / "voice_with_cta.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(vdir / "voiceover.mp3"), "-f", "lavfi", "-t",
                    f"{CTA_GAP}", "-i", "anullsrc=r=44100:cl=mono", "-i", str(vdir / spec["voice"]),
                    "-filter_complex", "[0:a]aresample=44100,aformat=channel_layouts=mono[a0];[2:a]aresample=44100,aformat=channel_layouts=mono[a2];"
                    "[a0][1:a][a2]concat=n=3:v=0:a=1", str(voice)], check=True)
    return {"spec": spec, "voice": voice, "scenes": scenes + [spec["text"]], "n_long": len(scenes),
            "align": {"characters": chars, "character_start_times_seconds": st,
                      "character_end_times_seconds": en}}


def plan_path(vdir, out_name):
    return vdir / (Path(out_name).stem + "_plan.txt")


def plan_scenes(vdir, tiktok, out_name=None):
    """The cut's scene list: PLANS / TIKTOK_PLANS, else the first line of its plan file. The Reels cut
    reads short_reels_plan.txt, falling back to the 70-90 s scenes of short_tiktok_plan.txt."""
    table, name = (TIKTOK_PLANS, "short_tiktok.mp4") if tiktok else (PLANS, "short.mp4")
    if vdir.name in table:
        return table[vdir.name]
    f = plan_path(vdir, name)
    if out_name == "short_reels.mp4" and plan_path(vdir, out_name).exists():
        f = plan_path(vdir, out_name)
    if f.exists():
        head = f.read_text(encoding="utf-8").splitlines()[0]
        m = re.search(r"scenes ([\d, ]+?)\s*\(", head)
        if m:
            return [int(x) for x in m.group(1).split(",")]
    raise SystemExit(f"no plan for {vdir.name}: pass --scenes (or add it to "
                     f"{'TIKTOK_PLANS' if tiktok else 'PLANS'})")


def segments(scenes, align, picks):
    """One voice segment per picked scene: source span, char span and place in the Short."""
    st, en = align["character_start_times_seconds"], align["character_end_times_seconds"]
    out, pos, t = [], [0], 0.0
    for s in scenes:
        pos.append(pos[-1] + len(s) + 1)
    for k, n in enumerate(picks):
        p0, p1 = pos[n - 1], pos[n - 1] + len(scenes[n - 1])
        a = max(0.0, st[p0] - LEAD)
        if n > 1:
            a = max(a, en[p0 - 2])                 # never include the previous scene's last sound
        b = en[p1 - 1] + BREATH
        if n < len(scenes):
            b = min(b, st[pos[n]])                 # never reach into the next scene
        out.append({"scene": n, "src": (a, b), "chars": (p0, p1), "at": t, "text": scenes[n - 1]})
        t += (b - a) + (GAPS.get(picks[k + 1], GAP) if k + 1 < len(picks) else 0)
    total = round((t + TAIL) * FPS) / FPS
    return out, total


CAPTION_TEXT = {}   # montage.json "caption_text" {"Your petting": "The petting"}: what the caption shows when it must match the spoken words


def fix_caption_text(sub):
    """Replace shown words in a character-timed caption dict (voice and timings stay as they are);
    a shorter replacement keeps the first characters' timings and drops the rest."""
    for old, new in CAPTION_TEXT.items():
        while True:
            i = "".join(sub["characters"]).find(old)
            if i < 0:
                break
            k, m = len(old), len(new)
            ends = sub["character_end_times_seconds"]
            last_end = ends[i + k - 1]
            for key in ("character_start_times_seconds", "character_end_times_seconds"):
                v = sub[key]
                v[i:i + k] = v[i:i + min(k, m)] + [v[i + k - 1]] * max(0, m - k)
            sub["characters"][i:i + k] = list(new)
            ends[i + m - 1] = last_end
    return sub


SPLICE = {}   # picture scene -> {"scene": cut scene, "text": sentence, "delay": s}, from montage.json "splice"


def splice(segs, scenes, align, total):
    """montage.json "splice" {"5": {"scene": 4, "text": "Now he's training you.", "delay": 2.0}}: the picture
    block of scene 5 opens with ONE sentence of the voice of a cut scene 4 (its picture is not used; the
    line plays over scene 5's picture), then scene 5's own voice follows. Returns (picture segs, audio segs,
    total): the picture segs keep one block per picked scene, the audio segs have the sentence as its own
    voice segment and the scene's voice moved after it; later blocks shift. sfx offsets of the scene
    count from the start of the block ("block_at")."""
    st, en = align["character_start_times_seconds"], align["character_end_times_seconds"]
    pos = [0]
    for s in scenes:
        pos.append(pos[-1] + len(s) + 1)
    pics, auds, shift = [], [], 0.0
    for sg in segs:
        sg = dict(sg, at=sg["at"] + shift)
        pics.append(sg)
        sp = SPLICE.get(sg["scene"])
        if not sp:
            auds.append(sg)
            continue
        n = sp["scene"]
        p0 = pos[n - 1] + scenes[n - 1].index(sp["text"])
        p1 = p0 + len(sp["text"])
        a = max(max(0.0, st[p0] - LEAD), en[p0 - 2])
        b = min(en[p1 - 1] + BREATH, st[p1 + 1]) if p1 + 1 < len(st) else en[p1 - 1] + BREATH
        block = sg["at"]
        pre = {"scene": n, "src": (a, b), "chars": (p0, p1), "at": block + sp.get("delay", 0.0),
               "text": sp["text"]}
        move = sp.get("delay", 0.0) + (b - a) + GAP
        auds += [pre, dict(sg, at=block + move, block_at=block)]
        shift += move
    return pics, auds, round((total + shift) * FPS) / FPS


def plan_text(vdir, segs, total, label="Short"):
    lines = [f"{vdir.name} {label} plan: scenes {', '.join(str(s.get('orig', s['scene'])) for s in segs)}"
             f"  ({len(segs)} scenes, {total:.1f} s)", ""]
    for s in segs:
        lines.append(f"[{s['at']:5.1f}s] " + ("CTA     " if s.get('pic') else f"scene {s['scene']:2d}") + f": {s['text']}")
    lines += ["", "As one read:", " ".join(s["text"] for s in segs)]
    return "\n".join(lines) + "\n"


def fit_lines(text, sizes, width, max_lines=2):
    """Split text into 1..max_lines balanced lines at the largest ASS size that fits width."""
    words = text.split()
    for size in sizes:
        font = ImageFont.truetype(str(FONT), round(size / EM))
        for n in range(1, max_lines + 1):
            if n > len(words):
                break
            best = None
            for cut in _cuts(len(words), n):
                ln = [" ".join(words[a:b]) for a, b in zip((0,) + cut, cut + (len(words),))]
                w = max(font.getlength(x) + len(x) for x in ln)
                if w > width:
                    continue
                # prefer breaks after a sentence/clause end, then the most balanced lines
                key = (-sum(bool(re.search(r"[.?!,:;]['\"’”]?$", x)) for x in ln[:-1]), w)
                if best is None or key < best[0]:
                    best = (key, ln)
            if best:
                return best[1], size
    return None


def _cuts(n, lines):
    if lines == 1:
        return [()]
    if lines == 2:
        return [(i,) for i in range(1, n)]
    return [(i, j) for i in range(1, n - 1) for j in range(i + 1, n)]


def hook_title(vdir):
    """The video's question (title before the parenthesis), on 2 balanced lines, sized to fit."""
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    text = TITLES.get(vdir.name) or re.split(r"\s*[(:|-]", meta["title"])[0].strip()
    text = re.sub(r"\s*#\w+", "", text).strip()     # never a "#Shorts" in the picture (15.11.2026)
    words = text.split()
    for size in range(TITLE_OPTS.get("size", 124), 60, -2):
        font = ImageFont.truetype(str(FONT), round(size / EM))
        best = min(((" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))),
                   key=lambda ln: max(font.getlength(x) for x in ln))
        if max(font.getlength(x) + len(x) for x in best) <= SW - 2 * 80:   # TT_HOOK_STYLE margins
            return best, size
    raise SystemExit("title does not fit on two lines: " + text)


def episode_number(vdir):
    m = re.fullmatch(r"v(\d+)", vdir.name)
    return int(m.group(1)) if m else 0


def tiktok_hook(vdir, scenes, override=None):
    """On-screen hook text for the TikTok cut, <= TT_HOOK_WORDS words, first match of:
    --hook; topics.json "tiktok_hook"; topics.json "hook" (or the scene-1 narration) when short
    enough; its question sentence when that stands alone (>= 6 words: "The room is full. So why
    do you still feel alone?" -> "Why do you still feel alone?"); the episode title, which is the
    plain search phrase ("Why You Feel Guilty When You Rest"); else the full hook, with a warning."""
    if override:
        return " ".join(override.split()).replace("{", "(").replace("}", ")")
    topic = {}
    tf = HERE / "topics.json"
    if tf.exists():
        topics = json.loads(tf.read_text(encoding="utf-8"))
        topic = next((t for t in topics if t.get("n") == episode_number(vdir)), {})
    hook = " ".join((topic.get("tiktok_hook") or topic.get("hook") or scenes[0]).split())
    picks = [hook]
    if not topic.get("tiktok_hook"):
        sents = [s.strip() for s in re.findall(r"[^.?!]+[.?!]+['\"’”]?", hook)]
        for q in [s for s in sents if s.endswith("?")][::-1]:
            q = re.sub(r"^(so|and|but|then|yet)\s+", "", q, flags=re.I)
            if len(q.split()) >= 6:
                picks.append(q[:1].upper() + q[1:])
        title = topic.get("title")
        if not title and (vdir / "meta.json").exists():
            title = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))["title"]
        if title:
            picks.append(re.split(r"\s+[(:|–—-]\s*|\s*\(", title)[0].strip())
    text = next((t for t in picks if len(t.split()) <= TT_HOOK_WORDS), None)
    if text is None:
        text = hook
        print(f"WARNING: hook has {len(hook.split())} words (> {TT_HOOK_WORDS}); pass --hook "
              f"or set topics.json \"tiktok_hook\"")
    return text.replace("{", "(").replace("}", ")")


def write_ass(path, align, segs, total, title, tiktok=False, end_text=None, profile="youtube_shorts"):
    """Captions rebuilt from exactly the picked segments (times moved to their Short position),
    plus the title (Short) or hook text (TikTok) and the end line."""
    sub = {"characters": [], "character_start_times_seconds": [],
           "character_end_times_seconds": []}
    for s in segs:
        if CTA and s.get("pic") and CTA["spec"].get("captions") is False:
            continue    # short_cta.json "captions": false: the follow line shows once, as the text card at the top
        p0, p1 = s["chars"]
        shift = s["at"] - s["src"][0]
        if sub["characters"]:          # whitespace separator: closes the last word
            t = sub["character_end_times_seconds"][-1]
            sub["characters"].append("\n")
            sub["character_start_times_seconds"].append(t)
            sub["character_end_times_seconds"].append(t)
        sub["characters"] += align["characters"][p0:p1]
        for k in ("character_start_times_seconds", "character_end_times_seconds"):
            sub[k] += [x + shift for x in align[k][p0:p1]]
    fix_caption_text(sub)
    captions(sub, path)
    ass = path.read_text(encoding="utf-8")
    ass = ass.replace("PlayResX: 1920", f"PlayResX: {SW}").replace("PlayResY: 1080",
                                                                  f"PlayResY: {SH}")
    if HIDE_CAP_SCENES:
        # montage.json "hide_caption_scenes": [1]: no bottom caption while those scenes' voice runs (the title/hook
        # text already shows the same sentence, 22.11.2026 critic: «aceeași frază de două ori»)
        def _ts(s):
            h, mi, sec = s.split(":")
            return int(h) * 3600 + int(mi) * 60 + float(sec)
        spans = [(sg["at"] - 0.05, sg["at"] + (sg["src"][1] - sg["src"][0])) for sg in segs
                 if sg["scene"] in HIDE_CAP_SCENES]
        ass = "\n".join(l for l in ass.split("\n")
                        if not (l.startswith("Dialogue: 0,") and ",Cap," in l
                                and any(a <= _ts(l.split(",")[1]) < b for a, b in spans)))
    if HOLD_CAP:
        _d = list(re.finditer(r"^(Dialogue: 0,[^,]+,)([^,]+)(,Cap,)", ass, flags=re.M))
        if _d:
            m = _d[-1]
            ass = ass[:m.start(2)] + ass_time(total) + ass[m.end(2):]
            if HOLD_MERGE and len(_d) > 1:
                # montage.json "hold_merge": the held caption shows the last two words' text together
                lines_ = ass.split("\n")
                idx = [i for i, l in enumerate(lines_) if l.startswith("Dialogue: 0,") and ",Cap," in l]
                a, b = lines_[idx[-2]], lines_[idx[-1]]
                ta = a.split(",,0,0,0,,", 1)[-1] if ",,0,0,0,," in a else None
                tb = b.split(",,0,0,0,,", 1)
                if ta and len(tb) == 2:
                    lines_[idx[-1]] = tb[0] + ",,0,0,0,," + ta + " " + tb[1]
                    ass = "\n".join(lines_)
    if HOLD_CAP or CLAMP_CAP:
        # a caption never runs over a picture cut: it ends on the frame before the next scene starts
        def _t(s):
            h, mi, sec = s.split(":")
            return int(h) * 3600 + int(mi) * 60 + float(sec)
        bnds = [sg["at"] for sg in segs[1:]]

        def _clamp(m):
            a, b = _t(m.group(2)), _t(m.group(3))
            for bd in bnds:
                if a < bd - 0.02 and b > bd - 0.01:
                    return m.group(1) + m.group(2) + "," + ass_time(bd - 0.034) + m.group(4)
            return m.group(0)
        ass = re.sub(r"(^Dialogue: 0,)([^,]+),([^,]+)(,Cap,)", _clamp, ass, flags=re.M)
    lift = json.loads(LIFT_FILE.read_text(encoding="utf-8")) if LIFT_FILE and LIFT_FILE.exists() else {}
    if lift:
        # caption_lift.json {"6": 740}: captions of those scenes sit that many px above the bottom
        # (clear of faces in a character row); keyed by source scene number
        def _secs(t):
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        spans = [(sg["at"], sg["at"] + (sg["src"][1] - sg["src"][0]), lift[str(sg["scene"])])
                 for sg in segs if str(sg["scene"]) in lift]

        def _lift(m):
            t0 = _secs(m.group(2))
            for a, b, v in spans:
                if a - 0.05 <= t0 < b:
                    return f"{m.group(1)}0,0,{v},,"
            return m.group(0)
        ass = re.sub(r"(^Dialogue: 0,([^,]+),[^,]+,Cap,,)0,0,0,,", _lift, ass, flags=re.M)
    lines, size = title
    end0 = ass_time(max(0.0, total - END_LEAD))
    top = TITLE_OPTS.get("top", safe_zones.top_text_margin(profile))
    t_on, t_off = TITLE_OPTS.get("start", 0.0), TITLE_OPTS.get("end", TT_HOOK_END)
    if "size" in TITLE_OPTS:
        size = min(size, TITLE_OPTS["size"])
    cta_lines = []
    if CTA:
        cta_lines, cta_size = (fit_lines(CTA["spec"]["screen"], range(110, 70, -2), SW - 2 * 80, 3)
                               or fit_lines(CTA["spec"]["screen"], range(70, 50, -2), SW - 2 * 80, 4))
    cap_style = safe_zones.caption_style(profile, TITLE_OPTS.get("cap_size", 84))
    if CAP_OUTLINE:     # --outline N: thicker black outline + shadow (direction 2026-11-13, warm backgrounds)
        cap_style = cap_style.replace(",1,7,3,2,", f",1,{CAP_OUTLINE},{max(3, CAP_OUTLINE // 2)},2,")
    styles = "\n".join([cap_style, TT_HOOK_STYLE.format(size=size, top=top),
                        TT_END_STYLE.format(top=top + 30)]
                       + ([TT_HOOK_STYLE.format(size=cta_size, top=top + 30).replace("Style: Hook", "Style: Cta")]
                          if CTA else []))
    if tiktok and BOX_TITLE and not NO_TITLE:
        # 2026-11-13 (review c839f4d9): TikTok/Reels cut with the same black title box as the
        # Short, no "#Shorts" in the picture, high enough to stay above the characters' heads
        bl, bsize = BOX_TITLE
        styles += ("\nStyle: Box,Arial Black,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,"
                   "0,100,100,1,0,1,0,0,8,60,60,0,1\nStyle: BoxBg,Arial,20,&H00000000,&H00000000,"
                   "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1" % bsize)
        ass = re.sub(r"^Style: Cap,.*$", styles, ass, flags=re.M)
        bfont = ImageFont.truetype(str(FONT), round(bsize / EM))
        bw = round(max(bfont.getlength(x) + len(x) for x in bl) + 2 * 40)
        bh = 2 * bsize + 2 * 20
        x0, y0 = (SW - bw) // 2, 110
        ass += (f"Dialogue: 0,{ass_time(0)},{ass_time(total)},BoxBg,,0,0,0,,"
                f"{{\\p1}}m {x0} {y0} l {x0 + bw} {y0} {x0 + bw} {y0 + bh} {x0} {y0 + bh}{{\\p0}}\n")
        ass += (f"Dialogue: 1,{ass_time(0)},{ass_time(total)},Box,,0,0,0,,"
                f"{{\\an8\\pos({SW // 2},{y0 + 20})}}" + "\\N".join(bl) + "\n")
    elif tiktok:
        ass = re.sub(r"^Style: Cap,.*$", styles, ass, flags=re.M)
        if not NO_TITLE:    # --notitle also removes the TikTok hook text (review d96305b2, 2026-11-22)
            ass += (f"Dialogue: 1,{ass_time(t_on)},{ass_time(t_off)},Hook,,0,0,0,,"
                    "{\\fad(0,300)}" + "\\N".join(lines) + "\n")
        if SHOW_END:
            ass += (f"Dialogue: 1,{end0},{ass_time(total)},End,,0,0,0,,"
                    "{\\fad(200,0)}" + end_text + "\n")
    else:
        # full-frame Short (2026-11-01): the title shows like the TikTok hook (first ~2.5 s), the
        # pointer to the full episode in the last ~2 s, captions in the same safe area
        l1, l2 = lines
        e1, e2 = end_text or END_TEXT
        if BOX_TITLE:
            # team test 2026-11-12: title in 2 lines at the top, white text in a solid black box
            # (BorderStyle 3), from the first frame to the end
            bl, bsize = BOX_TITLE
            # one even black rectangle (drawing, layer 0) behind the 2 lines, placed high (y 110+)
            # so it stays above the characters' heads (viewer review 2026-11-12)
            styles += ("\nStyle: Box,Arial Black,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,"
                       "0,100,100,1,0,1,0,0,8,60,60,0,1\nStyle: BoxBg,Arial,20,&H00000000,&H00000000,"
                       "&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1" % bsize)
        ass = re.sub(r"^Style: Cap,.*$", styles, ass, flags=re.M)
        if BOX_TITLE:
            bfont = ImageFont.truetype(str(FONT), round(bsize / EM))
            bw = round(max(bfont.getlength(x) + len(x) for x in bl) + 2 * 40)
            bh = 2 * bsize + 2 * 20
            x0, y0 = (SW - bw) // 2, 110
            ass += (f"Dialogue: 0,{ass_time(0)},{ass_time(total)},BoxBg,,0,0,0,,"
                    f"{{\\p1}}m {x0} {y0} l {x0 + bw} {y0} {x0 + bw} {y0 + bh} {x0} {y0 + bh}{{\\p0}}\n")
            ass += (f"Dialogue: 1,{ass_time(0)},{ass_time(total)},Box,,0,0,0,,"
                    f"{{\\an8\\pos({SW // 2},{y0 + 20})}}" + "\\N".join(bl) + "\n")
        elif not NO_TITLE:
            ass += (f"Dialogue: 1,{ass_time(t_on)},{ass_time(t_off)},Hook,,0,0,0,,"
                    "{\\fad(0,300)}" + f"{l1}\\N{l2}\n")
        if SHOW_END and not BOX_TITLE:
            ass += (f"Dialogue: 1,{end0},{ass_time(total)},End,,0,0,0,,"
                    "{\\fad(200,0)}" + e1 + "\\N{\\fs58}" + e2 + "\n")
    if CTA:
        # the follow CTA's text card: on screen from the CTA's first word to the end (>= 2 s)
        at = next(sg["at"] for sg in segs if sg.get("pic"))
        assert total - at >= 2.0, "CTA text would be on screen for less than 2 s"
        ass += (f"Dialogue: 2,{ass_time(at)},{ass_time(total)},Cta,,0,0,0,,"
                "{\\fad(200,0)}" + "\\N".join(cta_lines) + "\n")
    path.write_text(ass, encoding="utf-8")


# --- vertical pictures (owner decision 2026-11-01) -------------------------------------------------
# Both vertical cuts use their OWN 9:16 images: Flow redraws each picked scene vertically from its
# 16:9 image (vN/images_v/scene_NN.*, optional poses scene_NNb.* ..., optional 9:16 Veo clip
# scene_NN_clip.mp4). Nothing is cropped out of the 16:9 pictures, so no character is ever cut and
# every frame has the same full-screen format; a picked scene without a vertical image stops the
# render (no mixed formats).
def vertical_files(vdir, n):
    vimg = vdir / "images_v"
    clip = vimg / f"scene_{n:02d}_clip.mp4"
    files = sorted(vimg.glob(f"scene_{n:02d}.*"))[:1]
    for pose in "bcde":
        files += sorted(vimg.glob(f"scene_{n:02d}{pose}.*"))[:1]
    # 22.11.2026: a sharper copy made by upscale_scene.py (vN/images_v_hi/scene_NN.png, four times the size) is used
    # instead of the picture when it is not older than it; crops are fractions of the picture, so nothing else changes.
    files = [hi_copy(vdir, f) for f in files]
    return clip if clip.exists() else None, files


def hi_copy(vdir, f):
    hi = vdir / "images_v_hi" / (f.stem + ".png")
    if hi.exists() and hi.stat().st_mtime >= f.stat().st_mtime:
        print(f"{f.name}: sharper copy {hi.parent.name}/{hi.name}")
        return hi
    return f


def missing_vertical(vdir, picks):
    return [n for n in picks if vertical_files(vdir, n) == (None, [])]


def fill_frame(img, zoom, cx, cy):
    """A 9:16 window (full picture height / zoom) centred at (cx, cy), resampled sub-pixel to
    SW x SH; on a 9:16 picture at zoom 1 that is the whole picture."""
    sw, sh = img.size
    wh = sh / zoom
    ww = min(wh * SW / SH, sw)
    x0 = min(max(cx * sw - ww / 2, 0), sw - ww)
    y0 = min(max(cy * sh - wh / 2, 0), sh - wh)
    return img.transform((SW, SH), Image.AFFINE, (ww / SW, 0, x0, 0, wh / SH, y0),
                         resample=Image.BICUBIC)


def fill_scene_frames(imgs, nframes, move):
    """render.scene_frames in the 9:16 frame: poses snap with a short dissolve."""
    z0, z1, x0, x1, y0, y1 = move
    seg = nframes / len(imgs)
    for i in range(nframes):
        t = render.ease(i / max(1, nframes - 1))
        z, cx, cy = z0 + (z1 - z0) * t, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        p = min(len(imgs) - 1, int(i / seg))
        a = np.asarray(fill_frame(imgs[p], z, cx, cy), dtype=np.float32)
        into = i - p * seg
        if p > 0 and into < render.POSE_FADE:
            prev = np.asarray(fill_frame(imgs[p - 1], z, cx, cy), dtype=np.float32)
            k = (into + 1) / (render.POSE_FADE + 1)
            a = prev * (1 - k) + a * k
        yield a


def vertical_clip_frames(path, nframes, ss=0.0, speed=None):
    """render.clip_frames (same speed-up / hold rule) for a 9:16 clip. montage.json "clip" may start the
    clip later (ss, seconds) and set its own speed."""
    dur = probe_duration(path) - ss
    if speed is None:
        speed = min(1.5, max(1.0, dur / (nframes / FPS)))
    vf = (f"setpts=PTS/{speed:.4f},fps={FPS},scale={SW}:{SH}:force_original_aspect_ratio=increase,"
          f"crop={SW}:{SH}")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", str(path), "-an", "-vf", vf,
                          "-frames:v", str(nframes), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, SH, SW, 3)
    for k in range(nframes):
        yield frames[min(k, len(frames) - 1)].astype(np.float32)


MONTAGE = {}   # scene -> shots, from <vdir>/montage.json (editing pass: splits, punch-ins; never a shake)


CLIP_OPTS = {}   # scene -> {"ss": start s, "speed": x}, from montage.json "clip"
COVER = {}       # cut scene -> scene whose picture block continues over its voice, montage.json "cover"
CUTS = set()     # scenes that start with a hard cut (no cross-dissolve into them), montage.json "cuts"
END_FADE = 0.0   # montage.json "end_fade": seconds of audio fade-out at the very end
HOLD_MERGE = False
CLAMP_CAP = False  # montage.json "clamp_caption": every caption ends on the frame before its scene's cut
HOLD_CAP = False  # montage.json "hold_caption": the last caption stays until the last frame
HIDE_CAP_SCENES = set()   # montage.json "hide_caption_scenes": scenes whose voice shows no bottom caption
SFX_DB = {}      # sound file stem -> extra dB, montage.json "sfx_db" (sfx.json itself stays untouched)


def montage_frames(clip, files, nframes, shots, n=None):
    """One scene cut into several framings of the same picture or clip. Each shot:
    {"to": end as a fraction of the scene, "z": [start, end zoom], "c": [cx0, cy0, cx1, cy1],
    "ease": "in" for an accelerating push}. A "shake" key is ignored: the picture never shakes."""
    extra = sum(round(sh.get("skip", 0) * FPS) for sh in shots)   # frames left out by "skip"
    src = vertical_clip_frames(clip, nframes + extra, **CLIP_OPTS.get(n, {})) if clip else None
    img = None if clip else load(files[0])
    pics = {}
    edges = [0] + [round(sh["to"] * nframes) for sh in shots[:-1]] + [nframes]
    for k in range(nframes):
        j = next(i for i in range(len(shots)) if k < edges[i + 1] or i == len(shots) - 1)
        sh = shots[j]
        t = (k - edges[j]) / max(1, edges[j + 1] - edges[j] - 1)
        t = t * t if sh.get("ease") == "in" else render.ease(t)
        z = sh["z"][0] + (sh["z"][1] - sh["z"][0]) * t
        c = sh["c"]
        cx, cy = c[0] + (c[2] - c[0]) * t, c[1] + (c[3] - c[1]) * t
        # The picture never shakes (the Owner, 15.11.2026: «TREMURA IMAGINEA», «pune regulă că nu avem
        # voie să facem așa ceva»). A "shake" in montage.json is ignored: a shot moves with a smooth
        # push or pan, or it is cut. Do not bring the effect back.
        if src and k == edges[j] and sh.get("skip"):   # "skip": seconds of the clip left out at the start of this shot (a jump cut)
            for _ in range(round(sh["skip"] * FPS)):
                next(src)
        base = next(src) if src else img
        if sh.get("pic") and not clip:   # "pic": this shot shows another scene's picture (same montage, no new drawing)
            if sh["pic"] not in pics:
                pics[sh["pic"]] = load(vertical_files(files[0].parent.parent, sh["pic"])[1][0])
            base = pics[sh["pic"]]
        if clip:
            base = Image.fromarray(base.astype(np.uint8))
        yield np.asarray(fill_frame(base, z, cx, cy), dtype=np.float32)


def frames(vdir, segs, total):
    """render.py's scene loop over the picked scenes in their vertical pictures: each scene holds
    the screen for its voice segment (+ gap) with a gentle push in or out (alternating), poses
    snap, and it dissolves into the next picked scene."""
    bounds = [round(s["at"] * FPS) for s in segs] + [round(total * FPS)]
    bounds[0] = 0
    prev_tail, written, last = None, 0, None
    for j, s in enumerate(segs):
        n, final = s.get("pic", s["scene"]), j == len(segs) - 1
        xf = 0 if final or segs[j + 1].get("pic", segs[j + 1]["scene"]) in CUTS else XFADE
        nframes = bounds[j + 1] - bounds[j] + xf
        clip, files = vertical_files(vdir, n)
        if n in MONTAGE:
            gen = montage_frames(clip, files, nframes, MONTAGE[n], n)
        elif clip:
            gen = vertical_clip_frames(clip, nframes)
        else:
            z0, z1 = TT_ZOOM if j % 2 == 0 else TT_ZOOM[::-1]
            move = (z0, z1, 0.5, 0.5, 0.5, 0.48)
            if n in FOCUS:  # close-up on Leo: fixed window, tiny push
                fz, fx, fy, fz1, fx1, fy1 = FOCUS[n]   # fz1: end zoom (default a tiny push)
                move = (fz, fz1, fx, fx1, fy, fy1)
            gen = fill_scene_frames([load(f) for f in files], nframes, move)
        buf = []
        for k, fr in enumerate(gen):
            if prev_tail is not None and k < len(prev_tail):
                w = (k + 1) / (len(prev_tail) + 1)
                fr = prev_tail[k] * (1 - w) + fr * w
            if k < nframes - xf:
                last = fr.astype(np.uint8).tobytes()
                written += 1
                yield last
            else:
                buf.append(fr)
        prev_tail = buf
        print(f"scene {n}: {s['at']:.2f}s vertical {'clip' if clip else f'{len(files)} pose(s)'}",
              flush=True)
    while written < bounds[-1]:
        written += 1
        yield last


# --- "band" layout (2026-11-03, after the owner's example of a viral animated "What if…" TikTok) ----
# The 16:9 scene picture whole in a band across the middle of the 9:16 frame, the same picture blurred
# and darkened behind it, and the title in a large white box above it for the WHOLE video (late
# viewers and sound-off viewers always know the premise). Nothing is cropped from the picture and no
# vertical redraw is needed, so every episode can be cut this way. Captions sit under the band.
BAND_TOP = 650                # band y: 650..1257 (1080x607)
BAND_ZOOM = (1.0, 1.05)


def band_background(img):
    """The picture filling 9:16, blurred and darkened."""
    from PIL import ImageFilter, ImageEnhance
    sw, sh = img.size
    scale = SH / sh
    big = img.resize((round(sw * scale), SH), Image.BICUBIC)
    x0 = (big.width - SW) // 2
    bg = big.crop((x0, 0, x0 + SW, SH)).filter(ImageFilter.GaussianBlur(22))
    # 2026-11-04: the owner saw the old 0.55-dark fill as "black" on a phone under TikTok's own dark overlays.
    # Keep it bright and colourful (same picture, light blur), so the frame never reads as black bars.
    bg = ImageEnhance.Color(bg).enhance(1.15)
    return np.asarray(ImageEnhance.Brightness(bg).enhance(1.0), dtype=np.float32)


def band_title(title, profile):
    """RGBA overlay: the title in a white rounded box, centred above the band."""
    from PIL import ImageDraw
    over = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    top = safe_zones.top_text_margin(profile) + 20
    for size in range(70, 40, -2):
        f = ImageFont.truetype(str(FONT), size)
        lines, cur = [], ""
        for w in title.split():
            t = f"{cur} {w}".strip()
            if d.textlength(t, font=f) <= SW - 220 or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= 3 and top + 60 + len(lines) * size * 1.18 < BAND_TOP - 30:
            break
    lh = round(size * 1.18)
    bw = max(d.textlength(l, font=f) for l in lines) + 90
    bh = lh * len(lines) + 56
    x0 = (SW - bw) / 2
    d.rounded_rectangle([x0, top, x0 + bw, top + bh], radius=36, fill=(255, 255, 255, 250))
    y = top + 28
    for l in lines:
        d.text(((SW - d.textlength(l, font=f)) / 2, y), l, font=f, fill=(15, 15, 15, 255))
        y += lh
    a = np.asarray(over, dtype=np.float32)
    return a[..., :3], a[..., 3:4] / 255.0


def band_frames(vdir, segs, total, title, profile):
    """frames() for the band layout, from the episode's 16:9 scene pictures (vN/images)."""
    bounds = [round(s["at"] * FPS) for s in segs] + [round(total * FPS)]
    bounds[0] = 0
    t_rgb, t_a = band_title(title, profile)
    bh = round(SW * 9 / 16)
    prev_tail, written, last = None, 0, None
    for j, s in enumerate(segs):
        n, final = s.get("pic", s["scene"]), j == len(segs) - 1
        nframes = bounds[j + 1] - bounds[j] + (0 if final else XFADE)
        files = []
        for pose in ("", "b", "c", "d"):
            files += [p for p in sorted((vdir / "images").glob(f"scene_{n:02d}{pose}.*"))
                      if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")][:1]
        if not files:
            raise SystemExit(f"{vdir.name}: no 16:9 picture for scene {n}")
        imgs = [load(f) for f in files]
        bgs = [band_background(im) for im in imgs]
        z0, z1 = BAND_ZOOM if j % 2 == 0 else BAND_ZOOM[::-1]
        seg = nframes / len(imgs)
        buf = []
        for k in range(nframes):
            t = render.ease(k / max(1, nframes - 1))
            z = z0 + (z1 - z0) * t
            p = min(len(imgs) - 1, int(k / seg))
            im = imgs[p]
            w, h = im.size
            cw, ch = w / z, h / z
            fg = im.transform((SW, bh), Image.AFFINE,
                              (cw / SW, 0, (w - cw) / 2, 0, ch / bh, (h - ch) / 2), resample=Image.BICUBIC)
            fr = bgs[p].copy()
            fr[BAND_TOP:BAND_TOP + bh] = np.asarray(fg, dtype=np.float32)
            fr = fr * (1 - t_a) + t_rgb * t_a
            if prev_tail is not None and k < len(prev_tail):
                wgt = (k + 1) / (len(prev_tail) + 1)
                fr = prev_tail[k] * (1 - wgt) + fr * wgt
            if k < nframes - (0 if final else XFADE):
                last = fr.astype(np.uint8).tobytes()
                written += 1
                yield last
            else:
                buf.append(fr)
        prev_tail = buf
        print(f"scene {n}: {s['at']:.2f}s band, {len(imgs)} pose(s)", flush=True)
    while written < bounds[-1]:
        written += 1
        yield last


def mix(vdir, segs, total, vi, mi):
    """ffmpeg inputs, filter graph and its output labels ([v], [m], then one per effect) for the picked voice segments
    with the video's music bed (render.py's level logic and sidechain ducking) and the sound
    effects of <vdir>/sfx.json that belong to picked scenes (render.py: levelled to "lufs",
    default -26, placed at scene start + offset, an ambience trimmed to "length" with short fades;
    here moved to the scene's place in the Short and never longer than the scene's slot). vi / mi are the input
    indexes the voice and music will have; effect inputs follow the music."""
    choice = json.loads((vdir / "music.json").read_text(encoding="utf-8-sig"))
    music = choice.get("track", "yal-calm-angels-dream")
    lib = json.loads((render.MUSIC_DIR / "music_library.json").read_text(encoding="utf-8"))
    lufs = next((t.get("measured", {}).get("integrated_lufs") for t in lib["tracks"]
                 if t["id"] == music), None)
    music_db = (-40.0 - lufs) if lufs is not None else -35.0   # same level logic as render.py
    music_start = choice.get("start", 0.0)

    # voice: the picked segments, each faded and delayed to its place in the Short; the first
    # one starts at 0.0 s with no audible fade-in (the voice is there from frame 1)
    n = len(segs)
    parts = [f"[{vi}:a]asplit={n}" + "".join(f"[s{k}]" for k in range(n)) + ";"]
    for k, s in enumerate(segs):
        a, b = s["src"]
        d = b - a
        ms = round(s["at"] * 1000)
        fin = FIRST_FADE if k == 0 else FADE
        parts.append(f"[s{k}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={fin},afade=t=out:st={d - FADE:.3f}:d={FADE},"
                     f"adelay={ms}|{ms}[d{k}];")
    parts.append("".join(f"[d{k}]" for k in range(n))
                 # asetpts + apad=whole_dur (2026-11-12): with the voice files re-timed that day (1.1-1.2x, 0.30 s
                 # pauses) ffmpeg 9's amix emits frames WITHOUT timestamps once the first segment has ended (seen with
                 # ashowinfo on v67; v65 with the older voice has none). The old endless "apad,atrim" then never saw
                 # the end time and ffmpeg stalled for good, with no error (v66 at 18 MB, v67 at 27 MB). Timestamps
                 # are rebuilt from the sample count and the padding has a fixed length.
                 + f"amix=inputs={n}:duration=longest:normalize=0,asetpts=N/SR/TB,"
                 f"apad=whole_dur={total:.3f},atrim=0:{total:.3f},"
                 "asplit=2[v][key];")
    audio = ("".join(parts)
             + f"[{mi}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={music_db}dB,"
             f"afade=t=in:d=3,afade=t=out:st={max(0, total - 4):.2f}:d=4[m0];"
             f"[m0][key]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=700[m];"
             )
    ainputs = ["-i", str(CTA["voice"] if CTA else vdir / "voiceover.mp3"), "-ss", f"{music_start:.2f}", "-stream_loop",
               "-1", "-i", str(render.MUSIC_DIR / f"{music}.mp3")]
    try:
        sfx = render.load_sfx(vdir)                   # refuses a sound used twice (owner rule)
    except SystemExit:
        # an older episode whose long video predates the rule: a recut uses each sound once
        # (the first time it appears), so the cut itself still follows the rule
        raw = json.loads((vdir / "sfx.json").read_text(encoding="utf-8-sig"))
        seen, sfx = set(), []
        for fx in raw:
            path = (vdir / fx["file"]).resolve()
            keys = {re.sub(r"([_-]v?\d+)+$", "", path.stem.lower()), path.read_bytes()}
            if not keys & seen:
                sfx.append(fx)
            seen |= keys
        print(f"sfx: {len(raw) - len(sfx)} repeated sound(s) dropped for this cut")
    scenes, align = load_video(vdir)
    starts = scene_starts(scenes, align)
    where = {s["scene"]: s for s in segs}
    slot = {s["scene"]: (segs[j + 1]["at"] if j + 1 < len(segs) else total) - s["at"]
            for j, s in enumerate(segs)}
    mixin = ["[v]", "[m]"]
    for fx in sfx:
        s = where.get(fx["scene"])
        if s is None:
            continue
        # same position relative to the scene's voice as in the long video
        ms = max(0, round((s["at"] + starts[fx["scene"] - 1] - s["src"][0]
                           + fx.get("offset", 0.0)) * 1000))
        if "block_at" in s:     # montage.json "splice": the scene's sounds count from the start of its block
            ms = max(0, round((s["block_at"] + fx.get("offset", 0.0)) * 1000))
        k = len(mixin) - 2
        ainputs += ["-i", str(vdir / fx["file"])]
        trim = ""
        if fx.get("length"):
            ln = min(fx["length"], slot[fx["scene"]] + 0.3)
            trim = f",atrim=0:{ln:.2f},afade=t=in:d=0.4,afade=t=out:st={max(0, ln - 0.6):.2f}:d=0.6"
        audio += (f"[{mi + 1 + k}:a]loudnorm=I={fx.get('lufs', -26)}:TP=-3,aresample=48000{trim},"
                  f"volume={fx.get('db', 0) + render.SFX_TRIM_DB + SFX_DB.get(Path(fx['file']).stem, 0)}dB,adelay={ms}|{ms}[fx{k}];")
        mixin.append(f"[fx{k}]")
        print(f"sfx {fx['file']} (scene {fx['scene']}) at {ms / 1000:.2f}s")
    return ainputs, audio, mixin


BOX_TITLE = None
CAP_OUTLINE = 0   # from --outline
FOCUS = {}  # scene -> (zoom, cx, cy), from --focus


def make(vdir, picks, out, plan_file, tiktok=False, hook=None, end=None, profile=None, band=None):
    profile = profile or ("tiktok" if tiktok else "youtube_shorts")
    global CTA, TAIL, HOLD_CAP, END_FADE, HOLD_MERGE, CLAMP_CAP
    mfile = vdir / "montage.json"
    if mfile.exists():
        mj = json.loads(mfile.read_text(encoding="utf-8"))
        MONTAGE.update({int(k): v for k, v in mj.get("scenes", {}).items()})
        shaky = sum(1 for v in MONTAGE.values() for sh in v if sh.get("shake"))
        if shaky:
            print(f"montage.json: \"shake\" on {shaky} shot(s) IGNORED. The picture never shakes "
                  "(fixed rule of the Owner, 15.11.2026); take the key out of montage.json.", flush=True)
        TAIL = mj.get("tail", TAIL)
        GAPS.update({int(k): v for k, v in mj.get("gaps", {}).items()})
        CLIP_OPTS.update({int(k): v for k, v in mj.get("clip", {}).items()})
        SPLICE.update({int(k): v for k, v in mj.get("splice", {}).items()})
        CAPTION_TEXT.update(mj.get("caption_text", {}))
        CUTS.update(int(k) for k in mj.get("cuts", []))
        COVER.update({int(k): int(v) for k, v in mj.get("cover", {}).items()})
        TITLE_OPTS.update(mj.get("title", {}))
        if "cap_size" in mj:
            TITLE_OPTS["cap_size"] = mj["cap_size"]
        HIDE_CAP_SCENES.update(int(x) for x in mj.get("hide_caption_scenes", []))
        HOLD_MERGE = bool(mj.get("hold_merge", False))
        SFX_DB.update(mj.get("sfx_db", {}))
        HOLD_CAP = bool(mj.get("hold_caption", False))
        CLAMP_CAP = bool(mj.get("clamp_caption", False))
        END_FADE = float(mj.get("end_fade", 0.0))
    tmp = Path(tempfile.mkdtemp(prefix="short_"))
    CTA = load_cta(vdir, tmp)
    global LIFT_FILE
    LIFT_FILE = vdir / "caption_lift.json"
    if CTA:
        # follow-CTA repair (short_cta.json): the cut's last scene is replaced by the spoken CTA, drawn over
        # that scene's picture; always the full 9:16 frame with one picture on screen, never the band layout
        if band:
            print("short_cta.json: full-frame layout required, --band ignored")
            band = None
        last = picks[-1]
        picks = picks[:-1] + [CTA["n_long"] + 1]
    scenes, align = load_video(vdir)
    segs, total = segments(scenes, align, picks)
    if CTA:
        segs[-1].update(pic=last, orig=last)
    asegs = segs          # audio segments: with montage.json "splice" one more than the picture blocks
    if SPLICE:
        segs, asegs, total = splice(segs, scenes, align, total)
    if COVER:   # montage.json "cover" {"2": 1}: the voice of scene 2 stays, its picture is scene 1's block continuing
        # a value LOWER than the scene: the previous block keeps going over this voice; a value HIGHER than
        # the scene ("3": 4): the later scene's picture block starts here, at this scene's voice
        kept, carry = [], None
        for sg in segs:
            tgt = COVER.get(sg["scene"])
            if tgt is None:
                kept.append(sg if carry is None else dict(sg, at=carry))
                carry = None
            elif tgt > sg["scene"] and carry is None:
                carry = sg["at"]
        segs = kept
    plan = plan_text(vdir, asegs, total, "TikTok cut" if tiktok else "Short")
    if SPLICE and asegs is not segs:
        plan = plan.replace("scenes " + ", ".join(str(s.get("orig", s["scene"])) for s in asegs),
                            "scenes " + ", ".join(str(s.get("orig", s["scene"])) for s in segs), 1)
    plan_file.write_text(plan, encoding="utf-8")
    print(f"{vdir.name}: scenes {picks}, {'tiktok cut' if tiktok else 'short'} {total:.2f}s"
          f" -> {plan_file.name}")
    lo, hi = LENGTHS[profile]
    if not lo <= total <= hi:
        print(f"WARNING: {profile} cut is {total:.1f} s; the window is {lo}-{hi} s")
    if out is None:
        return
    missing = [] if band else missing_vertical(vdir, [sg.get("pic", sg["scene"]) for sg in segs])
    if missing:
        raise SystemExit(f"{vdir.name}: no vertical image in {vdir.name}/images_v for scenes "
                         f"{missing}; generate them in Flow first (flow_prompts/build_prompts.py "
                         f"--vertical), no mixed formats")

    ass = tmp / "short.ass"
    if tiktok:
        text = tiktok_hook(vdir, scenes, hook)
        fit = (fit_lines(text, range(124, 86, -2), SW - 2 * 80, 2)
               or fit_lines(text, range(110, 70, -2), SW - 2 * 80, 3))
        if fit is None:
            raise SystemExit("hook does not fit on three lines: " + text)
        end_text = end or TT_CTAS[episode_number(vdir) % len(TT_CTAS)]
        print(f"hook: {' / '.join(fit[0])} (size {fit[1]}); end: {end_text}")
        write_ass(ass, align, asegs, total, fit, tiktok=True, end_text=end_text, profile=profile)
    else:
        write_ass(ass, align, asegs, total, hook_title(vdir),
                  end_text=tuple(end.split("|", 1)) if end and "|" in end else None, profile=profile)
    if band:
        # band layout: the title box is the hook (on screen all the time), no end line; captions
        # top-anchored just under the band, clear of the platform's right-hand buttons
        txt = ass.read_text(encoding="utf-8")
        txt = re.sub(r"^Dialogue: 1,[^\n]*,(Hook|End),[^\n]*\n?", "", txt, flags=re.M)
        right = safe_zones.PROFILES[profile]["right"]
        txt = re.sub(r"^Style: Cap,.*$",
                     "Style: Cap,Arial Black,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,"
                     "100,100,1,0,1,7,3,8,90,%d,%d,1" % (right, BAND_TOP + round(SW * 9 / 16) + 30),
                     txt, flags=re.M)
        ass.write_text(txt, encoding="utf-8")
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:")
    # both cuts are full screen from their own vertical pictures (owner decision 2026-11-01)
    size = f"{SW}x{SH}"
    video = f"[0:v]subtitles='{ass_arg}',format=yuv420p[vo]"
    vcodec = TT_VIDEO
    ainputs, audio, mixin = mix(vdir, asegs, total, 1, 2)
    # render.py's loudnorm -14, after a gentle 3:1 compressor that tames the voice's peaks so
    # loudnorm can actually reach the target (plain loudnorm stops near -15.6 LUFS here); the
    # effects join after it, like render.py, so pauses don't lift them
    audio += render.sfx_after_loudnorm(
        mixin[:2], mixin[2:],
        "acompressor=threshold=0.05:ratio=3:attack=5:release=150:makeup=1,loudnorm=I=-14:TP=-1.5:LRA=11")
    if END_FADE and audio.rstrip().endswith("[a]"):   # montage.json "end_fade": no hard cut of the last sound
        audio = audio.rstrip()[:-3] + f"[a0];[a0]afade=t=out:st={total - END_FADE:.3f}:d={END_FADE}[a]"
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", size, "-r", str(FPS),
           "-i", "-", *ainputs,
           "-filter_complex", f"{video};{audio}", "-map", "[vo]", "-map", "[a]",
           *vcodec, "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", *STEREO,
           "-movflags", "+faststart", "-t", f"{total:.3f}", str(part_of(out))]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in (band_frames(vdir, segs, total, band, profile) if band else frames(vdir, segs, total)):
        ff.stdin.write(fr)
    ff.stdin.close()
    if ff.wait():
        raise SystemExit("ffmpeg failed")
    put_in_place(out)
    print("wrote", out)


# 22.11.2026 (the agent's request after v124): a render that is cut used to leave a file of 0 or 3,700 bytes over
# a good one. Every video is now written beside its place as <name>.part.mp4, measured with ffprobe, and only a
# file that plays takes the place of the old one. A cut render leaves the old file as it was.
def part_of(out):
    out = Path(out)
    return out.with_name(out.stem + ".part" + out.suffix)


def put_in_place(out):
    import os
    out = Path(out)
    part = part_of(out)
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(part)], capture_output=True, text=True).stdout.strip())
    except ValueError:
        dur = 0.0
    if dur <= 0 or part.stat().st_size < 10000:
        raise SystemExit(f"FILE: BROKEN {part.name} ({part.stat().st_size} bytes, ffprobe {dur:.2f} s); {out.name} was left as it was")
    os.replace(part, out)
    print(f"FILE: ok {out.name} {dur:.2f} s {out.stat().st_size} bytes")


def passed_critic(vdir, name):
    """True when vN/stranger.json has, for this file as it is now, three yes of the critic (like, stay, back)."""
    try:
        import json as _json
        from datetime import datetime as _dt
        rec = _json.loads((vdir / "stranger.json").read_text(encoding="utf-8-sig")).get(name)
        if not rec or not all(rec.get(k, {}).get("yes") is True for k in ("like", "stay", "back")):
            return False
        seen = _dt.fromisoformat(str(rec["file_mtime"]).replace("Z", "+00:00")).timestamp()
        return abs(seen - (vdir / name).stat().st_mtime) < 2.5
    except Exception:
        return False


def small_copy(src, dst, target_mb=9.0):
    """A copy under ~9.5 MB, ONLY for an upload tool that cannot take the full file (TikTok
    itself takes the full 1080x1920 file): 1080x1920, or 720x1280 when the bitrate would drop
    below ~1200 kbps."""
    dur = probe_duration(src)
    kbps = int(target_mb * 8192 / dur) - 135      # room for 128 kbps stereo sound (Meta's Reels specification)
    scale = [] if kbps >= 1200 else ["-vf", "scale=720:1280:flags=lanczos"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *scale, "-c:v", "libx264",
                    "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
                    "-bufsize", f"{kbps * 2}k", *GOP, "-c:a", "aac", "-b:a", "128k", "-ar", "48000", *STEREO,
                    "-movflags", "+faststart", str(part_of(dst))], check=True)
    put_in_place(dst)
    print("wrote", dst, f"{dst.stat().st_size / 1e6:.1f} MB")


# Length window per cut (seconds). TikTok: experiment E-TT1 from 2026-11-03 (Claude, with the owner's full
# autonomy): 20-35 s instead of 61-90 s. Our 70-90 s cuts all stopped at TikTok's ~250-view first test
# pool, Creator Rewards (the reason for >= 1 min) is not open in Romania, and completion is what widens
# the pool. Reels keep 61-90 s (one variable at a time).
LENGTHS = {"youtube_shorts": (20, 58), "tiktok": (20, 35), "reels": (61, 90),
           # full "What if" story on TikTok (2026-11-03: viral what-if stories there run minutes, in parts)
           "tiktok_long": (60, 600)}
# The team owns the lengths (owner 2026-11-12: format and duration are theirs to choose):
# team_settings.json {"lengths": {"tiktok": [20, 60]}} replaces the [shortest, longest] seconds of that cut.
for _cut, _span in team_settings.section("lengths").items():
    if (_cut not in LENGTHS or not isinstance(_span, list) or len(_span) != 2
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in _span)
            or not 1 <= _span[0] < _span[1] <= 3600):
        raise SystemExit(f"team_settings.json: lengths.{_cut} = {_span!r} must be [shortest, longest] seconds "
                         f"for one of {sorted(LENGTHS)}")
    LENGTHS[_cut] = (float(_span[0]), float(_span[1]))


def check(path, sheet, tiktok=False, profile=None):
    """ffprobe facts, integrated loudness, voice at 0.0 s and a contact sheet (one frame every
    3 s); for the TikTok cut also <sheet>_hook.png (frames at 0.0-3.0 s every 0.5 s)."""
    pr = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,bit_rate,duration:format=duration,"
         "bit_rate,size", "-of", "json", str(path)], capture_output=True, text=True,
        check=True).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    a = next(s for s in pr["streams"] if s["codec_type"] == "audio")
    dur = float(pr["format"]["duration"])
    log = subprocess.run(["ffmpeg", "-nostats", "-i", str(path), "-filter_complex",
                          "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)[-1])
    vd = subprocess.run(["ffmpeg", "-nostats", "-t", "0.3", "-i", str(path), "-af", "volumedetect",
                         "-f", "null", "-"], capture_output=True, text=True).stderr
    start_db = float(re.findall(r"max_volume:\s+(-?[\d.]+) dB", vd)[-1])
    n = int(dur // 3) + 1
    cols = 6
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
                    f"fps=1/3,scale=270:480,tile={cols}x{-(-n // cols)}:padding=6:color=gray",
                    "-frames:v", "1", str(sheet)], check=True)
    profile = profile or ("tiktok" if tiktok else "youtube_shorts")
    lo, hi = LENGTHS[profile]
    dur_ok = lo <= dur <= hi
    # the sound must run to the end of the picture (2026-11-12: a cut whose audio stopped 1.7 s early passed)
    audio_gap = round(float(v.get("duration") or dur) - float(a.get("duration") or dur), 2)
    ok = ((v["width"], v["height"]) == (SW, SH) and dur_ok and -16.5 <= lufs <= -13.5
          and start_db > -30 and audio_gap <= 0.3)
    facts = {"video": f"{v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']}",
             "video_kbps": round(int(v.get("bit_rate") or pr["format"]["bit_rate"]) / 1000),
             "size_mb": round(int(pr["format"]["size"]) / 1e6, 1),
             "audio": a["codec_name"], "duration": round(dur, 2), "lufs": lufs,
             "true_peak_dbfs": peak, "first_0.3s_max_db": start_db, "sheet": str(sheet)}
    if audio_gap > 0.3:
        facts["audio_ends_early_s"] = audio_gap     # render again: the sound stops before the picture
    if tiktok:
        hook = Path(sheet).with_name(Path(sheet).stem + "_hook.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", "3.4", "-i", str(path), "-vf",
                        "fps=2,scale=360:640,tile=7x1:padding=6:color=gray", "-frames:v", "1",
                        str(hook)], check=True)
        facts["hook_sheet"] = str(hook)
        facts["length_window"] = f"{lo}-{hi} s ({profile})"
    facts["ok"] = ok
    print(json.dumps(facts, indent=1))
    return ok


def main():
    p = argparse.ArgumentParser()
    p.add_argument("vdir", type=Path)
    p.add_argument("--scenes", help="comma-separated scene numbers (default: the cut's plan)")
    p.add_argument("--plan", action="store_true", help="only write the plan file")
    p.add_argument("--tiktok", action="store_true",
                   help="the 70-90 s TikTok/Reels cut: full-frame 9:16, hook text, TikTok CTA")
    p.add_argument("--reels", action="store_true",
                   help="the Instagram/Facebook Reels cut: the TikTok cut's scenes, laid out for the "
                        "Reels interface (safe_zones.py) -> short_reels.mp4")
    p.add_argument("--out", default=None, help="default short.mp4 / short_tiktok.mp4 / short_reels.mp4")
    p.add_argument("--long", action="store_true",
                   help="TikTok: the full-length story (60-600 s window), e.g. a whole What-if episode in band layout")
    p.add_argument("--band", metavar="TITLE",
                   help="band layout: the 16:9 pictures in a band across the middle, blurred fill, TITLE "
                        "in a white box on top for the whole video (no vertical pictures needed)")
    p.add_argument("--title", help="Short: on-screen title, 2 lines at the top, white text in a "
                                   "solid black box from the first frame (team test 2026-11-12)")
    p.add_argument("--xfade", type=int, default=None,
                   help="frames of cross-dissolve between scenes (default render.XFADE = 10; 0 = hard cut)")
    p.add_argument("--focus", help="vertical cuts: per-scene close-up on Leo, "
                   "'6=1.35,0.62,0.67;8=...' (scene=zoom,cx,cy[,end zoom[,end cx,end cy]])")
    p.add_argument("--outline", type=int, default=0,
                   help="caption outline width in px (default 7); shadow follows")
    p.add_argument("--hook", help="TikTok: on-screen hook text (default: topics.json)")
    p.add_argument("--end", help="TikTok: end line (default: rotating CTA); "
                                 "Short: 'line 1|line 2'")
    p.add_argument("--notitle", action="store_true", help="Short: no on-screen title at all")
    p.add_argument("--small", action="store_true",
                   help="TikTok: also write <out>_small.mp4 under 9.5 MB (upload tools only)")
    p.add_argument("--check", type=Path, help="only check <vdir>/<out>, writing this sheet")
    p.add_argument("--again", action="store_true",
                   help="render again a file that has already passed the critic (its answers become stale)")
    a = p.parse_args()
    vdir = a.vdir.resolve()
    if a.reels:
        a.tiktok = True
    global SHOW_END, BOX_TITLE, XFADE, CAP_OUTLINE, NO_TITLE
    NO_TITLE = a.notitle
    CAP_OUTLINE = a.outline
    if a.xfade is not None:
        XFADE = a.xfade
    if a.focus:
        for item in a.focus.split(";"):
            sc, vals = item.split("=")
            fz, fx, fy, *rest = (float(v) for v in vals.split(","))
            # optional: end zoom, then end cx, cy (a slow pan)
            fz1 = rest[0] if rest else fz * 1.02
            FOCUS[int(sc)] = (fz, fx, fy, fz1, rest[1] if len(rest) > 2 else fx,
                              rest[2] if len(rest) > 2 else fy)
    if a.title:
        if "|" in a.title:      # explicit line break: "line 1|line 2" (never shown literally)
            fit = None
            parts = [x.strip() for x in a.title.split("|")]
            for size in range(100, 60, -2):
                f = ImageFont.truetype(str(FONT), round(size / EM))
                if len(parts) == 2 and max(f.getlength(x) + len(x) for x in parts) <= SW - 2 * 60 - 2 * 24:
                    fit = (parts, size)
                    break
        else:
            fit = fit_lines(a.title, range(100, 60, -2), SW - 2 * 60 - 2 * 24, 2)
        if fit is None or len(fit[0]) != 2:
            raise SystemExit("--title must fit on exactly 2 lines: " + a.title)
        BOX_TITLE = fit
    if a.end:
        SHOW_END = True
    profile = "reels" if a.reels else ("tiktok" if a.tiktok else "youtube_shorts")
    if a.long:
        a.tiktok, profile = True, "tiktok_long"
    out_name = a.out or ("short_reels.mp4" if a.reels else "short_tiktok.mp4" if a.tiktok
                         else "short.mp4")
    if a.check:
        raise SystemExit(0 if check(vdir / out_name, a.check, a.tiktok, profile) else 1)
    # 15.11.2026 13:21: `shorts.py v108 --small` without --tiktok ignored --small and rendered short.mp4 again, minutes after it had
    # passed the critic and had been posted; the answers became stale and the episode could not be closed. Without --tiktok, --small
    # now only compresses the existing file into short_tiktok_small.mp4 and renders nothing.
    if a.small and not a.tiktok and not a.plan:
        src = vdir / out_name
        if not src.exists():
            raise SystemExit(f"{src} does not exist: --small without --tiktok only compresses an existing file; render it first")
        small_copy(src, vdir / "short_tiktok_small.mp4")
        print(f"compressed {src.name} into short_tiktok_small.mp4; {src.name} was NOT rendered again")
        return
    # A file that has passed the critic at the file stage (vN/stranger.json, three yes, for the file as it is now) is not rendered
    # again by accident: a run whose request really asks for a new edit adds --again.
    if not a.plan and not a.again and passed_critic(vdir, out_name):
        raise SystemExit(f"{out_name} has passed the critic at the file stage (stranger.json) and may already be posted: rendering it "
                         "again makes that answer stale. If the request of this run asks for a new edit of this file, add --again; "
                         "for a small copy for TikTok use --small alone.")
    picks = ([int(x) for x in a.scenes.split(",")] if a.scenes
             else plan_scenes(vdir, a.tiktok, out_name))
    out = vdir / out_name
    make(vdir, picks, None if a.plan else out, plan_path(vdir, out_name), a.tiktok, a.hook,
         a.end, profile, a.band)
    if a.small and a.tiktok and not a.plan:
        small_copy(out, out.with_name(out.stem + "_small.mp4"))


if __name__ == "__main__":
    main()
