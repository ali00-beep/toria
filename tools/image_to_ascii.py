"""Вырезает эмблему TORIA и сохраняет её как 48x24 JSON-арт."""

import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    print("Pillow не установлен. Установите Pillow отдельно, затем повторите запуск.")
    raise SystemExit(2)

if len(sys.argv) != 2:
    print("Использование: python tools/image_to_ascii.py путь\к\картинке")
    raise SystemExit(1)

root = Path(__file__).resolve().parents[1]
output = root / "ui" / "assets" / "toria_art.json"
chars = " .:-=+*#%"
with Image.open(sys.argv[1]) as source:
    crop = source.crop((0, 0, int(source.width * 0.43), int(source.height * 0.73)))
    # Убираем чёрные поля вокруг эмблемы, чтобы она занимала всю левую колонку.
    visible = crop.point(lambda value: 255 if value > 20 else 0)
    bounds = visible.getbbox()
    if bounds:
        crop = crop.crop(bounds)
    # 48x24 ячеек на терминале имеют примерно квадратный экранный размер:
    # высота символа обычно вдвое больше его ширины.
    image = ImageOps.autocontrast(crop.convert("L")).resize((48, 24), Image.Resampling.LANCZOS)
cells = []
for y in range(24):
    row = []
    for x in range(48):
        raw_brightness = image.getpixel((x, y))
        brightness = max(0, min(255, round((raw_brightness - 12) * 1.35)))
        row.append({"char": chars[brightness * (len(chars) - 1) // 255], "brightness": brightness})
    cells.append(row)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"width": 48, "height": 24, "cells": cells}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Сохранено: {output}")
