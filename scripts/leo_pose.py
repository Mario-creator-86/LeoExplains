"""Leo drawn on a skeleton you give, as a transparent PNG for compose_scene.py.

Why (the channel agent's request of 15.11.2026, built on the Owner's word of 20.11.2026 «sa ii dai tot ce cere»): Flow keeps
drawing Leo with limbs that start under the head or with one leg missing. Here the body is drawn from joints, so Leo always has
one trunk, two arms from the shoulders and two legs from the hip, in any pose.

  python leo_pose.py OUT.png --pose POSE.json [--size 1200]
  python leo_pose.py OUT.png --preset stand|dive|sit|arms_up|kneel [--face shock] [--cap left|right]

POSE.json: coordinates in a square from 0 to 1 (x to the right, y down). Only "head" and "hip" are required:
  {"head":[0.5,0.2], "hip":[0.5,0.6],
   "neck":[0.5,0.33],                       (default: under the head, toward the hip)
   "l_hand":[0.25,0.5], "r_hand":[0.75,0.5], "l_elbow":[..], "r_elbow":[..],   (elbows optional: a slight bend is added)
   "l_foot":[0.4,0.95], "r_foot":[0.6,0.95], "l_knee":[..], "r_knee":[..],
   "face":"neutral|happy|shock|sad|angry|smug", "look":[dx,dy] (where the eyes look, -1..1),
   "cap":"left|right" (side the brim points to; the cap is worn backwards), "head_r":0.11}
It prints the joints it used. The picture is Leo ALONE on a transparent background: put it over a set with
  python compose_scene.py vN/candidates/scene_SS_c1.jpeg --bg SET.jpeg --fg OUT.png --at x,y --height h
A Leo drawn by this script is flatter than a Leo drawn in Flow (no soft shading): LOOK at the composition against the look
rule before it replaces a scene; a composition that looks pasted is rejected like any other picture.
"""
import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

K = 4            # drawn K times larger, then reduced
INK = (24, 20, 22, 255)
SKIN = (255, 255, 255, 255)
CAP = (250, 204, 46, 255)
CAP_D = (214, 160, 20, 255)
HAIR = (120, 78, 44, 255)

PRESETS = {
    "stand": {"head": [0.5, 0.17], "hip": [0.5, 0.60], "l_hand": [0.36, 0.56], "r_hand": [0.64, 0.56],
              "l_foot": [0.42, 0.95], "r_foot": [0.58, 0.95]},
    "arms_up": {"head": [0.5, 0.22], "hip": [0.5, 0.62], "l_hand": [0.22, 0.10], "r_hand": [0.78, 0.10],
                "l_foot": [0.41, 0.95], "r_foot": [0.59, 0.95], "face": "shock"},
    "sit": {"head": [0.45, 0.22], "hip": [0.42, 0.62], "l_hand": [0.60, 0.56], "r_hand": [0.66, 0.50],
            "l_knee": [0.66, 0.64], "r_knee": [0.70, 0.62], "l_foot": [0.68, 0.93], "r_foot": [0.76, 0.92]},
    "kneel": {"head": [0.42, 0.28], "hip": [0.50, 0.66], "l_hand": [0.24, 0.78], "r_hand": [0.30, 0.86],
              "l_knee": [0.40, 0.92], "r_knee": [0.66, 0.74], "l_foot": [0.62, 0.93], "r_foot": [0.70, 0.94], "face": "sad"},
    "dive": {"head": [0.70, 0.40], "neck": [0.58, 0.43], "hip": [0.34, 0.50], "l_hand": [0.93, 0.36], "r_hand": [0.94, 0.48],
             "l_foot": [0.06, 0.44], "r_foot": [0.07, 0.60], "face": "shock", "cap": "left", "look": [1, 0]},
}


