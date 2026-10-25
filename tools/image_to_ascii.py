"""Преобразует картинку в ASCII-арт 36x18, если установлен Pillow."""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow не установлен. Установите Pillow отдельно, затем повторите запуск.")
    raise SystemExit(2)

if len(sys.argv) != 2:
    print("Использование: python tools/image_to_ascii.py путь\к\картинке")
    raise SystemExit(1)

root = Path(__file__).resolve().parents[1]
output = root / "ui" / "assets" / "toria_art.txt"
chars = " .:-=+*#%"
image = Image.open(sys.argv[1]).convert("L")
image.thumbnail((36, 18))
canvas = Image.new("L", (36, 18), 0)
canvas.paste(image, ((36 - image.width) // 2, (18 - image.height) // 2))
lines = []
for y in range(18):
    lines.append("".join(chars[pixel * (len(chars) - 1) // 255] for pixel in [canvas.getpixel((x, y)) for x in range(36)]).rstrip())
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Сохранено: {output}")
