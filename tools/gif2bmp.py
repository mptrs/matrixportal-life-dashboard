#!/usr/bin/env python3
"""Convert GIFs into sprite sheets for the Matrix Portal (64x32 or 32x64).

Usage:    python3 gif2bmp.py cat.gif nyan.gif     -o /Volumes/CIRCUITPY/gifs_landscape
          python3 gif2bmp.py --portrait cat.gif   -o /Volumes/CIRCUITPY/gifs_portrait
Options:  --fit cover     fill the screen and crop, instead of black bars
          --bg edge       fill the bars with the GIF's own background color instead of black
          --black-bg      make the background black, starting from the edges (white is harsh on LEDs)
          --split         put the left half above the right half (wide image, portrait screen)
          --sharp         always scale sharply (pixel art), never blur
          --trim          cut away empty (black) space around the subject so it gets bigger
          --name NAME     output file name (default: name of the GIF)

Each GIF becomes one 8-bit BMP with all frames stacked vertically. The average
frame time goes into the file name: cat_d80.bmp = 80 ms per frame.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence


def edge_color(img):
    """Most common color along the edge of the image."""
    w, h = img.size
    px = [img.getpixel((x, y)) for x in range(w) for y in (0, h - 1)]
    px += [img.getpixel((x, y)) for y in range(h) for x in (0, w - 1)]
    return max(set(px), key=px.count)


def blacken_background(img):
    """Make the background black by flood-filling from every corner."""
    w, h = img.size
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if img.getpixel(xy) != (0, 0, 0):
            ImageDraw.floodfill(img, xy, (0, 0, 0), thresh=40)
    return img


def split_halves(img):
    """Wide image -> left half on top, right half below."""
    half = img.width // 2
    out = Image.new("RGB", (half, img.height * 2))
    out.paste(img.crop((0, 0, half, img.height)), (0, 0))
    out.paste(img.crop((half, 0, half * 2, img.height)), (0, img.height))
    return out


def prepare(frame, opt):
    img = Image.new("RGBA", frame.size, (0, 0, 0, 255))
    img.alpha_composite(frame.convert("RGBA"))
    img = img.convert("RGB")
    if opt.black_bg:
        img = blacken_background(img)
    if opt.split:
        img = split_halves(img)
    return img


def trim_box(images, margin=2):
    """Smallest box around everything that is not black, across all frames."""
    boxes = [b for b in (im.getbbox() for im in images) if b]
    if not boxes:
        return None
    w, h = images[0].size
    return (max(0, min(b[0] for b in boxes) - margin), max(0, min(b[1] for b in boxes) - margin),
            min(w, max(b[2] for b in boxes) + margin), min(h, max(b[3] for b in boxes) + margin))


def fit_frame(img, W, H, opt):
    if img.size == (W, H):
        return img
    # Pixel art that is exactly 2x, 3x... the size: scale sharply
    sx, sy = img.width / W, img.height / H
    exact = sx == sy and sx.is_integer()
    resample = Image.NEAREST if exact or opt.sharp else Image.LANCZOS
    if opt.fit == "cover":
        s = max(W / img.width, H / img.height)
    else:
        s = min(W / img.width, H / img.height)
    size = (max(1, round(img.width * s)), max(1, round(img.height * s)))
    img = img.resize(size, resample)
    out = Image.new("RGB", (W, H), edge_color(img) if opt.bg == "edge" else (0, 0, 0))
    out.paste(img, ((W - size[0]) // 2, (H - size[1]) // 2))
    return out


def convert(src, W, H, opt):
    im = Image.open(src)
    # Too many frames? Take every 2nd/3rd/... frame so the whole animation still fits
    step = -(-getattr(im, "n_frames", 1) // opt.max_frames)
    frames, durations = [], []
    for i, frame in enumerate(ImageSequence.Iterator(im)):
        if i % step == 0:
            frames.append(prepare(frame, opt))
            durations.append(0)
        durations[-1] += frame.info.get("duration") or 100
    if opt.trim:
        box = trim_box(frames)
        if box:
            frames = [f.crop(box) for f in frames]
    frames = [fit_frame(f, W, H, opt) for f in frames]
    sheet = Image.new("RGB", (W, H * len(frames)))
    for i, f in enumerate(frames):
        sheet.paste(f, (0, i * H))
    sheet = sheet.quantize(colors=opt.colors, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE)
    delay = max(20, round(sum(durations) / len(durations)))
    stem = opt.name or Path(src).stem
    stem = "".join(ch for ch in stem.lower() if ch.isalnum() or ch == "-")[:20]
    out = Path(opt.out) / f"{stem or 'gif'}_d{delay}.bmp"
    sheet.save(out)
    print(f"{src} -> {out}  ({len(frames)} frames, {delay} ms, {out.stat().st_size // 1024} KB)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("gifs", nargs="+")
    p.add_argument("-o", "--out", default=".", help="folder, e.g. /Volumes/CIRCUITPY/gifs_landscape")
    p.add_argument("--portrait", action="store_true", help="32x64 for a portrait matrix")
    p.add_argument("--fit", choices=("contain", "cover"), default="contain")
    p.add_argument("--bg", choices=("black", "edge"), default="black")
    p.add_argument("--black-bg", action="store_true")
    p.add_argument("--split", action="store_true")
    p.add_argument("--sharp", action="store_true")
    p.add_argument("--trim", action="store_true")
    p.add_argument("--name")
    p.add_argument("--colors", type=int, default=128)
    p.add_argument("--max-frames", type=int, default=90)
    opt = p.parse_args()
    if opt.name and len(opt.gifs) > 1:
        p.error("--name only works with one GIF at a time")
    Path(opt.out).mkdir(parents=True, exist_ok=True)
    w, h = (32, 64) if opt.portrait else (64, 32)
    for g in opt.gifs:
        convert(g, w, h, opt)


if __name__ == "__main__":
    main()
