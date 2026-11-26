"""Helpers for the Leo stickman series.

usage: series_tool.py parse <n>      -> v<n>/scenes.json, v<n>/meta.json, v<n>/narration.txt, v<n>/batch_XX.txt
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEO = ("Leo, a simple stickman with a big round white head, black outline, simple expressive eyes "
       "and mouth, a yellow baseball cap worn backwards with a small tuft of brown hair, thin black "
       "line body and limbs, round black hands and black oval feet")
STYLE = ("Detailed 2D cartoon explainer illustration, vibrant colors, clean bold outlines, soft "
         "lighting, cinematic composition, 16:9, no text")
BATCH = 6


def field(text, name):
    m = re.search(rf"^{name}:\s*(.*?)(?=^\s*[A-Z]+:|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def parse(n):
    vdir = HERE / f"v{n}"
    text = (vdir / "chatgpt.md").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    head, _, rest = text.partition("SCENE 1\n")
    rest = "SCENE 1\n" + rest
    meta = {
        "title": field(head, "TITLE"),
        "description": field(head, "DESCRIPTION"),
        "hashtags": field(head, "HASHTAGS"),
        "tags": field(head, "TAGS"),
        "thumbnail": field(head.split("THUMBNAIL:", 1)[-1], "IMAGE") if "THUMBNAIL:" in head else "",
        "thumbnail_text": "",
    }
    th = head.split("THUMBNAIL:", 1)[-1]
    mt = re.search(r"(?i)text:\s*\"?([^\"\n]+)\"?", th)
    if mt:
        meta["thumbnail_text"] = mt.group(1).strip().strip('"')
    scenes = {}
    for m in re.finditer(r"^SCENE (\d+)\n(.*?)(?=^SCENE \d+\n|\Z)", rest, re.S | re.M):
        body = m.group(2)
        scenes[int(m.group(1))] = {
            "narration": field(body, "NARRATION"),
            "image": field(body, "IMAGE"),
            "motion": field(body, "MOTION"),
        }
        fish = field(body, "PERFORMANCE")   # Fish Drama 3 version: the narration + tested direction tags
        if fish and fish != scenes[int(m.group(1))]["narration"]:
            scenes[int(m.group(1))]["fish"] = fish
    nums = sorted(scenes)
    assert nums == list(range(1, len(nums) + 1)), nums
    (vdir / "scenes.json").write_text(json.dumps({str(k): v for k, v in scenes.items()},
                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    (vdir / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (vdir / "narration.txt").write_text("\n".join(scenes[k]["narration"] for k in nums),
                                        encoding="utf-8")
    for old in vdir.glob("batch_*.txt"):
        old.unlink()
    for s in range(1, len(nums) + 1, BATCH):
        part = []
        for k in range(s, min(s + BATCH, len(nums) + 1)):
            img = scenes[k]["image"].replace(LEO, "Leo").replace(STYLE, "").strip().rstrip(".")
            img = re.sub(r"\s+", " ", img)
            part.append(f"SCENE {k}: {img}.")
        msg = (f"Generate exactly ONE 16:9 image per scene below (1 image each). Name each image "
               f"'Scene N'. Leo must look exactly like the uploaded character sheet (stickman with a "
               f"yellow backwards cap and brown hair tuft): {LEO}. Style for every image: {STYLE}. "
               f"Rich detailed background environments, never plain white. "
               + " ".join(part))
        (vdir / f"batch_{s:02d}.txt").write_text(msg, encoding="utf-8")
        poses = []
        for k in range(s, min(s + BATCH, len(nums) + 1)):
            mo = re.sub(r"\s+", " ", scenes[k]["motion"]).strip().rstrip(".")
            poses.append(f"Image {k - s + 1} (Scene {k}): {mo}.")
        bmsg = ("Now EDIT each of the images you just generated in your previous answer, in the same "
                "order, producing exactly ONE edited image per original. Keep the background, "
                "framing, camera angle, lighting, colors, props and Leo's size and position exactly "
                "the same; change ONLY Leo's pose, arms and facial expression to show the next "
                "moment of the action described below (a small, natural change, like the next "
                "keyframe of a cartoon). Keep Leo identical to the character sheet. "
                + " ".join(poses))
        (vdir / f"batchB_{s:02d}.txt").write_text(bmsg, encoding="utf-8")
    words = sum(len(scenes[k]["narration"].split()) for k in nums)
    print(f"v{n}: {len(nums)} scenes, {words} words, title: {meta['title']}")


if __name__ == "__main__":
    {"parse": parse}[sys.argv[1]](int(sys.argv[2]))
