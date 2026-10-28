"""Draws the app icon (an APC-style pad grid) and saves it for Windows and macOS.

    py -3.12 -m pip install pillow
    py -3.12 assets/make_icon.py

Writes assets/icon.png (1024 px), assets/icon.ico (Windows) and assets/icon.icns (macOS).
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024
SCALE = 2  # draw bigger, then shrink, for smooth edges

BODY = (32, 35, 43)
EDGE = (62, 68, 82)
COLOURS = {"g": (46, 204, 64), "r": (255, 65, 54), "y": (255, 220, 0), "o": (58, 63, 74)}
PATTERN = ["gror",
           "rgyr",
           "orgg",
           "grrg"]


def draw() -> Image.Image:
    s = SIZE * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = int(s * 0.06)  # transparent margin, as macOS icons have
    d.rounded_rectangle([m, m, s - m, s - m], radius=int(s * 0.2), fill=BODY, outline=EDGE, width=int(s * 0.012))
    inner = int(s * 0.17)
    gap = int(s * 0.035)
    cell = (s - 2 * inner - 3 * gap) // 4
    for row, line in enumerate(PATTERN):
        for col, ch in enumerate(line):
            x = inner + col * (cell + gap)
            y = inner + row * (cell + gap)
            d.rounded_rectangle([x, y, x + cell, y + cell], radius=int(cell * 0.18), fill=COLOURS[ch])
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    img = draw()
    img.save(HERE / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(HERE / "icon.icns")
    print("Wrote icon.png, icon.ico and icon.icns in", HERE)


if __name__ == "__main__":
    main()
