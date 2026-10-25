"""Потоковый терминальный интерфейс на Rich и prompt_toolkit."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.application import Application
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import Frame, Label, RadioList
from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import theme

ROOT = Path(__file__).resolve().parent.parent
LOGO = [
    " ███    ████  █████  █   █  █████",
    "█   █  █      █      ██  █    █  ",
    "█████  █  ██  ████   █ █ █    █  ",
    "█   █  █   █  █      █  ██    █  ",
    "█   █   ████  █████  █   █    █  ",
]


class ConsoleUI:
    def __init__(self):
        self.console = Console(highlight=False)
        self.config = self._load_config()
        self.output_queue = queue.Queue()
        self.process = None
        self.stop_event = threading.Event()

    @staticmethod
    def _load_config():
        try:
            return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def header(self):
        logo = []
        for line in LOGO:
            colored = Text()
            for index, char in enumerate(line):
                colored.append(char, style=theme.ACCENT_START if index < len(line) / 2 else theme.ACCENT_END)
            logo.append(colored)
        info = Table.grid(padding=(0, 1))
        info.add_row(Text(">_ Голосовой агент (v0.1)", style="bold white"))
        info.add_row(Text(f"Диспетчер: ✓ {self.config.get('dispatcher', {}).get('model', '—')}", style=theme.MUTED))
        info.add_row(Text(f"Исполнитель: ✓ {self.config.get('executor', {}).get('model', '—')}", style=theme.MUTED))
        info.add_row(Text(f"Проект: {ROOT}", style=theme.MUTED))
        self.console.print(Columns([Group(*logo), Panel(info, box=box.SIMPLE, border_style=theme.MUTED, padding=(0, 1))], expand=True))
        self.console.print(Text("Подсказка: /модели — выбрать нейросети", style=theme.MUTED))
        self.console.print()

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
                    self.output_queue.put(line)

    def _drain_voice(self):
        while True:
            try:
                self._print_event(self.output_queue.get_nowait())
            except queue.Empty:
                return

    def _print_event(self, message):
        if "Распознано:" in message:
            self.console.print(f"[bold white]>[/] {message}")
        elif "Скажу:" in message:
            self.console.print(f"[{theme.DISPATCHER}] диспетчер: {message.split(':', 1)[-1].strip()}")
        elif "Задача:" in message or "Исполнитель работает" in message:
            self.console.print(f"[{theme.EXECUTOR}] исполнитель: {message}")
        elif "Ошибка" in message or "ошибка" in message:
            self.console.print(f"[{theme.FAIL}] {message}")
        elif "Файл сохранён" in message or "Диспетчер готов" in message:
            self.console.print(f"[{theme.OK}] {message}", style=theme.SUCCESS)
        else:
            self.console.print(message, style=theme.MUTED)

    def _models_menu(self):
        choices = [("dispatcher", "Диспетчер\n  Модель понимания команд"), ("executor", "Исполнитель\n  Модель генерации файлов")]
        radio = RadioList(choices)
        menu = Application(layout=Layout(Frame(HSplit([Label("Модели"), radio]), title="Модели")), full_screen=False)
        radio.focus(); menu.run()
        self.console.print("Меню моделей закрыто (сохранение появится позже).", style=theme.MUTED)

    def _command(self, value):
        command = value.strip().lower()
        if command == "/выход": return False
        if command == "/модели": self._models_menu()
        elif command in {"/настройки", "/лог"}: self.console.print(f"{command}: скоро", style=theme.MUTED)
        else: self.console.print(f"{theme.FAIL} Неизвестная команда: {value}", style=theme.ERROR)
        return True

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
            self.console.print(f"{theme.EXECUTOR} исполнитель: {task or 'нет задачи'}")
            if task:
                result = execute(task, text, self.config.get("executor", {}), ROOT)
                if result["status"] == "ok":
                    self.console.print(f"{theme.OK} готово: {result['summary']}", style=theme.SUCCESS); speech.speak(result["summary"])
                else:
                    self.console.print(f"{theme.FAIL} ошибка: {result['details']}", style=theme.ERROR); speech.speak(result["summary"])
        except Exception as error:
            self.console.print(f"{theme.FAIL} ошибка: {error}", style=theme.ERROR)

    def run(self):
        self.header(); self.start_voice()
        session = PromptSession(completer=WordCompleter(["/модели", "/настройки", "/лог", "/выход"], ignore_case=True))
        try:
            while not self.stop_event.is_set():
                self._drain_voice()
                try: value = session.prompt(HTML("<ansigreen>></ansigreen> "))
                except (EOFError, KeyboardInterrupt): break
                self._drain_voice()
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
