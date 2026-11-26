"""Build an exact English SRT for a Leo series video from the voice's own timings.

Long video (default): the voice starts at 0.0 s in render.py (no offset; a 1.6 s music tail follows),
so cue times are the ElevenLabs character timings of <vdir>/voiceover.alignment.json as they are.
Episodes rendered before the alignment file was kept (v1-v5) fall back to <vdir>/work/captions.ass,
the burned-in word-by-word captions render.py wrote from that same alignment just before the
render (one Dialogue per highlighted word: start = word start, end = next word / chunk end).

Short (--short): the Short is cut from the long voice by shorts.py (picked scenes, LEAD/BREATH
spans, GAP silences); its scenes come from <vdir>/short_plan.txt and the times are moved to their
place in the Short with shorts.segments(). Needs the alignment file (v6 onwards).

Cues: one sentence or short phrase each, at most 2 lines of at most 42 characters, at most ~6 s,
shown from the first word's start to just after the last word (never overlapping the next cue).

usage: make_srt.py <vdir> [--short] [--out FILE]      (default out: <vdir>/captions_en.srt or
                                                       <vdir>/short_captions_en.srt)
       make_srt.py <vdir> --scenes                    print each scene's start time (for chapters)
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "video_pipeline"))

LINE = 42          # max characters per line
MAX_CHARS = 2 * LINE
MAX_DUR = 6.0      # seconds per cue (split longer sentences at a comma or word boundary)
HOLD = 0.35        # keep a cue up this long after its last word ends (if the next cue allows)
MIN_DUR = 1.0      # stretch very short cues up to this (if the next cue allows)
GAP = 0.04         # minimal gap between two cues


def scenes_of(vdir):
    data = json.loads((vdir / "scenes.json").read_text(encoding="utf-8"))
    return [data[str(n)]["narration"] for n in range(1, len(data) + 1)]


def words_from_alignment(align):
    """(word, start, end) from character timings (same rule as assemble.words)."""
    out, cur, t0, t1 = [], "", None, None
    for ch, s, e in zip(align["characters"], align["character_start_times_seconds"],
                        align["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                out.append((cur, t0, t1))
            cur, t0 = "", None
            continue
        if not cur:
            t0 = s
        cur += ch
        t1 = e
    if cur:
        out.append((cur, t0, t1))
    return out


def _secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def words_from_ass(path, scenes):
    """(word, start, end) from render.py's word-highlight captions; the words are checked against
    the narration (ASS turned { } into ( ), so the narration's own spelling is used)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        f = line.split(",", 9)
        m = re.search(r"\{\\c&H00D7FF&\}(.*?)\{\\c&HFFFFFF&\}", f[9])
        if not m:
            continue
        out.append([m.group(1), _secs(f[1]), _secs(f[2])])
    ref = " ".join(scenes).split()
    if len(ref) != len(out):
        raise SystemExit(f"{path}: {len(out)} caption words vs {len(ref)} narration words")
    for w, r in zip(out, ref):
        if w[0] != r.replace("{", "(").replace("}", ")"):
            raise SystemExit(f"{path}: caption word {w[0]!r} != narration word {r!r}")
        w[0] = r
    return [tuple(w) for w in out]


def long_words(vdir):
    scenes = scenes_of(vdir)
    af = vdir / "voiceover.alignment.json"
    if af.exists():
        align = json.loads(af.read_text(encoding="utf-8"))
        assert "".join(align["characters"]) == "\n".join(scenes), "alignment text differs"
        return words_from_alignment(align), "alignment"
    return words_from_ass(vdir / "work" / "captions.ass", scenes), "captions.ass"


def scene_starts(vdir):
    """Start of each scene's first spoken word in the long video (scene 1 at 0.0)."""
    ws, _ = long_words(vdir)
    starts, k = [], 0
    for s in scenes_of(vdir):
        starts.append(ws[k][1])
        k += len(s.split())
    starts[0] = 0.0
    return starts


def short_words(vdir):
    import shorts  # shorts.py's own segment rule, so the times match the published cut
    import tempfile
    shorts.CTA = shorts.load_cta(vdir, Path(tempfile.mkdtemp(prefix="srt_")))   # short_cta.json: the CTA closes the cut
    scenes, align = shorts.load_video(vdir)
    head = (vdir / "short_plan.txt").read_text(encoding="utf-8").splitlines()[0]
    picks = [int(x) for x in re.search(r"scenes ([\d, ]+)", head).group(1).replace(" ", "").split(",")]
    if shorts.CTA:
        picks = picks[:-1] + [shorts.CTA["n_long"] + 1]
    segs, total = shorts.segments(scenes, align, picks)
    mf = vdir / "montage.json"
    if mf.exists():      # montage.json "splice": a sentence of a cut scene opens a picture block
        shorts.SPLICE.update({int(k): v for k, v in json.loads(mf.read_text(encoding="utf-8")).get("splice", {}).items()})
        shorts.CAPTION_TEXT.update(json.loads(mf.read_text(encoding="utf-8")).get("caption_text", {}))
        if shorts.SPLICE:
            segs, segs, total = shorts.splice(segs, scenes, align, total)
    ws = []
    for s in segs:
        p0, p1 = s["chars"]
        shift = s["at"] - s["src"][0]
        sub = {k: align[k][p0:p1] for k in ("characters", "character_start_times_seconds",
                                            "character_end_times_seconds")}
        ws += [(w, a + shift, b + shift) for w, a, b in words_from_alignment(shorts.fix_caption_text(sub))]
    return ws, total, picks


def split_phrase(ws):
    """Split one sentence (list of words) into cues that fit 2 lines and MAX_DUR."""
    text = " ".join(w[0] for w in ws)
    if (len(ws) == 1 or fits(text)) and ws[-1][2] - ws[0][1] <= MAX_DUR:
        return [ws]
    # best split point: after a comma/semicolon/colon/dash near the middle, else the word boundary
    # nearest the middle by characters
    total = len(text)
    best, best_score = None, None
    pos = 0
    for i in range(len(ws) - 1):
        pos += len(ws[i][0]) + 1
        punct = bool(re.search(r"[,;:—–-]$", ws[i][0]))
        score = abs(pos - total / 2) - (total * 0.25 if punct else 0)
        if best_score is None or score < best_score:
            best, best_score = i + 1, score
    return split_phrase(ws[:best]) + split_phrase(ws[best:])


def fits(text):
    """True when the text fits on at most 2 lines of at most LINE characters."""
    if len(text) <= LINE:
        return True
    words = text.split()
    return len(text) <= MAX_CHARS and any(
        len(" ".join(words[:i])) <= LINE and len(" ".join(words[i:])) <= LINE
        for i in range(1, len(words)))


def wrap(text):
    if len(text) <= LINE:
        return text
    words = text.split()
    pairs = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    pairs = [p for p in pairs if max(len(p[0]), len(p[1])) <= LINE]
    if not pairs:
        raise SystemExit(f"cue does not fit 2x{LINE}: {text}")
    # balanced lines, preferring a break after punctuation, never ending a line on "a"/"the"
    best = min(pairs, key=lambda p: max(len(p[0]), len(p[1]))
               - (8 if re.search(r"[,;:]$", p[0]) else 0)
               + (6 if p[0].split()[-1].lower() in {"a", "an", "the", "to", "of"} else 0))
    return "\n".join(best)


def cues(ws, end_limit):
    sentences, cur = [], []
    for w in ws:
        cur.append(w)
        if re.search(r"[.!?][\"')”’]*$", w[0]):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    groups = [g for s in sentences for g in split_phrase(s)]
    out = []
    for i, g in enumerate(groups):
        start = g[0][1]
        nxt = groups[i + 1][0][1] - GAP if i + 1 < len(groups) else end_limit
        end = min(max(g[-1][2] + HOLD, start + MIN_DUR), nxt)
        end = max(end, g[-1][2])
        out.append((start, end, wrap(" ".join(w[0] for w in g))))
    return out


def stamp(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(path, cs):
    body = "\n".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{t}\n" for i, (a, b, t) in
                     enumerate(cs, 1))
    path.write_text(body, encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("vdir", type=Path)
    p.add_argument("--short", action="store_true")
    p.add_argument("--scenes", action="store_true")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    vdir = a.vdir.resolve()
    if a.scenes:
        for n, t in enumerate(scene_starts(vdir), 1):
            print(f"{n:2d} {int(t) // 60}:{int(t) % 60:02d} ({t:6.2f}s) {scenes_of(vdir)[n - 1]}")
        return
    if a.short:
        ws, total, picks = short_words(vdir)
        cs = cues(ws, total)
        out = a.out or vdir / "short_captions_en.srt"
        src = f"short plan {picks}, {total:.2f}s"
    else:
        ws, src = long_words(vdir)
        cs = cues(ws, ws[-1][2] + 1.6)   # render.py: TAIL = 1.6 s after the voice
        out = a.out or vdir / "captions_en.srt"
    write_srt(out, cs)
    print(f"{out.name}: {len(cs)} cues from {src}, last ends {cs[-1][1]:.2f}s")


if __name__ == "__main__":
    main()
