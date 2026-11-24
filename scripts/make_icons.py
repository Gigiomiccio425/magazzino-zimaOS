"""Genera le icone PWA (rombo rosso su nero, stile costruttivista). Uso: python scripts/make_icons.py"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "static" / "pwa"
BLACK, RED, PAPER = (17, 17, 17), (226, 35, 26), (244, 241, 233)


def icon(size: int, maskable: bool) -> Image.Image:
    img = Image.new("RGB", (size, size), BLACK)
    d = ImageDraw.Draw(img)
    scale = 0.30 if maskable else 0.36          # le icone maskable tengono il disegno nella zona sicura
    c, r = size / 2, size * scale
    shadow = size * 0.035
    diamond = lambda dx, dy: [(c + dx, c - r + dy), (c + r + dx, c + dy), (c + dx, c + r + dy), (c - r + dx, c + dy)]  # noqa: E731
    d.polygon(diamond(shadow, shadow), fill=PAPER)
    d.polygon(diamond(0, 0), fill=RED)
    bar_h = size * 0.06
    d.rectangle([size * 0.12, size * 0.84, size * 0.88, size * 0.84 + bar_h], fill=RED)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192, False).save(OUT / "icon-192.png")
    icon(512, False).save(OUT / "icon-512.png")
    icon(512, True).save(OUT / "icon-maskable-512.png")


if __name__ == "__main__":
    main()
