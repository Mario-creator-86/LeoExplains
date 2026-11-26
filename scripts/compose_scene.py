"""Compose a scene on this PC: a character cut out of its own picture, put over a set, and/or a clock
whose hands show an exact hour.

Why (15.11.2026): Google Flow drew scene 3 of v109 more than six times with Leo's limbs starting under
his head, and scene 6 eight times with a clock that read another hour: when a reference picture is
given, Flow copies its pose and ignores the words. The channel agent asked for a local composition and
the Owner said «Da, construiește». The set and the character are still DRAWN (in Flow, in the style of
the series); this script only puts them together, so each of them can be asked for alone, where Flow
is reliable: a set with nobody in it, and one character alone on a plain flat background.

  python compose_scene.py OUT.jpeg --bg SET.jpeg
        [--fg CHAR.png --at 0.50,0.62 --height 0.45 [--rotate -20] [--flip] [--no-shadow]]   (repeatable)
        [--clock 0.31,0.18,0.07,1:50 [--clock-face "#f4ead2"] [--clock-hands "#2b2118"]]

--bg     the set, any size; it is fitted to 1080x1920 (centre crop).
--fg     a picture of ONE character on a plain flat background (white, green, any single colour). The
         background is removed from the edges inwards, so a white head inside a black outline stays.
         A PNG that already has transparency is used as it is. Give --fg several times for several
         characters; each takes the --at/--height/--rotate/--flip that follow it.
--at     where the middle of the character goes, as fractions of the frame (x from the left, y from the top).
--height the character's height as a fraction of the frame height.
--clock  cx,cy,r,H:MM as fractions of the frame WIDTH for r and of the frame for cx,cy: the middle of
         the clock face that is already drawn in the set, its radius, and the hour to show. The old
         hands are covered with a disc of the face colour (inside the numerals) and new hands are drawn.
OUT      never one of the episode's scene files: write a candidate (for example
         vN/candidates/scene_03_c1.jpeg), LOOK at it, and only a candidate that passes the look rule is
         copied over vN/images_v/scene_SS.jpeg by the run that made it. It prints what it did.
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920


def fit(img):
    img = img.convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def cut_out(path, tol=38):
    """The character with a transparent background: the plain colour is removed from the edges inwards."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA") and np.asarray(img.convert("RGBA"))[..., 3].min() < 250:
        return img.convert("RGBA")
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w = rgb.shape[:2]
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    back = np.median(edge, axis=0)
    close = (np.abs(rgb - back).sum(axis=2) < tol * 3)
    mask = Image.fromarray(np.where(close, 255, 0).astype(np.uint8), "L").copy()   # a copy: fromarray is read-only
    step = max(4, min(w, h) // 80)
    seeds = [(x, 0) for x in range(0, w, step)] + [(x, h - 1) for x in range(0, w, step)] + \
            [(0, y) for y in range(0, h, step)] + [(w - 1, y) for y in range(0, h, step)]
    for s in seeds:
        if mask.getpixel(s) == 255:
            ImageDraw.floodfill(mask, s, 128)
    outside = np.asarray(mask) == 128
    alpha = Image.fromarray(np.where(outside, 0, 255).astype(np.uint8), "L")
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = img.convert("RGBA")
    out.putalpha(alpha)
    box = alpha.getbbox()
    if not box:
        raise SystemExit(f"{path}: nothing left after the background was removed")
    share = 1 - outside.mean()
    if share > 0.92:
        raise SystemExit(f"{path}: the background is not plain (only {100 - share * 100:.0f}% of it could be "
                         "removed): ask for the character alone on one flat colour")
    return out.crop(box)


def place(frame, fg, at, height, rotate, flip, shadow):
    if flip:
        fg = fg.transpose(Image.FLIP_LEFT_RIGHT)
    s = height * H / fg.height
    fg = fg.resize((max(1, round(fg.width * s)), max(1, round(fg.height * s))), Image.LANCZOS)
    if rotate:
        fg = fg.rotate(rotate, resample=Image.BICUBIC, expand=True)
    x, y = round(at[0] * W - fg.width / 2), round(at[1] * H - fg.height / 2)
    if shadow:   # a soft contact shadow under the character, so it stands in the set instead of floating
        sh = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(sh)
        bw, by = fg.width * 0.42, y + fg.height
        d.ellipse((x + fg.width / 2 - bw, by - fg.height * 0.03, x + fg.width / 2 + bw, by + fg.height * 0.03), fill=90)
        sh = sh.filter(ImageFilter.GaussianBlur(max(6, fg.height * 0.02)))
        frame.paste(Image.new("RGB", (W, H), (25, 18, 12)), (0, 0), sh)
    frame.paste(fg, (x, y), fg)
    return (x, y, x + fg.width, y + fg.height)


def clock(frame, cx, cy, r, hour, minute, face, hands):
    k = 4                                          # drawn four times larger, then reduced: smooth edges
    R = round(r * W * k)
    layer = Image.new("RGBA", (2 * R, 2 * R), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    inner = R * 0.66
    d.ellipse((R - inner, R - inner, R + inner, R + inner), fill=face)
    ah = math.radians(((hour % 12) + minute / 60) * 30 - 90)
    am = math.radians(minute * 6 - 90)
    for ang, length, width in ((ah, 0.40, 0.085), (am, 0.62, 0.055)):
        x2, y2 = R + math.cos(ang) * R * length, R + math.sin(ang) * R * length
        wd = max(2, round(R * width))
        d.line((R, R, x2, y2), fill=hands, width=wd)
        d.ellipse((x2 - wd / 2, y2 - wd / 2, x2 + wd / 2, y2 + wd / 2), fill=hands)
    d.ellipse((R - R * 0.07, R - R * 0.07, R + R * 0.07, R + R * 0.07), fill=hands)
    layer = layer.resize((2 * R // k, 2 * R // k), Image.LANCZOS)
    frame.paste(layer, (round(cx * W - layer.width / 2), round(cy * H - layer.height / 2)), layer)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("out")
    p.add_argument("--bg", required=True)
    p.add_argument("--fg", action="append", default=[])
    p.add_argument("--at", action="append", default=[])
    p.add_argument("--height", action="append", default=[])
    p.add_argument("--rotate", action="append", default=[])
    p.add_argument("--flip", action="store_true")
    p.add_argument("--no-shadow", action="store_true")
    p.add_argument("--clock")
    p.add_argument("--clock-face", default="#f4ead2")
    p.add_argument("--clock-hands", default="#2b2118")
    a = p.parse_args()
    out = Path(a.out)
    if out.parent.name == "images_v" or out.name.lower().startswith("scene_") and out.parent.name != "candidates":
        raise SystemExit("write a candidate first (for example vN/candidates/scene_03_c1.jpeg), look at it, "
                         "then copy the one that passes over the scene file")
    frame = fit(Image.open(a.bg))
    said = [f"set {a.bg}"]
    if a.clock:
        cx, cy, r, t = a.clock.split(",")
        hh, mm = t.split(":")
        clock(frame, float(cx), float(cy), float(r), int(hh), int(mm), a.clock_face, a.clock_hands)
        said.append(f"clock at {cx},{cy} radius {r} shows {int(hh)}:{int(mm):02d}")
    for i, f in enumerate(a.fg):
        at = tuple(float(v) for v in (a.at[i] if i < len(a.at) else "0.5,0.6").split(","))
        height = float(a.height[i]) if i < len(a.height) else 0.45
        rot = float(a.rotate[i]) if i < len(a.rotate) else 0.0
        box = place(frame, cut_out(f), at, height, rot, a.flip and i == 0, not a.no_shadow)
        said.append(f"{f} at {at[0]},{at[1]} height {height} rotate {rot}: pixels {box}")
        if box[0] < 0 or box[1] < 0 or box[2] > W or box[3] > H:
            said.append("  WARNING: part of this character is outside the frame")
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out, quality=95)
    print("\n".join(said))
    print(f"wrote {out} ({W}x{H}). LOOK at it before it replaces a scene: edges of the cut-out, the size of "
          "the character against the furniture, the light on it against the light of the set.")


if __name__ == "__main__":
    sys.exit(main())
