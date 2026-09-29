#!/usr/bin/env python3
"""Creates the demo GIFs (a Pac-Man-like chase and a plasma) in both orientations.

Usage:  python3 tools/make_demo_gifs.py
Writes demo-*.bmp to CIRCUITPY/gifs_landscape and CIRCUITPY/gifs_portrait.
"""
import colorsys
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

import gif2bmp

ROOT = Path(__file__).resolve().parent.parent / "CIRCUITPY"


def plasma(w, h):
    frames = []
    for f in range(40):
        im = Image.new("RGB", (w, h))
        px = im.load()
        t = f / 40 * 2 * math.pi
        for y in range(h):
            for x in range(w):
                v = (math.sin(x / 6 + t) + math.sin(y / 6 - t) + math.sin((x + y) / 9 + t)
                     + math.sin(math.hypot(x - w / 2, y - h / 2) / 5 - t)) / 4
                r, g, b = colorsys.hsv_to_rgb((v + 1) / 2, 1, 1)
                px[x, y] = (int(r * 255), int(g * 255), int(b * 255))
        frames.append(im)
    return frames, 60


def chase(w, h):
    """Yellow circle with an open mouth, chased by a red ghost."""
    horizontal = w > h
    length = w if horizontal else h
    mid = (h if horizontal else w) // 2
    frames = []
    for f in range(48):
        im = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(im)
        pos = ((f * 2) % (length + 32)) - 16

        def xy(along, across):
            return (along, across) if horizontal else (across, along)

        for i in range(8):  # dots still waiting to be eaten
            p = i * 9 + 4 - (f * 2) % 9
            if p > pos + 8:
                x, y = xy(p, mid - 1)
                d.rectangle((x, y, x + 1, y + 1), fill=(255, 190, 150))
        mouth = abs((f % 8) - 4) * 9
        start = 0 if horizontal else 90
        x, y = xy(pos, mid)
        d.pieslice((x - 7, y - 7, x + 7, y + 7), start + mouth, start + 360 - mouth,
                   fill=(255, 220, 0))
        gx, gy = xy(pos - 20, mid)
        d.chord((gx - 7, gy - 7, gx + 7, gy + 7), 180, 360, fill=(255, 40, 40))
        d.rectangle((gx - 7, gy, gx + 7, gy + 5), fill=(255, 40, 40))
        for k in range(3):
            d.polygon([(gx - 7 + k * 5, gy + 5), (gx - 5 + k * 5, gy + 7),
                       (gx - 3 + k * 5, gy + 5)], fill=(255, 40, 40))
        d.rectangle((gx - 4, gy - 3, gx - 2, gy - 1), fill="white")
        d.rectangle((gx + 1, gy - 3, gx + 3, gy - 1), fill="white")
        frames.append(im)
    return frames, 70


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for folder, (w, h) in (("gifs_landscape", (64, 32)), ("gifs_portrait", (32, 64))):
            out = ROOT / folder
            out.mkdir(parents=True, exist_ok=True)
            for name, make in (("demo-chase", chase), ("demo-plasma", plasma)):
                frames, delay = make(w, h)
                src = Path(tmp) / f"{name}.gif"
                frames[0].save(src, save_all=True, append_images=frames[1:], duration=delay, loop=0)
                opt = SimpleNamespace(out=out, fit="contain", bg="black", black_bg=False,
                                      split=False, sharp=True, trim=False, name=name,
                                      colors=128, max_frames=90)
                gif2bmp.convert(src, w, h, opt)


if __name__ == "__main__":
    main()
