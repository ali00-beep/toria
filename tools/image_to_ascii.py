"""Превращает логотип Toria (PNG) в ASCII-арт для стартового экрана.

Запуск (из папки проекта):
    python tools/image_to_ascii.py
    python tools/image_to_ascii.py путь/к/картинке.png --rows 24 --cell-aspect 2.1

Что делает:
  1. Находит эмблему (всё левее слова TORIA) по яркости относительно фона.
  2. Вырезает её строго квадратом вокруг центра.
  3. Сжимает квадрат в сетку COLS x ROWS, где COLS = ROWS * CELL_ASPECT.
     Ячейка терминала примерно вдвое выше своей ширины, поэтому столбцов
     нужно в ~2.1 раза больше, чем строк, иначе углы лучей «поедет».
  4. Выбирает символ по яркости с упорядоченным дизерингом (матрица Байера 4x4).
  5. Сохраняет ui/assets/toria_art.json (символы + яркость 0-255)
     и, если указан --preview, картинку для проверки геометрии.

Нужен только Pillow (и numpy). Во время работы агента этот скрипт не нужен:
интерфейс читает готовый json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE = ROOT / "ui" / "assets" / "toria_logo.png"
DEFAULT_OUT = ROOT / "ui" / "assets" / "toria_art.json"

CHAR_RAMP = " .:-=+*#%@"
BAYER_4 = np.array(
    [[0, 8, 2, 10],
     [12, 4, 14, 6],
     [3, 11, 1, 9],
     [15, 7, 13, 5]],
    dtype=float,
)
BAYER_4 = (BAYER_4 + 0.5) / 16.0  # пороги 0..1

BG_MARGIN = 4       # насколько ярче фона должен быть пиксель эмблемы (хвосты лучей тусклые)
MERGE_GAP_PX = 80   # просвет между лучами меньше этого считаем одной эмблемой
CROP_PADDING = 1.05  # запас вокруг эмблемы
EMPTY_BELOW = 0.04   # ячейки темнее этого значения остаются пустыми


def luminance(img: Image.Image) -> np.ndarray:
    rgb = np.asarray(img.convert("RGB"), dtype=float)
    return rgb.mean(axis=2)


def find_emblem_box(lum: np.ndarray) -> tuple[int, int, int, int, float]:
    """Границы эмблемы (левая группа ярких пикселей, до слова TORIA)."""
    bg = float(np.median(lum[:50, :50]))
    mask = lum > bg + BG_MARGIN
    cols = mask.any(axis=0)

    runs: list[list[int]] = []
    start = None
    for x, on in enumerate(cols):
        if on and start is None:
            start = x
        elif not on and start is not None:
            runs.append([start, x - 1])
            start = None
    if start is not None:
        runs.append([start, len(cols) - 1])
    if not runs:
        raise SystemExit("Не нашёл эмблему: картинка пустая или фон не тёмный.")

    # склеиваем близкие группы столбцов, берём самую левую группу
    merged = [runs[0]]
    for r in runs[1:]:
        if r[0] - merged[-1][1] <= MERGE_GAP_PX:
            merged[-1][1] = r[1]
        else:
            break  # дальше начинается слово TORIA
    x0, x1 = merged[0]
    ys = np.where(mask[:, x0 : x1 + 1].any(axis=1))[0]
    return x0, x1, int(ys.min()), int(ys.max()), bg


def square_crop(lum: np.ndarray, box: tuple[int, int, int, int, float]) -> np.ndarray:
    x0, x1, y0, y1, bg = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    side = int(round(max(w, h) * CROP_PADDING))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = int(round(cx - side / 2)), int(round(cy - side / 2))

    canvas = np.full((side, side), bg, dtype=float)
    # копируем с учётом выхода за границы картинки
    sx0, sy0 = max(left, 0), max(top, 0)
    sx1, sy1 = min(left + side, lum.shape[1]), min(top + side, lum.shape[0])
    canvas[sy0 - top : sy1 - top, sx0 - left : sx1 - left] = lum[sy0:sy1, sx0:sx1]
    return canvas


def to_grid(square: np.ndarray, bg: float, rows: int, cols: int) -> np.ndarray:
    img = Image.fromarray(np.clip(square, 0, 255).astype(np.uint8), "L")
    small = np.asarray(img.resize((cols, rows), Image.BOX), dtype=float)
    v = np.clip((small - bg) / max(small.max() - bg, 1.0), 0.0, 1.0)
    return v


def to_chars(v: np.ndarray) -> list[str]:
    rows, cols = v.shape
    n = len(CHAR_RAMP) - 1
    lines = []
    for y in range(rows):
        line = []
        for x in range(cols):
            val = v[y, x]
            if val < EMPTY_BELOW:
                line.append(" ")
                continue
            level = val * n
            base = int(np.floor(level))
            frac = level - base
            idx = base + (1 if frac > BAYER_4[y % 4, x % 4] else 0)
            idx = max(1, min(n, idx))  # непустая ячейка не может быть пробелом
            line.append(CHAR_RAMP[idx])
        lines.append("".join(line))
    return lines


def save_json(path: Path, chars: list[str], v: np.ndarray, sub: np.ndarray, cell_aspect: float) -> None:
    data = {
        "rows": len(chars),
        "cols": len(chars[0]),
        "cell_aspect": cell_aspect,
        # режим «ascii»: символ и яркость каждой ячейки
        "chars": chars,
        "brightness": [[int(round(b * 255)) for b in row] for row in v],
        # режим «blocks»: яркость двух половинок каждой ячейки (2*rows строк)
        "sub_brightness": [[int(round(b * 255)) for b in row] for row in sub],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--rows", type=int, default=24)
    ap.add_argument("--cell-aspect", type=float, default=2.1,
                    help="высота ячейки терминала / ширина (Windows Terminal ~2.1)")
    ap.add_argument("--preview", default="", help="сохранить картинку для проверки")
    args = ap.parse_args()

    cols = int(round(args.rows * args.cell_aspect))
    lum = luminance(Image.open(args.image))
    box = find_emblem_box(lum)
    square = square_crop(lum, box)
    sub = to_grid(square, box[4], args.rows * 2, cols)          # две половинки на ячейку
    v = sub.reshape(args.rows, 2, cols).mean(axis=1)
    v = v / max(v.max(), 1e-6)
    chars = to_chars(v)

    save_json(Path(args.out), chars, v, sub, args.cell_aspect)
    print(f"Эмблема: x {box[0]}-{box[1]}, y {box[2]}-{box[3]}; сетка {cols}x{args.rows}")
    print("\n".join(chars))

    if args.preview:
        from preview_check import make_preview  # tools/preview_check.py
        make_preview(square, box[4], chars, v, sub, args.preview, args.cell_aspect)
        print(f"Превью: {args.preview}")


if __name__ == "__main__":
    main()
