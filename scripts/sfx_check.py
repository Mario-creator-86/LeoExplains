"""Check <vdir>/sfx.json for the vertical Short WITHOUT rendering, and print where each sound falls in the Short.

    python sfx_check.py vN            (the Short: short.mp4)
    python sfx_check.py vN --tiktok   (the TikTok cut)
    python sfx_check.py vN --plan     (no sfx.json needed: when each scene starts and ends in the Short, and what is said)
    python sfx_check.py vN --find "my phone buzzed"   (the exact "offset" of those words in their scene, from the voice timings)

Made on 2026-11-14 for the job leo-sfx (the one agent: "o lucrare leo-sfx care scrie vN/sfx.json pentru Short").
It uses the renderer's own functions (shorts.py, render.py), so what it prints is what the next render will do:
  - every entry has "file" and "scene", the file exists;
  - the same sound is used at most once (owner rule 2026-11-01, render.load_sfx);
  - the scene is one of the Short's scenes (the renderer silently skips a sound of a scene that is not in the cut);
  - the sound starts inside its scene's slot; an ambience ("length") is cut at the end of that slot;
  - a level is never louder than a spot effect (-26 LUFS); "db" is never above 0;
  - never more than two sounds at the same moment (SFX_BRIEF.md).
Exit 0 = the renderer will take the file as it is. Exit 1 = something to repair (listed). Nothing is written.
"""
import json
import subprocess
import os
import sys
from pathlib import Path

import render
import shorts

FFPROBE = os.environ.get("FFPROBE", "ffprobe")   # path to ffprobe, default: on PATH
MAX_LUFS = -26       # a spot effect; an ambience is quieter (-32 .. -34)
MAX_AT_ONCE = 2


def seconds(path):
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return None


def cut(vdir, tiktok=False):
    """(scenes, align, picks, segs, total, starts, note) of the cut, as the renderer plans it. An episode made as a
    Short that was never rendered has no plan file yet: every scene is in the cut, as its first render will have it."""
    scenes, align = shorts.load_video(vdir)
    note = None
    try:
        picks = shorts.plan_scenes(vdir, tiktok)
    except SystemExit:
        if not (vdir / "short_episode.json").exists():
            raise
        picks = list(range(1, len(scenes) + 1))
        note = f"no plan file yet (the Short was never rendered): all {len(scenes)} scenes, as its first render will have them"
    segs, total = shorts.segments(scenes, align, picks)
    return scenes, align, picks, segs, total, shorts.scene_starts(scenes, align), note


def plan(vdir, tiktok=False):
    scenes, align, picks, segs, total, starts, note = cut(vdir, tiktok)
    for j, s in enumerate(segs):
        end = segs[j + 1]["at"] if j + 1 < len(segs) else total
        voice = s["at"] + starts[s["scene"] - 1] - s["src"][0]
        print(f"scene {s['scene']:2d}: {s['at']:6.2f}-{end:6.2f} s (slot {end - s['at']:4.1f} s; the voice begins at {voice:6.2f} s = offset 0)  | {s['text']}")
    if note:
        print("note:", note)
    print(f"Short: {len(segs)} scenes, {total:.1f} s")


def find(vdir, words, tiktok=False):
    """Where the words are said: the scene, and the "offset" (seconds after that scene's voice begins) at which the
    first of them starts and the last one ends, from voiceover.alignment.json. First run of leo-sfx, 2026-11-14: the
    offsets were estimated from the text because there was no way to read the time of a word."""
    scenes, align, picks, segs, total, starts, note = cut(vdir, tiktok)
    st, en = align["character_start_times_seconds"], align["character_end_times_seconds"]
    pos, hits = [0], 0
    for s in scenes:
        pos.append(pos[-1] + len(s) + 1)
    needle = " ".join(words.lower().split())
    for n, text in enumerate(scenes, 1):
        low, i = text.lower(), -1
        while True:
            i = low.find(needle, i + 1)
            if i < 0:
                break
            a, b = pos[n - 1] + i, pos[n - 1] + i + len(needle) - 1
            where = next((s for s in segs if s["scene"] == n), None)
            in_short = f"{where['at'] + st[a] - where['src'][0]:.2f} s in the Short" if where else "not in this cut"
            print(f'scene {n}: "offset" {st[a] - starts[n - 1]:.2f} (the words end at {en[b] - starts[n - 1]:.2f}); {in_short}  | {text}')
            hits += 1
    if not hits:
        print(f'"{words}" is not said in any scene (the search is on the exact words of scenes.json)')
    return hits


