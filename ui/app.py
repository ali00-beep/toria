"""Потоковый терминальный интерфейс на Rich и prompt_toolkit."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.application import Application
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import Frame, Label, RadioList
from rich.columns import Columns
from rich.console import Console, Group
from rich.text import Text

from . import theme

ROOT = Path(__file__).resolve().parent.parent
ART_PATH = ROOT / "ui" / "assets" / "toria_art.json"
WORD_PATH = ROOT / theme.WORD_ART_PATH

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class ConsoleUI:
    def __init__(self):
        self.console = Console(highlight=False)
        self.config = self._load_config()
        self.output_queue = queue.Queue()
        self.process = None
        self.stop_event = threading.Event()
        self.details = False
        self.operation_started = None

    @staticmethod
    def _load_config():
        try:
            return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def header(self):
        word_lines = self._word_art()
        right = [
            *word_lines,
            Text("Голосовой помощник для вашего ПК"),
            Text(""),
            Text("v0.1", style=theme.MUTED),
            Text("─" * 34, style=theme.MUTED),
            Text("Начало работы", style="bold white"),
            Text("> /модели       выбрать нейросети", style=theme.SUCCESS),
            Text("  /детали       показать или скрыть технические строки"),
            Text("  /лог          показать последние строки лога"),
            Text("  /выход        завершить работу"),
            Text(""),
            Text("F9 — запись голосовой команды", style=theme.MUTED),
        ]
        try:
            art_data = json.loads(ART_PATH.read_text(encoding="utf-8"))
        except OSError:
            art_data = {}
        except json.JSONDecodeError:
            art_data = {}
        width = shutil.get_terminal_size((120, 30)).columns
        if width >= 90 and art_data.get("cells"):
            art_rows = []
            for row in art_data["cells"]:
                line = Text()
                for x, cell in enumerate(row):
                    line.append(cell["char"], style=self._gradient_color(x, theme.ART_WIDTH, cell["brightness"]))
                art_rows.append(line)
            art = Group(*art_rows)
            padding = max(0, (theme.ART_HEIGHT - len(right)) // 2)
            right_group = Group(*([Text("")] * padding + right))
            self.console.print(Columns([art, right_group], expand=False, padding=(0, 4)))
        else:
            self.console.print(Group(*right))

    def _word_art(self):
        try:
            lines = WORD_PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = ["Toria"]
        width = max((len(line) for line in lines), default=1)
        rendered = []
        for line in lines:
            text = Text()
            for index, char in enumerate(line):
                text.append(char, style=f"bold {self._gradient_color(index, width)}")
            rendered.append(text)
        return rendered

    @staticmethod
    def _gradient_color(index, length, brightness=255):
        def rgb(value):
            value = value.lstrip("#")
            return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
        start, end = rgb(theme.ACCENT_START), rgb(theme.ACCENT_END)
        ratio = index / max(1, length - 1)
        factor = max(0.0, min(1.0, brightness / 255))
        color = tuple(round((start[i] + (end[i] - start[i]) * ratio) * factor) for i in range(3))
        return "#%02x%02x%02x" % color

    def start_voice(self):
        python_path = ROOT / ".venv" / "Scripts" / "python.exe"
        executable = str(python_path if python_path.exists() else sys.executable)
        env = os.environ.copy(); env["PYTHONIOENCODING"] = "utf-8"
        self.process = subprocess.Popen([executable, "-u", str(ROOT / "src" / "record.py")], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env, bufsize=1)
        threading.Thread(target=self._read_voice, daemon=True).start()

    def _read_voice(self):
        if self.process and self.process.stdout:
            for line in self.process.stdout:
                line = line.rstrip()
                if not line.startswith("pygame-ce"):
                    self._print_event(line)

    def _print_event(self, message):
        technical = any(marker in message for marker in (
            "Прогрев", "Распознавание заняло", "Время до", "Начало синтеза", "Конец синтеза",
        ))
        if technical and not self.details:
            return
        if "Запись..." in message:
            self.operation_started = time.perf_counter()
            return
        if "Распознано:" in message:
            self.console.print(f"[bold white]>[/] {message.split(':', 1)[-1].strip()}")
        elif "Скажу:" in message:
            self.console.print(f"[{theme.DISPATCHER}] диспетчер: {message.split(':', 1)[-1].strip()}")
            self._set_status("● Думаю…")
        elif "Задача:" in message or "Исполнитель работает" in message:
            if self.details:
                self.console.print(f"[{theme.EXECUTOR}] исполнитель: {message}", style=theme.MUTED)
            self._set_status("● Выполняю…")
        elif "Ошибка" in message or "ошибка" in message:
            self.console.print(f"[{theme.FAIL}] {message}")
            self._set_status("● Ошибка")
        elif "Файл сохранён" in message or "Диспетчер готов" in message:
            if "Файл сохранён" in message:
                elapsed = time.perf_counter() - self.operation_started if self.operation_started else 0
                self.console.print(f"[{theme.OK}] готово ({elapsed:.1f} с)", style=theme.SUCCESS)
                self._set_status("● Слушаю…")
            elif self.details:
                self.console.print(message, style=theme.MUTED)
        else:
            if self.details:
                self.console.print(message, style=theme.MUTED)

    def _set_status(self, value: str) -> None:
        self.console.print(value, style=theme.MUTED)

    def _models_menu(self):
        choices = [
            ("dispatcher", f"Диспетчер: {self.config.get('dispatcher', {}).get('model', '—')}\n  Модель понимания команд"),
            ("executor", f"Исполнитель: {self.config.get('executor', {}).get('model', '—')}\n  Модель генерации файлов"),
        ]
        radio = RadioList(choices)
        menu = Application(layout=Layout(Frame(HSplit([Label("Модели"), radio]), title="Модели")), full_screen=False)
        radio.focus(); menu.run()
        self.console.print("Меню моделей закрыто (сохранение появится позже).", style=theme.MUTED)

    def _command(self, value):
        command = value.strip().lower()
        if command in {"/выход", "/exit"}: return False
        if command == "/детали":
            self.details = not self.details
            state = "показаны" if self.details else "скрыты"
            self.console.print(f"Детали: {state}", style=theme.MUTED)
            if self.details:
                self.console.print(f"Диспетчер: {self.config.get('dispatcher', {}).get('model', '—')}", style=theme.MUTED)
                self.console.print(f"Исполнитель: {self.config.get('executor', {}).get('model', '—')}", style=theme.MUTED)
            return True
        if command == "/модели": self._models_menu()
        elif command == "/лог": self._show_log()
        elif command == "/настройки": self.console.print("/настройки: скоро", style=theme.MUTED)
        else: self.console.print(f"{theme.FAIL} Неизвестная команда: {value}", style=theme.ERROR)
        return True

    def _show_log(self):
        log_path = ROOT / "logs" / f"{datetime.now():%Y-%m-%d}.log"
        if not log_path.exists():
            self.console.print("Лог пуст", style=theme.MUTED)
            return
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        self.console.print("\n".join(lines) if lines else "Лог пуст", style=theme.MUTED)

    def _process_text(self, text):
        try:
            from src.dispatcher import dispatch_stream
            from src.executor import execute
            from src.tts import SpeechManager
            speech = SpeechManager(self.config.get("tts", {})); started = time.perf_counter(); first = True

            def on_sentence(sentence):
                nonlocal first
                self.console.print(f"{theme.DISPATCHER} диспетчер: {sentence}")
                if first: speech.speak(sentence, started); first = False
                else: speech.enqueue(sentence)

            result = dispatch_stream(text, self.config.get("dispatcher", {}), ROOT, on_sentence)
            if result is None:
                self.console.print(f"{theme.FAIL} ошибка: диспетчер не вернул результат", style=theme.ERROR); return
            task = result.get("task", "")
            if self.details:
                self.console.print(f"{theme.EXECUTOR} исполнитель: {task or 'нет задачи'}", style=theme.MUTED)
            if task:
                result = execute(task, text, self.config.get("executor", {}), ROOT)
                if result["status"] == "ok":
                    elapsed = time.perf_counter() - started
                    self.console.print(f"{theme.EXECUTOR} исполнитель: {result['summary']}")
                    self.console.print(f"{theme.OK} {elapsed:.1f} с", style=theme.SUCCESS); speech.speak(result["summary"])
                else:
                    self.console.print(f"{theme.FAIL} ошибка: {result['details']}", style=theme.ERROR); speech.speak(result["summary"])
            else:
                self.console.print(f"{theme.OK} {time.perf_counter() - started:.1f} с", style=theme.SUCCESS)
        except Exception as error:
            self.console.print(f"{theme.FAIL} ошибка: {error}", style=theme.ERROR)

    def run(self):
        if os.name == "nt":
            os.system("title Toria")
        self.header()
        self.console.print("Запуск… ", end="")
        self.start_voice()
        self.console.print("✓ готов", style=theme.SUCCESS)
        self.console.print("F9 запись · /детали · /лог · /модели · Esc выход", style=theme.MUTED)
        session = PromptSession(completer=WordCompleter(["/модели", "/настройки", "/лог", "/детали", "/выход"], ignore_case=True))
        try:
            with patch_stdout(raw=True):
              while not self.stop_event.is_set():
                try: value = session.prompt(HTML("<ansigreen>></ansigreen> "))
                except (EOFError, KeyboardInterrupt): break
                if not value.strip(): continue
                if value.lstrip().startswith("/"):
                    if not self._command(value): break
                else:
                    self.console.print(f"[bold white]>[/] {value}")
                    threading.Thread(target=self._process_text, args=(value,), daemon=True).start()
        finally: self.stop()

    def stop(self):
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=2)
            except subprocess.TimeoutExpired: self.process.kill()