def mid_bend(a, b, bend):
    """A joint between a and b, pushed sideways by `bend` of their distance (a soft elbow or knee)."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    return [mx - dy * bend, my + dx * bend]


def draw(pose, size):
    S = size * K
    P = lambda p: (p[0] * S, p[1] * S)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    head, hip = pose["head"], pose["hip"]
    hr = pose.get("head_r", 0.11)
    L = math.hypot(hip[0] - head[0], hip[1] - head[1]) or 1
    ux, uy = (hip[0] - head[0]) / L, (hip[1] - head[1]) / L
    neck = pose.get("neck") or [head[0] + ux * hr * 0.98, head[1] + uy * hr * 0.98]
    sh = [neck[0] + (hip[0] - neck[0]) * 0.10, neck[1] + (hip[1] - neck[1]) * 0.10]      # shoulders: one point on the trunk
    j = {"head": head, "neck": neck, "shoulder": sh, "hip": hip}
    for side, sgn in (("l", -1), ("r", 1)):
        hand = pose.get(f"{side}_hand") or [sh[0] + sgn * 0.16, sh[1] + 0.26]
        foot = pose.get(f"{side}_foot") or [hip[0] + sgn * 0.09, min(0.95, hip[1] + 0.34)]
        j[f"{side}_hand"], j[f"{side}_foot"] = hand, foot
        j[f"{side}_elbow"] = pose.get(f"{side}_elbow") or mid_bend(sh, hand, 0.12 * sgn)
        j[f"{side}_knee"] = pose.get(f"{side}_knee") or mid_bend(hip, foot, -0.07 * sgn)
    w = max(6, round(S * 0.016))

    def limb(*pts):
        d.line([P(p) for p in pts], fill=INK, width=w, joint="curve")
        for p in pts:
            x, y = P(p)
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=INK)

    limb(neck, hip)
    for side in ("l", "r"):
        limb(sh, j[f"{side}_elbow"], j[f"{side}_hand"])
        limb(hip, j[f"{side}_knee"], j[f"{side}_foot"])
        hx, hy = P(j[f"{side}_hand"])
        r = S * 0.021
        d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=INK)                       # round black hand
        fx, fy = P(j[f"{side}_foot"])
        kx, ky = P(j[f"{side}_knee"])
        ang = math.atan2(fy - ky, fx - kx) + math.pi / 2                              # the foot lies across the shin
        foot = Image.new("RGBA", (round(S * 0.085), round(S * 0.042)), (0, 0, 0, 0))
        ImageDraw.Draw(foot).ellipse((0, 0, foot.width - 1, foot.height - 1), fill=INK)
        foot = foot.rotate(-math.degrees(ang) + (0 if side == "r" else 180), expand=True, resample=Image.BICUBIC)
        img.alpha_composite(foot, (round(fx - foot.width / 2), round(fy - foot.height / 2)))
    d = ImageDraw.Draw(img)
    # head
    cx, cy = P(head)
    R = hr * S
    d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=SKIN, outline=INK, width=w)
    # cap worn backwards: a dome over the top of the head, the brim sticking out to one side at the back
    side = -1 if pose.get("cap", "right") == "left" else 1
    d.pieslice((cx - R * 1.04, cy - R * 1.12, cx + R * 1.04, cy + R * 0.96), 180, 360, fill=CAP, outline=INK, width=w)
    d.line((cx - R * 1.04, cy - R * 0.08, cx + R * 1.04, cy - R * 0.08), fill=INK, width=w)
    bx = cx + side * R * 0.95
    d.polygon([(bx, cy - R * 0.42), (bx + side * R * 0.75, cy - R * 0.18), (bx + side * R * 0.70, cy + R * 0.02),
               (bx, cy - R * 0.08)], fill=CAP_D, outline=INK)
    d.line([(bx, cy - R * 0.42), (bx + side * R * 0.75, cy - R * 0.18), (bx + side * R * 0.70, cy + R * 0.02),
            (bx, cy - R * 0.08)], fill=INK, width=max(3, w // 2))
    tx = cx - side * R * 0.30                                                       # tuft of brown hair at the forehead
    d.polygon([(tx - R * 0.30, cy - R * 0.08), (tx - R * 0.05, cy + R * 0.20), (tx + R * 0.02, cy - R * 0.02),
               (tx + R * 0.22, cy + R * 0.14), (tx + R * 0.30, cy - R * 0.08)], fill=HAIR, outline=INK)
    # face
    look = pose.get("look", [0, 0])
    ex, ey = look[0] * R * 0.10, look[1] * R * 0.08
    face = pose.get("face", "neutral")
    er = R * (0.13 if face == "shock" else 0.085)
    for sx in (-0.34, 0.34):
        x, y = cx + sx * R + ex, cy + R * 0.22 + ey
        if face in ("happy", "smug") and sx > 0 and face == "smug":
            d.arc((x - er * 1.4, y - er, x + er * 1.4, y + er), 200, 340, fill=INK, width=max(4, w // 2))
        else:
            d.ellipse((x - er, y - er * 1.25, x + er, y + er * 1.25), fill=INK)
        if face == "angry":
            d.line((x - er * 1.8, y - er * 2.6 - sx * R * 0.25, x + er * 1.8, y - er * 2.6 + sx * R * 0.25), fill=INK, width=max(4, w // 2))
        if face == "sad":
            d.line((x - er * 1.8, y - er * 2.6 + sx * R * 0.2, x + er * 1.8, y - er * 2.6 - sx * R * 0.2), fill=INK, width=max(4, w // 2))
    mx, my, mw = cx + ex, cy + R * 0.60 + ey, R * 0.34
    lw = max(4, w // 2)
    if face == "shock":
        d.ellipse((mx - mw * 0.55, my - mw * 0.55, mx + mw * 0.55, my + mw * 0.75), fill=(120, 30, 40, 255), outline=INK, width=lw)
    elif face in ("happy", "smug"):
        d.arc((mx - mw, my - mw * 0.9, mx + mw, my + mw * 0.5), 20, 160, fill=INK, width=lw)
    elif face in ("sad", "angry"):
        d.arc((mx - mw, my, mx + mw, my + mw * 1.2), 200, 340, fill=INK, width=lw)
    else:
        d.line((mx - mw * 0.7, my, mx + mw * 0.7, my), fill=INK, width=lw)
    out = img.resize((size, size), Image.LANCZOS)
    return out.crop(out.getbbox()), j


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("out")
    p.add_argument("--pose")
    p.add_argument("--preset", choices=sorted(PRESETS))
    p.add_argument("--face")
    p.add_argument("--cap", choices=("left", "right"))
    p.add_argument("--size", type=int, default=1200)
    a = p.parse_args()
    if not a.pose and not a.preset:
        raise SystemExit("give --pose POSE.json or --preset " + "|".join(sorted(PRESETS)))
    pose = dict(PRESETS[a.preset]) if a.preset else {}
    if a.pose:
        pose.update(json.loads(Path(a.pose).read_text(encoding="utf-8-sig")))
    if a.face:
        pose["face"] = a.face
    if a.cap:
        pose["cap"] = a.cap
    for need in ("head", "hip"):
        if need not in pose:
            raise SystemExit(f'the pose needs "{need}": [x, y]')
    img, j = draw(pose, a.size)
    out = Path(a.out)
    if out.suffix.lower() != ".png":
        raise SystemExit("OUT must be a .png (the background is transparent)")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(json.dumps({k: [round(v[0], 3), round(v[1], 3)] for k, v in j.items()}))
    print(f"wrote {out} {img.size}: one trunk, two arms from the shoulder, two legs from the hip. LOOK at it, then compose.")


if __name__ == "__main__":
    sys.exit(main())
