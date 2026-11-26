"""1280x720 thumbnail.

NEW procedure (team vote 2026-11-06): a DEDICATED image drawn in Google Flow (Leo large, close-up, strong emotion,
plain background, empty space for text; reference character/leo_cap_sheet.png). This script only places the 2-3 word
text in the empty space; the AI never draws text.

usage:
  thumbnail.py <vdir> --hero <image> [--text "2-3 WORDS"] [--side left|right]   (dedicated Flow image; default
                                                                                    <vdir>/thumbnail_hero.*)
  thumbnail.py <vdir> <scene number> [text]                                      (LEGACY: scene crop + dark band)
text defaults to meta.json thumbnail_text. --side = which side of the frame the text goes on (the empty side).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = os.environ.get("LEO_FONT", r"C:\Windows\Fonts\ariblk.ttf")   # Arial Black (any bold TTF works)
W, H = 1280, 720


def fit_cover(img):
    img = img.resize((W, round(img.height * W / img.width)), Image.LANCZOS) if img.width / img.height < W / H \
        else img.resize((round(img.width * H / img.height), H), Image.LANCZOS)
    left, top = max(0, (img.width - W) // 2), max(0, (img.height - H) // 2)
    return img.crop((left, top, left + W, top + H))


def hero(vdir, path, text, side):
    words = text.upper().split()
    if len(words) > 3:
        sys.exit("thumbnail text must be 2-3 words: " + text)
    img = fit_cover(Image.open(path).convert("RGB"))
    box_w = 560  # empty text area, ~44% of the frame width
    x0 = 50 if side == "left" else W - 50 - box_w
    draw = ImageDraw.Draw(img, "RGBA")
    size = 190
    font = ImageFont.truetype(FONT, size)
    while max(draw.textlength(w, font=font) for w in words) > box_w and size > 60:
        size -= 6
        font = ImageFont.truetype(FONT, size)
    line_h = size + 14
    y = (H - line_h * len(words)) // 2
    for i, word in enumerate(words):
        w = draw.textlength(word, font=font)
        color = (255, 215, 0) if i == len(words) - 1 else (255, 255, 255)
        draw.text((x0 + (box_w - w) / 2, y), word, font=font, fill=color, stroke_width=9, stroke_fill=(0, 0, 0))
        y += line_h
    img.save(vdir / "thumbnail.png", optimize=True)
    print("thumbnail (hero):", vdir / "thumbnail.png", words, "side", side)


def legacy(vdir, n, text):
    img = Image.open(next((vdir / "images").glob(f"scene_{n:02d}.*"))).convert("RGB")
    img = img.resize((1280, round(img.height * 1280 / img.width)), Image.LANCZOS)
    top = max(0, (img.height - 720) // 2)
    img = img.crop((0, top, 1280, top + 720))
    words = text.split()
    half = (len(words) + 1) // 2
    lines = [" ".join(words[:half]), " ".join(words[half:])] if len(words) > 2 else [text]
    draw = ImageDraw.Draw(img, "RGBA")
    size = 110
    font = ImageFont.truetype(FONT, size)
    while max(draw.textlength(l, font=font) for l in lines) > 1180 and size > 60:
        size -= 4
        font = ImageFont.truetype(FONT, size)
    band_h = len(lines) * (size + 18) + 40
    draw.rectangle((0, 720 - band_h, 1280, 720), fill=(10, 10, 20, 170))
    y = 720 - band_h + 22
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        color = (255, 215, 0) if i == len(lines) - 1 else (255, 255, 255)
        draw.text(((1280 - w) / 2, y), line, font=font, fill=color, stroke_width=6,
                  stroke_fill=(0, 0, 0))
        y += size + 18
    img.save(vdir / "thumbnail.png", optimize=True)
    print("thumbnail (legacy):", vdir / "thumbnail.png", lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vdir")
    ap.add_argument("scene", nargs="?", type=int)
    ap.add_argument("legacy_text", nargs="?")
    ap.add_argument("--hero")
    ap.add_argument("--text")
    ap.add_argument("--side", choices=["left", "right"], default="right")
    a = ap.parse_args()
    vdir = Path(a.vdir)
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    if a.hero or a.scene is None:
        path = a.hero or next(iter(sorted(vdir.glob("thumbnail_hero.*"))), None)
        if not path:
            sys.exit("no hero image: draw one in Flow into <vdir>/thumbnail_hero.png (see PRODUCTION_BRIEF.md §3)")
        hero(vdir, path, a.text or meta.get("thumbnail_text") or meta["title"], a.side)
    else:
        legacy(vdir, a.scene, (a.legacy_text or meta.get("thumbnail_text") or meta["title"]).upper())


if __name__ == "__main__":
    main()
