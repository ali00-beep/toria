"""Каркас консольного интерфейса в стиле Claude Code / Qwen Code."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

ROOT = Path(__file__).resolve().parent.parent
ACCENT = "#f59e0b"
SUCCESS = "#22c55e"
ERROR = "#ef4444"
MUTED = "#8792a2"


class VoiceAgentApp(App):
    TITLE = "Голосовой агент"
    CSS = f"""
    Screen {{ background: #171717; color: #e5e7eb; }}
    #top {{ border: round {ACCENT}; height: 5; padding: 0 1; background: #202020; }}
    #brand {{ color: {ACCENT}; text-style: bold; width: 25; }}
    #status {{ width: 28; }}
    #models {{ color: {MUTED}; }}
    #hint {{ color: {MUTED}; width: 1fr; text-align: right; }}
    #events {{ border: round #3f3f46; height: 1fr; margin: 1 0; padding: 0 1; background: #18181b; }}
    #input {{ border: round {ACCENT}; margin-top: 0; }}
    #commands {{ color: {MUTED}; height: 1; padding: 0 1; }}
    """

    def __init__(self):
        super().__init__()
        self.config = self._load_config()
        self.events = queue.Queue()
        self.process = None
        self.speech = None
        self._stop_requested = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top"):
            yield Static("Голосовой агент", id="brand")
            yield Static("● Слушаю", id="status")
            dispatcher = self.config.get("dispatcher", {}).get("model", "—")
            executor = self.config.get("executor", {}).get("model", "—")
            yield Static(f"Диспетчер: ✓ {dispatcher}   Исполнитель: ✓ {executor}", id="models")
            yield Static(f"F9 — запись", id="hint")
        yield RichLog(id="events", highlight=False, markup=False, wrap=True)
        yield Input(placeholder="> Введите команду или /выход", id="input")
        yield Static("/модели   /настройки   /лог   /выход", id="commands")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.05, self._drain_events)
        self._start_voice_agent()
        self._write("✓ Интерфейс запущен", SUCCESS)

    def _load_config(self) -> dict:
        try:
            return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _start_voice_agent(self) -> None:
        python_path = ROOT / ".venv" / "Scripts" / "python.exe"
        executable = str(python_path if python_path.exists() else sys.executable)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        self.process = subprocess.Popen(
            [executable, "-u", str(ROOT / "src" / "record.py")],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )
        threading.Thread(target=self._read_voice_output, daemon=True).start()

    def _read_voice_output(self) -> None:
        if self.process and self.process.stdout:
            for line in self.process.stdout:
                self.events.put(("voice", line.rstrip()))

    def _drain_events(self) -> None:
        log = self.query_one("#events", RichLog)
        while True:
            try:
                source, message = self.events.get_nowait()
            except queue.Empty:
                break
            if source == "voice":
                self._update_status(message)
                self._write(self._decorate_voice(message))
            else:
                self._write(message)

    def _decorate_voice(self, message: str) -> str:
        if "Распознано:" in message:
            return f"> {message}"
        if "Скажу:" in message or "Задача:" in message:
            return f"● {message}"
        if "Ошибка" in message or "ошибка" in message:
            return f"✗ {message}"
        if "Файл сохранён" in message or "готов" in message.lower():
            return f"✓ {message}"
        return message

    def _write(self, message: str, color: str | None = None) -> None:
        log = self.query_one("#events", RichLog)
        if color:
            log.write(Text(message, style=color))
        else:
            log.write(Text(message))

    def _update_status(self, message: str) -> None:
        status = self.query_one("#status", Static)
        if "Запись..." in message:
            status.update("● Записываю")
        elif "Исполнитель работает" in message:
            status.update("● Выполняю")
        elif "Распознано" in message or "Думаю" in message:
            status.update("● Думаю")
        elif "Скажу" in message or "начала звука" in message:
            status.update("● Говорю")
        elif "Ошибка" in message:
            status.update("● Ошибка")
        else:
            status.update("● Слушаю")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._command(text.lower())
            return
        self._write(f"> {text}")
        threading.Thread(target=self._process_text, args=(text,), daemon=True).start()

    def _command(self, command: str) -> None:
        if command == "/выход":
            self.exit()
        elif command in {"/модели", "/настройки", "/лог"}:
            self._write(f"● {command}: скоро", MUTED)
        else:
            self._write(f"✗ Неизвестная команда: {command}", ERROR)

    def _process_text(self, text: str) -> None:
        try:
            from src.dispatcher import dispatch_stream
            from src.executor import confirm_run, execute, run_file
            from src.tts import SpeechManager

            tts_config = self.config.get("tts", {})
            speech = SpeechManager(tts_config)
            started = time.perf_counter()
            say_parts = []

            def on_sentence(sentence: str) -> None:
                say_parts.append(sentence)
                self.events.put(("text", f"● Ответ диспетчера: {sentence}"))
                speech.speak(sentence, started) if len(say_parts) == 1 else speech.enqueue(sentence)

            result = dispatch_stream(text, self.config.get("dispatcher", {}), ROOT, on_sentence)
            if result is None:
                self.events.put(("text", "✗ Диспетчер не вернул результат"))
                return
            task = result.get("task", "")
            self.events.put(("text", f"● Задача исполнителя: {task or 'нет'}"))
            if task:
                self.events.put(("text", "● Исполнитель работает..."))
                executor_config = self.config.get("executor", {})
                executor_result = execute(task, text, executor_config, ROOT)
                if executor_result["status"] != "ok":
                    self.events.put(("text", f"✗ {executor_result['summary']}: {executor_result['details']}"))
                    speech.speak(executor_result["summary"])
                    return
                self.events.put(("text", f"✓ {executor_result['summary']} ({executor_result['details']})"))
                speech.speak(executor_result["summary"])
        except Exception as error:
            self.events.put(("text", f"✗ Ошибка: {error}"))

    def key_escape(self):
        self.exit()

    def action_quit(self) -> None:
        self.exit()

    def on_unmount(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

