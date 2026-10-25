"""Создаёт статичный ASCII-арт орба Toria без сторонних библиотек."""

import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ui" / "assets" / "toria_art.txt"
WIDTH, HEIGHT = 36, 18
CHARS = " .:-=+*#%"

lines = []
for y in range(HEIGHT):
    row = []
    for x in range(WIDTH):
        nx = (x - WIDTH / 2) / (WIDTH / 2 - 2)
        ny = (y - HEIGHT / 2) / (HEIGHT / 2 - 1)
        radius = nx * nx + ny * ny
        if radius > 1.0:
            row.append(" ")
            continue
        wave = 0.16 * math.sin(nx * 10 + ny * 5) + 0.05 * math.sin(nx * 23)
        light = max(0.0, 1.0 - radius) ** 0.45
        band = 0.22 if abs(ny - wave) < 0.12 or abs(ny + 0.35 - wave) < 0.08 else 0.0
        shade = min(1.0, 0.12 + light * 0.58 + band)
        row.append(CHARS[min(len(CHARS) - 1, int(shade * len(CHARS)))])
    lines.append("".join(row).rstrip())

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Создано: {OUTPUT}")
