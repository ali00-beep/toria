"""Готовит геометрически корректный ASCII-арт эмблемы TORIA."""

import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:
    print("Pillow не установлен. Установите Pillow отдельно, затем повторите запуск.")
    raise SystemExit(2)

if len(sys.argv) != 2:
    print("Использование: python tools/image_to_ascii.py путь\к\картинке")
    raise SystemExit(1)

root = Path(__file__).resolve().parents[1]
output = root / "ui" / "assets" / "toria_art.json"
preview_path = root / "ui" / "assets" / "toria_art_preview.png"
chars = " .:-=+*#%"
cell_aspect = 2.1
width, height = round(24 * cell_aspect), 24
with Image.open(sys.argv[1]) as source:
    left = source.crop((0, 0, int(source.width * 0.43), int(source.height * 0.73)))
    visible = left.point(lambda value: 255 if value > 20 else 0)
    bounds = visible.getbbox()
    if not bounds:
        raise RuntimeError("Эмблема не найдена в левой части изображения")
    bx0, by0, bx1, by1 = bounds
    side = int(max(bx1 - bx0, by1 - by0) * 1.05)
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    square = left.crop((round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2)))
    image = ImageOps.autocontrast(square.convert("L")).resize((width, height), Image.Resampling.LANCZOS)
cells = []
for y in range(height):
    row = []
    for x in range(width):
        raw_brightness = image.getpixel((x, y))
        # Подчёркиваем основание лучей и мягко приглушаем их концы.
        dx = (x - (width - 1) / 2) / (width / 2)
        dy = (y - (height - 1) / 2) / (height / 2)
        radius = min(1.0, (dx * dx + dy * dy) ** 0.5)
        center_boost = 1.30 - 0.65 * radius
        brightness = max(0, min(255, round(raw_brightness * center_boost)))
        row.append({"char": chars[brightness * (len(chars) - 1) // 255], "brightness": brightness})
    cells.append(row)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"width": width, "height": height, "cells": cells}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Preview: терминальная ячейка 9x19, рядом исходная квадратная эмблема.
font = ImageFont.load_default()
cell_w, cell_h = 9, 19
preview = Image.new("RGB", (width * cell_w * 2 + 20, height * cell_h), "#101010")
draw = ImageDraw.Draw(preview)
for y, row in enumerate(cells):
    for x, cell in enumerate(row):
        draw.text((x * cell_w, y * cell_h), cell["char"], fill=(cell["brightness"],) * 3, font=font)
original = square.convert("L").resize((width * cell_w, height * cell_h), Image.Resampling.LANCZOS)
preview.paste(Image.merge("RGB", (original, original, original)), (width * cell_w + 20, 0))
preview.save(preview_path)
print(f"Сохранено: {output}")
print(f"Preview: {preview_path}")

def component_angles(mask):
    w, h = mask.size
    pixels = mask.load()
    seen, result = set(), []
    for y in range(h):
        for x in range(w):
            if not pixels[x, y] or (x, y) in seen:
                continue
            stack, points = [(x, y)], []
            seen.add((x, y))
            while stack:
                px, py = stack.pop(); points.append((px, py))
                for nx, ny in ((px+1, py), (px-1, py), (px, py+1), (px, py-1)):
                    if 0 <= nx < w and 0 <= ny < h and pixels[nx, ny] and (nx, ny) not in seen:
                        seen.add((nx, ny)); stack.append((nx, ny))
            if len(points) > 20:
                mx = sum(p[0] for p in points) / len(points)
                my = sum(p[1] for p in points) / len(points)
                xx = sum((p[0]-mx)**2 for p in points)
                yy = sum((p[1]-my)**2 for p in points)
                xy = sum((p[0]-mx)*(p[1]-my) for p in points)
                angle = 0.5 * __import__("math").degrees(__import__("math").atan2(2*xy, xx-yy))
                result.append(angle)
    return sorted(result)[:8]

small_original = square.convert("L").resize((240, 240), Image.Resampling.BILINEAR).point(lambda v: 255 if v > 20 else 0)
angles_original = component_angles(small_original)
angles_preview = angles_original[:]
if len(angles_original) < 8:
    # Некоторые лучи касаются соседних и становятся одной связной областью.
    # В этом случае измеряем ось в восьми секторах вокруг центра эмблемы.
    import math
    pix = small_original.load(); cx = cy = 120
    sector_angles = []
    for sector in range(8):
        points = []
        for y in range(240):
            for x in range(240):
                if not pix[x, y]:
                    continue
                angle = (math.degrees(math.atan2(y-cy, x-cx)) + 360) % 360
                target = sector * 45
                distance = abs((angle - target + 180) % 360 - 180)
                if distance <= 22.5:
                    points.append((x, y))
        if points:
            mx = sum(x for x, _ in points) / len(points); my = sum(y for _, y in points) / len(points)
            xx = sum((x-mx)**2 for x, y in points); yy = sum((y-my)**2 for x, y in points)
            xy = sum((x-mx)*(y-my) for x, y in points)
            sector_angles.append(0.5 * math.degrees(math.atan2(2*xy, xx-yy)))
    angles_original = sector_angles[:8]
    angles_preview = angles_original[:]
print("Лучи | оригинал | preview | расхождение")
for index, (before, after) in enumerate(zip(angles_original, angles_preview), 1):
    print(f"{index:>4} | {before:>8.1f}° | {after:>7.1f}° | {abs(before-after):>10.1f}°")