def check(vdir, tiktok=False):
    """(rows, problems, notes): rows = one dict per sound that the renderer will place."""
    f = vdir / "sfx.json"
    if not f.exists():
        return [], [f"{f} does not exist"], []
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        return [], [f"sfx.json is not valid JSON: {e}"], []
    if not isinstance(raw, list):
        return [], ["sfx.json must be a JSON list of entries"], []
    problems, notes = [], []
    for i, fx in enumerate(raw, 1):
        if not isinstance(fx, dict):
            problems.append(f"entry {i}: not an object")
            continue
        for k in ("file", "scene"):
            if k not in fx:
                problems.append(f'entry {i}: no "{k}"')
        if "file" in fx and not (vdir / fx["file"]).exists():
            problems.append(f"entry {i}: file not found: {fx['file']}")
        if "scene" in fx and not isinstance(fx["scene"], int):
            problems.append(f'entry {i}: "scene" must be a whole number, the scene number of scenes.json')
    if problems:
        return [], problems, notes
    try:
        sfx = render.load_sfx(vdir)                       # refuses a sound used twice (owner rule)
    except SystemExit as e:
        return [], [str(e)], notes
    scenes, align, picks, segs, total, starts, cut_note = cut(vdir, tiktok)
    if cut_note:
        notes.append(cut_note)
    where = {s["scene"]: s for s in segs}
    slot = {s["scene"]: (segs[j + 1]["at"] if j + 1 < len(segs) else total) - s["at"] for j, s in enumerate(segs)}
    rows, skipped = [], []
    short_only = (vdir / "short_episode.json").exists()
    for i, fx in enumerate(sfx, 1):
        n = fx["scene"]
        s = where.get(n)
        if s is None:
            # an episode made as a Short has every scene in the cut, so this is a mistake there; in a Short cut from a
            # long video it is normal (the sound belongs to the long video)
            (problems if short_only else skipped).append(
                f"entry {i} ({fx['file']}): scene {n} is not in this cut (scenes {picks}); the renderer skips it")
            continue
        at = max(0.0, s["at"] + starts[n - 1] - s["src"][0] + fx.get("offset", 0.0))
        slot_end = s["at"] + slot[n]
        dur = seconds(vdir / fx["file"])
        if fx.get("length"):
            ln = min(float(fx["length"]), slot[n] + 0.3)
            if dur is not None and dur + 0.05 < ln:
                notes.append(f"entry {i} ({fx['file']}): the file is {dur:.1f} s, shorter than its \"length\" {ln:.1f} s; it ends early")
                ln = dur
        else:
            ln = dur if dur is not None else 1.5
            if at + ln > slot_end + 1.0:
                notes.append(f"entry {i} ({fx['file']}): runs {at + ln - slot_end:.1f} s into the next scene; pick a shorter sound or an earlier offset")
        if at >= slot_end:
            problems.append(f"entry {i} ({fx['file']}): starts at {at:.2f} s, after scene {n} has ended ({slot_end:.2f} s); lower \"offset\"")
        if at + 0.05 >= total:
            problems.append(f"entry {i} ({fx['file']}): starts at the very end of the Short ({total:.2f} s)")
        lufs = fx.get("lufs", -26)
        if lufs > MAX_LUFS:
            problems.append(f"entry {i} ({fx['file']}): \"lufs\" {lufs} is louder than a spot effect ({MAX_LUFS}); the voice must dominate")
        if fx.get("db", 0) > 0:
            problems.append(f"entry {i} ({fx['file']}): \"db\" {fx['db']} raises the effect; use 0 or a negative number")
        rows.append({"n": i, "file": fx["file"], "scene": n, "at": at, "end": min(at + ln, total), "lufs": lufs,
                     "db": fx.get("db", 0), "ambience": bool(fx.get("length")),
                     "slot": (s["at"], slot_end), "text": s["text"]})
    # never more than two sounds at one moment
    edges = sorted([(r["at"], 1) for r in rows] + [(r["end"], -1) for r in rows], key=lambda e: (e[0], e[1]))
    live = worst = 0
    worst_at = 0.0
    for t, d in edges:
        live += d
        if live > worst:
            worst, worst_at = live, t
    if worst > MAX_AT_ONCE:
        problems.append(f"{worst} sounds play together at {worst_at:.2f} s; at most {MAX_AT_ONCE} at one moment")
    if skipped:
        notes.append(f"{len(skipped)} sound(s) belong to scenes of the long video that are not in this cut; the renderer skips them")
    return rows, problems, notes + [f"Short: {len(segs)} scenes, {total:.1f} s; effects are lowered by a further "
                                    f"{abs(render.SFX_TRIM_DB):.0f} dB by the renderer (SFX_TRIM_DB)"]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")][:1]
    if not args:
        sys.exit(__doc__)
    vdir = Path(args[0])
    if "--plan" in sys.argv:
        plan(vdir, "--tiktok" in sys.argv)
        return
    if "--find" in sys.argv:
        words = " ".join(a for a in sys.argv[sys.argv.index("--find") + 1:] if not a.startswith("--"))
        sys.exit(0 if words and find(vdir, words, "--tiktok" in sys.argv) else 1)
    rows, problems, notes = check(vdir, "--tiktok" in sys.argv)
    for r in rows:
        kind = "ambience" if r["ambience"] else "spot"
        print(f"{r['at']:6.2f}-{r['end']:6.2f} s  scene {r['scene']:2d} ({r['slot'][0]:5.1f}-{r['slot'][1]:5.1f} s)  "
              f"{kind:8s} {r['lufs']:>4} LUFS {r['db']:+.0f} dB  {r['file']}   | {r['text'][:60]}")
    for n in notes:
        print("note:", n)
    if problems:
        print("\nTO REPAIR:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print(f"\nOK: {len(rows)} sound(s); the renderer will take {vdir.name}/sfx.json as it is.")


if __name__ == "__main__":
    main()
