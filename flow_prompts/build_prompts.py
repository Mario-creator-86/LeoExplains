"""Build per-scene Flow image prompts (poses A, b, c, d) for Leo episodes.

usage: python build_prompts.py 15 19 20 21 22 23 14   -> writes prompts_all.json next to this file
       python build_prompts.py --vertical 15 19        -> prompts_vertical.json: one 9:16 prompt per
              scene of the Short + TikTok plans (vN/short_plan.txt, vN/short_tiktok_plan.txt must exist);
              the images go to vN/images_v/scene_NN.jpeg (reference: vN/images/scene_NN.*)
Pose b/c/d prompts describe LEO'S ACTION (taken from the scene description), never camera moves.
"""
import re, json, pathlib, sys

base = pathlib.Path(__file__).resolve().parent.parent / "scripts"   # the production folder (shorts.py, episode folders vN/)
LEO = ("Leo, a simple stickman with a big round white head, black outline, simple expressive eyes and mouth, "
       "a yellow baseball cap worn backwards with a small tuft of brown hair, thin black line body and limbs, "
       "round black hands and black oval feet,")
STYLE = ("IMAGES ONLY, do NOT create any videos. Generate ONE 16:9 image. Leo must look exactly like the attached "
         "character sheet (stickman with a yellow backwards cap and brown hair tuft): a simple stickman with a big round "
         "white head, black outline, simple expressive eyes and mouth, a yellow baseball cap worn backwards with a small "
         "tuft of brown hair, thin black line body and limbs, round black hands and black oval feet. Style: Detailed 2D "
         "cartoon explainer illustration, vibrant colors, clean bold outlines, soft lighting, cinematic composition, 16:9, "
         "no text. Rich detailed background environment, never plain white. Exactly ONE Leo in the image, NO glasses, "
         "no new accessories. ")
TAIL = " Exactly ONE Leo, NO glasses, no new accessories, no extra characters, no text."
# Scenes whose description doesn't name Leo show OTHER characters (a friend across town, a colleague at home).
# The generic STYLE forced "exactly one Leo" into them (v22 11-14, v23 10/11/15/16/25/32 on 2026-11-01), so those
# scenes get their own wording: no Leo, no cap, the sheet only for the drawing style.
NOLEO = ("IMAGES ONLY, do NOT create any videos. Generate ONE 16:9 image. LEO IS NOT IN THIS SCENE: do not draw Leo, "
         "no stickman with a yellow cap or a brown hair tuft, and no cap anywhere in the picture. Use the attached "
         "character sheet ONLY for the drawing style of the stickmen (big round white head, black outline, simple "
         "expressive eyes and mouth, thin black line body and limbs, round black hands, black oval feet); the stickmen "
         "here have plain round heads with NO cap and NO hair. Style: Detailed 2D cartoon explainer illustration, vibrant "
         "colors, clean bold outlines, soft lighting, cinematic composition, 16:9, no text. Rich detailed background "
         "environment, never plain white. Every character has exactly two arms and two legs attached to the body. ")
NOLEO_TAIL = " No Leo, no yellow cap, no hair tuft, NO glasses, no extra characters, no text."


def has_leo(desc: str) -> bool:
    return bool(re.search(r"\bLeo\b", desc))
STAGE = {"b": "the NEXT natural moment", "c": "a LATER moment (further along than the next keyframe)",
         "d": "the END of the action (his final reaction)"}


def leo_action(desc: str) -> str:
    """Sentences of the scene description that describe what Leo does (no camera language)."""
    sents = re.split(r"(?<=[.!?])\s+", desc)
    keep = [s for s in sents if re.search(r"\bLeo\b|\bhe\b|\bhis\b|\bhim\b", s)]
    keep = [s for s in keep if not re.match(r"(?i)^(dramatic |slow |fast |wide |close[- ]up|camera|pan|zoom|push|tilt)", s)]
    txt = " ".join(keep) or desc
    txt = re.sub(r"(?i)\b(camera|close-up|close up|push-in|pan(ning)?|zoom(ing)?|tilt(ing)?|tracking shot|wide shot)\b[^.]*\.", "", txt)
    return txt.strip()


