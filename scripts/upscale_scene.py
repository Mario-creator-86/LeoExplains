"""upscale_scene.py vN <scene> [<scene> ...] [--force]

A sharper copy of a drawn vertical scene for a tight crop in the edit (CERERE MECANISM, 22.11.2026: a crop
of 2.8x of a 768x1376 picture comes out soft, and the redraw cap leaves the crop as the only repair).

Writes vN/images_v_hi/scene_NN.png, four times the size of vN/images_v/scene_NN.*; the picture in images_v is
never touched. shorts.py uses the copy by itself when it exists and is not older than the picture (same
frame, same crop numbers in montage.json / --focus: they are fractions of the picture).

Method: Real-ESRGAN x4 for drawings (models/RealESRGAN_x4plus_anime_6B.pth, run on this PC with torch on the
CPU, about a minute or two a picture). Without that file the script does a plain Lanczos enlargement with a
light sharpening and SAYS SO: that copy is only a little better than what shorts.py does alone.

Last line: «UPSCALE: model» or «UPSCALE: lanczos (no model)», with the files written. It draws nothing new:
what is not in the picture is not invented, lines and flat colours get cleaner. Look at the rendered sheet.
"""
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "RealESRGAN_x4plus_anime_6B.pth"
SCALE, TILE, PAD = 4, 256, 16


def source(vdir, n):
    for f in sorted((vdir / "images_v").glob(f"scene_{n:02d}.*")):
        if f.suffix.lower() in (".jpeg", ".jpg", ".png", ".webp"):
            return f
    return None


def net():
    import torch
    from torch import nn
    import torch.nn.functional as F

    class RDB(nn.Module):
        def __init__(s, nf=64, gc=32):
            super().__init__()
            s.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
            s.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
            s.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
            s.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
            s.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)

        def forward(s, x):
            a = F.leaky_relu(s.conv1(x), 0.2)
            b = F.leaky_relu(s.conv2(torch.cat((x, a), 1)), 0.2)
            c = F.leaky_relu(s.conv3(torch.cat((x, a, b), 1)), 0.2)
            d = F.leaky_relu(s.conv4(torch.cat((x, a, b, c), 1)), 0.2)
            return s.conv5(torch.cat((x, a, b, c, d), 1)) * 0.2 + x

    class RRDB(nn.Module):
        def __init__(s):
            super().__init__()
            s.rdb1, s.rdb2, s.rdb3 = RDB(), RDB(), RDB()

        def forward(s, x):
            return s.rdb3(s.rdb2(s.rdb1(x))) * 0.2 + x

    class Net(nn.Module):
        def __init__(s, blocks=6, nf=64):
            super().__init__()
            s.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
            s.body = nn.Sequential(*[RRDB() for _ in range(blocks)])
            s.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
            s.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1)
            s.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
            s.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1)
            s.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)

        def forward(s, x):
            f = s.conv_first(x)
            f = f + s.conv_body(s.body(f))
            f = F.leaky_relu(s.conv_up1(F.interpolate(f, scale_factor=2, mode="nearest")), 0.2)
            f = F.leaky_relu(s.conv_up2(F.interpolate(f, scale_factor=2, mode="nearest")), 0.2)
            return s.conv_last(F.leaky_relu(s.conv_hr(f), 0.2))

    sd = torch.load(MODEL, map_location="cpu", weights_only=True)   # weights only: no code is run from the file
    sd = sd.get("params_ema", sd.get("params", sd))
    m = Net()
    m.load_state_dict(sd, strict=True)
    return m.eval()


def with_model(img, model):
    import numpy as np
    import torch
    a = torch.from_numpy(np.asarray(img.convert("RGB"), dtype=np.float32) / 255).permute(2, 0, 1)[None]
    _, _, h, w = a.shape
    out = torch.zeros(1, 3, h * SCALE, w * SCALE)
    with torch.no_grad():
        for y in range(0, h, TILE):
            for x in range(0, w, TILE):
                y0, x0 = max(y - PAD, 0), max(x - PAD, 0)
                y1, x1 = min(y + TILE + PAD, h), min(x + TILE + PAD, w)
                t = model(a[:, :, y0:y1, x0:x1])
                ty, tx = (y - y0) * SCALE, (x - x0) * SCALE
                th, tw = (min(y + TILE, h) - y) * SCALE, (min(x + TILE, w) - x) * SCALE
                out[:, :, y * SCALE:y * SCALE + th, x * SCALE:x * SCALE + tw] = t[:, :, ty:ty + th, tx:tx + tw]
    b = (out[0].clamp(0, 1).permute(1, 2, 0).numpy() * 255 + 0.5).astype("uint8")
    return Image.fromarray(b)


def plain(img):
    big = img.convert("RGB").resize((img.width * SCALE, img.height * SCALE), Image.LANCZOS)
    return big.filter(ImageFilter.UnsharpMask(radius=3, percent=60, threshold=2))


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    force = "--force" in argv
    if len(args) < 2:
        print(__doc__)
        return 2
    vdir = ROOT / args[0]
    scenes = [int(a) for a in args[1:]]
    model = net() if MODEL.exists() else None
    how = "model" if model else "lanczos (no model)"
    hi = vdir / "images_v_hi"
    hi.mkdir(exist_ok=True)
    done = []
    for n in scenes:
        src = source(vdir, n)
        if not src:
            print(f"scene {n}: no picture in {vdir.name}/images_v")
            return 1
        dst = hi / f"scene_{n:02d}.png"
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and not force:
            print(f"scene {n}: {dst.relative_to(ROOT)} is already newer than the picture (use --force)")
            done.append(dst)
            continue
        img = Image.open(src)
        big = with_model(img, model) if model else plain(img)
        if big.size != (img.width * SCALE, img.height * SCALE):
            print(f"scene {n}: wrong size {big.size}, nothing written")
            return 1
        tmp = dst.with_suffix(".tmp.png")
        big.save(tmp)
        tmp.replace(dst)
        print(f"scene {n}: {img.size} -> {big.size} {dst.relative_to(ROOT)}")
        done.append(dst)
    print(f"UPSCALE: {how} | " + ", ".join(str(d.relative_to(ROOT)).replace('\\', '/') for d in done))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
