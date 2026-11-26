"""Remove a lead-in phrase (e.g. "Here's the twist: ") from an episode's narration without re-voicing it.

Cuts the phrase out of voiceover.mp3 using the character timings in voiceover.alignment.json,
shifts the later timings, and updates scenes.json + narration.txt to match (next letter capitalised).
Originals are kept in <vdir>/pre_cut/.

usage: cut_phrase.py <vdir> [regex]   (default regex: the "twist" lead-ins the owner banned on 2026-10-31)
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT = r"(?:But )?(?:Here[’']s the twist|Here comes the twist|Here is the twist|Plot twist)[:,]?\s+"
FADE = 0.02


def main():
    vdir = Path(sys.argv[1]).resolve()
    pattern = re.compile(sys.argv[2] if len(sys.argv) > 2 else DEFAULT, re.I)
    align_p, voice_p = vdir / "voiceover.alignment.json", vdir / "voiceover.mp3"
    scenes_p, narr_p = vdir / "scenes.json", vdir / "narration.txt"
    align = json.loads(align_p.read_text(encoding="utf-8"))
    chars, st, en = (align["characters"], align["character_start_times_seconds"],
                     align["character_end_times_seconds"])
    m = pattern.search("".join(chars))
    if not m:
        raise SystemExit(f"{vdir.name}: phrase not found, nothing to do")
    i, j = m.start(), m.end()                 # chars[i:j] go; chars[j] is the next word's first letter
    t0, t1 = st[i], st[j]
    print(f"{vdir.name}: cutting {''.join(chars[i:j])!r} at {t0:.3f}-{t1:.3f} s")

    backup = vdir / "pre_cut"
    backup.mkdir(exist_ok=True)
    for p in (align_p, voice_p, scenes_p, narr_p):
        if not (backup / p.name).exists():
            shutil.copy2(p, backup / p.name)

    src = backup / "voiceover.mp3"
    tmp = vdir / "voiceover.cut.mp3"
    graph = (f"[0]atrim=0:{t0},asetpts=N/SR/TB[a];[0]atrim=start={t1},asetpts=N/SR/TB[b];"
             f"[a][b]acrossfade=d={FADE}[o]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", graph,
                    "-map", "[o]", "-c:a", "libmp3lame", "-b:a", "128k", str(tmp)], check=True)
    tmp.replace(voice_p)

    shift = (t1 - t0) + FADE
    nxt = chars[j].upper()
    align["characters"] = chars[:i] + [nxt] + chars[j + 1:]
    align["character_start_times_seconds"] = st[:i] + [round(t - shift, 3) for t in st[j:]]
    align["character_end_times_seconds"] = en[:i] + [round(t - shift, 3) for t in en[j:]]
    align_p.write_text(json.dumps(align, ensure_ascii=False), encoding="utf-8")

    def fix(text):
        return pattern.sub(lambda mm: "", text, count=1)

    def cap_after(old, new):  # capitalise the first letter where the phrase was removed
        k = pattern.search(old).start()
        return new[:k] + new[k:k + 1].upper() + new[k + 1:]

    data = json.loads(scenes_p.read_text(encoding="utf-8"))
    for key, sc in data.items():
        if pattern.search(sc.get("narration", "")):
            sc["narration"] = cap_after(sc["narration"], fix(sc["narration"]))
            print(f"  scene {key}: {sc['narration']}")
            break
    scenes_p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    narr = narr_p.read_text(encoding="utf-8")
    if pattern.search(narr):
        narr_p.write_text(cap_after(narr, fix(narr)), encoding="utf-8")


if __name__ == "__main__":
    main()
