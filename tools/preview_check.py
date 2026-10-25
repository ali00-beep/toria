"""Проверка геометрии: рисует оригинал, ASCII-вариант и вариант на полублоках рядом.

Используется скриптом image_to_ascii.py с ключом --preview. Ячейка превью
имеет те же пропорции, что ячейка терминала (CELL_ASPECT), поэтому если
на картинке лучи стоят под правильными углами, то и в терминале тоже.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import theme  # noqa: E402

CELL_W = 10
FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
BG = (12, 12, 12)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def gradient_color(x: int, cols: int, bright: float, floor: float) -> tuple[int, int, int]:
    t = x / max(cols - 1, 1)
    base = [a + (b - a) * t for a, b in zip(theme.ACCENT_FROM, theme.ACCENT_TO)]
    k = floor + (1 - floor) * bright
    return tuple(int(c * k) for c in base)  # type: ignore[return-value]


def render_ascii(chars: list[str], v: np.ndarray, cell_aspect: float) -> Image.Image:
    rows, cols = len(chars), len(chars[0])
    cell_h = int(round(CELL_W * cell_aspect))
    img = Image.new("RGB", (cols * CELL_W, rows * cell_h), BG)
    d = ImageDraw.Draw(img)
    font = _font(int(CELL_W / 0.6))
    for y, line in enumerate(chars):
        for x, ch in enumerate(line):
            if ch != " ":
                col = gradient_color(x, cols, float(v[y, x]), theme.COLOR_FLOOR)
                d.text((x * CELL_W + CELL_W / 2, y * cell_h + cell_h / 2), ch, font=font, fill=col, anchor="mm")
    return img


def render_blocks(sub: np.ndarray, cell_aspect: float) -> Image.Image:
    rows2, cols = sub.shape
    cell_h = int(round(CELL_W * cell_aspect))
    half = cell_h // 2
    img = Image.new("RGB", (cols * CELL_W, (rows2 // 2) * cell_h), BG)
    d = ImageDraw.Draw(img)
    for y in range(rows2):
        top = (y // 2) * cell_h + (0 if y % 2 == 0 else half)
        bottom = top + half - 1 if y % 2 == 0 else (y // 2) * cell_h + cell_h - 1
        for x in range(cols):
            col = gradient_color(x, cols, float(sub[y, x]), 0.0)
            d.rectangle([x * CELL_W, top, (x + 1) * CELL_W - 1, bottom], fill=col)
    return img


def make_preview(square: np.ndarray, bg: float, chars: list[str], v: np.ndarray, sub: np.ndarray,
                 path: str, cell_aspect: float) -> None:
    rows, cols = len(chars), len(chars[0])
    cell_h = int(round(CELL_W * cell_aspect))
    size = (cols * CELL_W, rows * cell_h)

    orig = Image.fromarray(np.clip(square, 0, 255).astype(np.uint8), "L").resize(size, Image.LANCZOS).convert("RGB")
    panels = [orig, render_ascii(chars, v, cell_aspect), render_blocks(sub, cell_aspect)]

    gap = 24
    sheet = Image.new("RGB", (size[0] * 3 + gap * 2, size[1]), (40, 40, 40))
    for i, p in enumerate(panels):
        sheet.paste(p, (i * (size[0] + gap), 0))
    sheet.save(path)
