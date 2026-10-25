# Логотип Toria — готовый набор

Куда копировать: содержимое этой папки кладётся в `C:\codex\aiagent` с сохранением структуры
(`tools\`, `ui\`, `ui\assets\`). Если файлы с такими именами есть, `ui\theme.py` и `ui\logo.py`
нужно объединить с существующими, а не затирать.

Проверка вида без агента (в Windows Terminal):

    python -m ui.logo            # режим из theme.ART_MODE (blocks)
    python -m ui.logo ascii      # режим знаков

Перегенерация арта из картинки (нужен Pillow):

    python tools/image_to_ascii.py --preview preview.png
    python tools/image_to_ascii.py --cell-aspect 2.0   # если лучи выглядят повёрнутыми

Настройки (цвета, режим, пропорции ячейки, минимальная ширина терминала) — только в `ui/theme.py`.

Подключение к интерфейсу: `ui/logo.py -> start_screen_lines(right_lines, term_width)`
возвращает готовые строки с ANSI-цветом; правую колонку (меню команд) собирает интерфейс.