def build(n: int) -> dict:
    scenes = json.load(open(base / f"v{n}" / "scenes.json", encoding="utf-8"))
    v = {}
    for k, sc in scenes.items():
        s = int(k)
        desc = sc["image"].strip()
        desc = desc.replace(LEO, "Leo").replace("Leo, Leo", "Leo")
        # drop a trailing style sentence that scenes.json repeats per scene
        desc = re.sub(r"\s*Detailed 2D cartoon.*$", "", desc, flags=re.S).strip().rstrip(".")
        # 2026-11-12: some scenes.json (v77) describe the vertical cut ("Medium-close, vertical 9:16, Leo fills half the
        # frame ... no letterbox, no blurred bars"); a 16:9 prompt must not ask for vertical framing.
        desc = re.sub(r"(?i)\s*Close-up or medium-close,? vertical 9:16, Leo fills about half of the frame;[^.]*(?:\.|$)", "", desc)
        desc = re.sub(r"(?i)Medium-close,? vertical 9:16, Leo fills half the frame\.", "Medium shot, 16:9, Leo clearly visible.", desc)
        desc = re.sub(r"(?i),?\s*vertical 9:16,?", " 16:9,", desc)
        if not has_leo(desc):
            v[s] = {"A": NOLEO + "SCENE: " + desc + "."}
            for p, st in STAGE.items():
                v[s][p] = ("IMAGES ONLY, do NOT create any videos. Generate ONE 16:9 image: the SAME image as the attached "
                           "scene image (first reference), redrawn identically. Keep the background, framing, camera angle, "
                           "lighting, colors, props, and every character's size and position EXACTLY the same. Change ONLY "
                           "the main character's pose, arms, head and facial expression to " + st + " of what they are "
                           "doing, clearly different from the reference. What happens: " + desc + "." + NOLEO_TAIL)
            continue
        v[s] = {"A": STYLE + "SCENE: " + desc + "."}
        act = leo_action(desc)
        for p, st in STAGE.items():
            v[s][p] = ("IMAGES ONLY, do NOT create any videos. Generate ONE 16:9 image: the SAME image as the attached scene "
                       "image (first reference), redrawn identically. Keep the background, framing, camera angle, lighting, "
                       "colors, props, and Leo's size and position on screen EXACTLY the same (Leo stays in the same spot, "
                       "same scale; no camera move, no zoom). Change ONLY Leo's pose, arms, head and facial expression to "
                       + st + " of what he is doing in this scene, clearly different from the reference. What Leo is doing: "
                       + act + " Keep Leo identical to the character sheet (second reference: yellow backwards cap, brown tuft)."
                       + TAIL)
    # Place continuity (owner 2026-11-12, looking at v72 in Flow: three pictures of the same bedroom came out with the
    # furniture in three different spots, because only the character sheet was attached). Every scene of a place after
    # its first one asks for the finished picture of that first scene as one more reference. vN/cast.json lists the places.
    try:
        cast = json.load(open(base / f"v{n}" / "cast.json", encoding="utf-8-sig"))
        places = [p for p in cast.get("places", []) if isinstance(p, dict) and isinstance(p.get("scenes"), list)]
    except (OSError, ValueError, AttributeError):
        places = []
    for p in places:
        sc = sorted({int(x) for x in p["scenes"] if str(x).isdigit() and int(x) in v})
        for s in sc[1:]:
            v[s]["A"] += (f" PLACE CONTINUITY: attach ALSO the finished image of scene {sc[0]} "
                          f"(v{n}/images/scene_{sc[0]:02d}) as one more reference, after the character sheet. It shows "
                          f"this same place ({p.get('name') or p.get('id')}). Keep the place identical to it: the same "
                          "furniture in the same positions, the same walls, colours and props, except a detail that this "
                          "scene's description changes on purpose (for example the time shown on a clock): there, follow "
                          "the description. Change only the pose, the expression and the moment; do not copy the pose "
                          "from that image.")
    missing = [s for s in range(1, 41) if s not in v]
    print(n, len(v), "missing", missing)
    return {str(s): v[s] for s in sorted(v)}


