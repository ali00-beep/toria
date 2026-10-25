"""Логотип Toria для стартового экрана: эмблема + слово TORIA + сборка в две колонки.

Использование в интерфейсе:

    from ui.logo import start_screen_lines, enable_ansi
    enable_ansi()
    right = [ ... строки правой колонки (можно с ANSI-цветами) ... ]
    for line in start_screen_lines(right, term_width):
        print(line)

Для rich:  console.print(Text.from_ansi("\\n".join(lines)))
Для prompt_toolkit:  print_formatted_text(ANSI("\\n".join(lines)))

Модуль читает готовые файлы ui/assets/toria_art.json и toria_word.txt.
Картинку и Pillow во время работы агента он не использует.
"""
from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from pathlib import Path

from . import theme

ASSETS = Path(__file__).resolve().parent / "assets"
RESET = "\x1b[0m"
Color = tuple[int, int, int]


def enable_ansi() -> None:
    """Включает ANSI-цвета в консоли Windows (в Windows Terminal уже включены)."""
    if os.name == "nt":
        os.system("")


def _gradient(x: int, width: int) -> Color:
    t = x / max(width - 1, 1)
    return tuple(int(a + (b - a) * t) for a, b in zip(theme.ACCENT_FROM, theme.ACCENT_TO))  # type: ignore[return-value]


def _scaled(x: int, width: int, bright: float, floor: float = 0.0) -> Color:
    k = floor + (1.0 - floor) * max(0.0, min(1.0, bright))
    return tuple(int(c * k) for c in _gradient(x, width))  # type: ignore[return-value]


def _fg(c: Color) -> str:
    return f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m"


def _bg(c: Color) -> str:
    return f"\x1b[48;2;{c[0]};{c[1]};{c[2]}m"


@lru_cache(maxsize=1)
def _load_art() -> dict:
    return json.loads((ASSETS / "toria_art.json").read_text(encoding="utf-8"))


def art_width() -> int:
    return int(_load_art()["cols"])


def art_height() -> int:
    return int(_load_art()["rows"])


def art_lines(mode: str | None = None) -> list[str]:
    """Строки эмблемы с ANSI-цветом. mode: 'blocks' или 'ascii' (по умолчанию из theme)."""
    mode = mode or theme.ART_MODE
    data = _load_art()
    rows, cols = data["rows"], data["cols"]
    out: list[str] = []

    if mode == "ascii":
        for y in range(rows):
            parts: list[str] = []
            for x in range(cols):
                ch = data["chars"][y][x]
                if ch == " ":
                    parts.append(" ")
                else:
                    b = data["brightness"][y][x] / 255
                    parts.append(_fg(_scaled(x, cols, b, theme.COLOR_FLOOR)) + ch)
            out.append("".join(parts) + RESET)
        return out

    sub = data["sub_brightness"]  # 2*rows строк
    lim = theme.BLOCK_EMPTY_BELOW
    for y in range(rows):
        parts = []
        for x in range(cols):
            bt, bb = sub[2 * y][x] / 255, sub[2 * y + 1][x] / 255
            top = _scaled(x, cols, bt) if bt >= lim else None
            bot = _scaled(x, cols, bb) if bb >= lim else None
            if top is None and bot is None:
                parts.append(" ")
            elif bot is None:
                parts.append(_fg(top) + "▀" + RESET)           # type: ignore[arg-type]
            elif top is None:
                parts.append(_fg(bot) + "▄" + RESET)
            else:
                parts.append(_fg(top) + _bg(bot) + "▀" + RESET)
        out.append("".join(parts))
    return out


@lru_cache(maxsize=1)
def _load_word() -> list[str]:
    lines = (ASSETS / "toria_word.txt").read_text(encoding="utf-8").splitlines()
    width = max(len(s) for s in lines)
    return [s.ljust(width) for s in lines]


def word_width() -> int:
    return len(_load_word()[0])


def word_lines() -> list[str]:
    """Слово TORIA знаками «#» с градиентом по горизонтали."""
    lines = _load_word()
    width = len(lines[0])
    out = []
    for row in lines:
        parts = []
        for x, ch in enumerate(row):
            parts.append(" " if ch == " " else _fg(_gradient(x, width)) + ch)
        out.append("".join(parts) + RESET)
    return out


def start_screen_lines(right_lines: list[str], term_width: int | None = None, mode: str | None = None) -> list[str]:
    """Две колонки: слева эмблема, справа right_lines (по вертикали по центру).

    Если терминал уже theme.MIN_WIDTH_FOR_ART - возвращает только правую колонку.
    """
    term_width = term_width or shutil.get_terminal_size((120, 30)).columns
    if term_width < theme.MIN_WIDTH_FOR_ART:
        return list(right_lines)

    art = art_lines(mode)
    height = len(art)
    top_pad = max((height - len(right_lines)) // 2, 0)
    gap = " " * theme.COLUMN_GAP
    out = []
    for i in range(max(height, top_pad + len(right_lines))):
        left = art[i] if i < height else " " * art_width()
        j = i - top_pad
        right = right_lines[j] if 0 <= j < len(right_lines) else ""
        out.append(left + gap + right)
    return out


def demo_right_column() -> list[str]:
    """Пример правой колонки, как на стартовом экране Toria (для проверки вида)."""
    grey, white, green, dim = "\x1b[38;2;150;150;150m", "\x1b[97m", "\x1b[38;2;60;190;60m", "\x1b[38;2;110;110;110m"
    sep = dim + "─" * 62 + RESET
    return [
        *word_lines(),
        "",
        white + "Голосовой помощник для вашего ПК" + RESET,
        "",
        grey + "v0.1" + RESET,
        sep,
        white + "\x1b[1mНачало работы" + RESET,
        green + "> /модели       выбрать нейросети" + RESET,
        white + "  /детали       показать или скрыть технические строки" + RESET,
        white + "  /лог         показать последние строки лога".replace("/лог         ", "/лог          ") + RESET,
        white + "  /выход        завершить работу" + RESET,
        "",
        grey + "F9 — запись голосовой команды" + RESET,
    ]


if __name__ == "__main__":  # python -m ui.logo [ascii|blocks]
    import sys

    enable_ansi()
    print()
    for line in start_screen_lines(demo_right_column(), mode=sys.argv[1] if len(sys.argv) > 1 else None):
        print(line)
    print()
