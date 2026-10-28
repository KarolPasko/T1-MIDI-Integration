"""Draws the app icon (an APC-style pad grid) and saves it for Windows and macOS.

    py -3.12 -m pip install pillow
    py -3.12 assets/make_icon.py

Writes assets/icon.png (1024 px), assets/icon.ico (Windows) and assets/icon.icns (macOS).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SIZE = 1024
SCALE = 2  # draw bigger, then shrink, for smooth edges
NAME = "Karol Pasko"
SMALL = 48  # at this size and below the name is unreadable, so it is left off
FONTS = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica.ttc"]

BODY = (32, 35, 43)
EDGE = (62, 68, 82)
COLOURS = {"g": (46, 204, 64), "r": (255, 65, 54), "y": (255, 220, 0), "o": (58, 63, 74)}
PATTERN = ["gror",
           "rgyr",
           "orgg",
           "grrg"]


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def draw(with_name: bool = True) -> Image.Image:
    s = SIZE * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = int(s * 0.06)  # transparent margin, as macOS icons have
    d.rounded_rectangle([m, m, s - m, s - m], radius=int(s * 0.2), fill=BODY, outline=EDGE, width=int(s * 0.012))
    rows = PATTERN[:3] if with_name else PATTERN
    inner = int(s * 0.17)
    gap = int(s * 0.035)
    cell = (s - 2 * inner - 3 * gap) // 4
    top = int(s * 0.14) if with_name else inner
    for row, line in enumerate(rows):
        for col, ch in enumerate(line):
            x = inner + col * (cell + gap)
            y = top + row * (cell + gap)
            d.rounded_rectangle([x, y, x + cell, y + cell], radius=int(cell * 0.18), fill=COLOURS[ch])
    if with_name:
        f = font(int(s * 0.105))
        y = top + 3 * (cell + gap) + (s - m - top - 3 * (cell + gap)) // 2 - int(s * 0.02)
        d.text((s // 2, y), NAME, font=f, fill=(240, 242, 246), anchor="mm")
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    img, plain = draw(), draw(with_name=False)
    img.save(HERE / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [(plain if n <= SMALL else img).resize((n, n), Image.LANCZOS) for n in sizes]
    images[-1].save(HERE / "icon.ico", sizes=[(n, n) for n in sizes], append_images=images[:-1])
    img.save(HERE / "icon.icns", append_images=[plain.resize((n, n), Image.LANCZOS) for n in (16, 32)])
    print("Wrote icon.png, icon.ico and icon.icns in", HERE)


if __name__ == "__main__":
    main()