VERTICAL = ("IMAGES ONLY, do NOT create any videos. Generate ONE VERTICAL 9:16 (portrait) image. Redraw the attached "
            "scene image (first reference) as a tall vertical picture: the SAME scene, the same characters doing the "
            "same thing, the same background, style, colors, lighting and props. Every character is shown COMPLETE: "
            "whole head, cap, body, arms, hands and feet inside the picture, nobody touches or crosses the edges; "
            "characters stand closer together if needed. Frame it close (2026-11-12: half of the v72 verticals "
            "showed Leo at a third of the picture height above a strip of empty floor): the main character is at "
            "least half of the picture height. Crop the sides of the room instead of adding empty wall above or "
            "empty floor below; the furniture nearest to the character stays visible. "
            "Leo identical to the character sheet (second reference: yellow backwards cap, brown tuft). "
            "Exactly ONE Leo, NO glasses, no new accessories, no extra characters, no text. SCENE: ")


def vertical(n: int) -> dict:
    """Pose-A vertical prompts for every scene the Short and the TikTok/Reels cut use (their plan
    files), owner decision 2026-11-01: the vertical cuts get their own 9:16 pictures."""
    sys.path.insert(0, str(base))
    import shorts
    vdir = base / f"v{n}"
    picks = set()
    for plan in ("short_plan.txt", "short_tiktok_plan.txt", "short_reels_plan.txt", "recut_plan.txt"):
        # recut_plan.txt (2026-11-03): scenes of a new 20-35 s TikTok recut of an already-posted
        # episode; older episodes have only that plan, their first Shorts were made before 9:16 images
        f = vdir / plan
        if f.exists():
            m = re.search(r"scenes ([\d, ]+?)\s*\(", f.read_text(encoding="utf-8").splitlines()[0])
            if m:
                picks |= {int(x) for x in m.group(1).split(",")}
    if (vdir / "recut_plan.txt").exists() and not (vdir / "images_v").exists():
        # an already-posted episode: only the recut's scenes, not its old cropped Short's
        f = (vdir / "recut_plan.txt").read_text(encoding="utf-8").splitlines()[0]
        picks = {int(x) for x in re.search(r"scenes ([\d, ]+?)\s*\(", f).group(1).split(",")}
    if not picks:
        raise SystemExit(f"v{n}: no plan file with scenes")
    picks = sorted(picks)
    scenes = json.load(open(vdir / "scenes.json", encoding="utf-8"))
    out = {}
    for s in picks:
        desc = scenes[str(s)]["image"].strip().replace(LEO, "Leo").replace("Leo, Leo", "Leo")
        desc = re.sub(r"\s*Detailed 2D cartoon.*$", "", desc, flags=re.S).strip().rstrip(".")
        # 2026-11-13: scenes.json (v88) still carried "Leo fills about half of the frame; no wide shots", which contradicts
        # the 60-65% rule written in the same text; drop it.
        desc = re.sub(r"(?i)\s*Close-up or medium-close,? vertical 9:16, Leo fills about half of the frame;[^.]*(?:\.|$)", "", desc).strip()
        if has_leo(desc):
            out[str(s)] = VERTICAL + desc + "."
        else:
            out[str(s)] = (VERTICAL.split(" Leo identical")[0] + " Use the character sheet ONLY for the drawing style."
                           + NOLEO_TAIL + " SCENE: " + desc + ".")
    have = shorts.missing_vertical(vdir, picks)
    print(n, "vertical scenes", picks, "| still missing in images_v:", have)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--vertical":
        out = {str(int(a.lstrip("v"))): vertical(int(a.lstrip("v"))) for a in args[1:]}
        p = pathlib.Path(__file__).with_name("prompts_vertical.json")
    else:
        out = {str(int(a.lstrip("v"))): build(int(a.lstrip("v"))) for a in args}
        p = pathlib.Path(__file__).with_name("prompts_all.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("wrote", p)
