"""Фоновая озвучка с отдельными очередями синтеза и воспроизведения."""

import asyncio
import queue
import re
import tempfile
import threading
import time
from pathlib import Path

import edge_tts
import pygame
import pyttsx3


def split_long_text(text: str, limit: int = 70) -> list[str]:
    """Делит длинный ответ на естественные фрагменты для раннего TTS."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        boundaries = []
        for match in re.finditer(r"[,;]\s+|\s+(?=(?:и|а|но|также)\b)", remaining, flags=re.IGNORECASE):
            position = match.end() if match.group(0).strip() in {",", ";"} else match.start()
            if 45 <= position <= limit + 5:
                boundaries.append(position)
        position = max(boundaries, default=-1)
        if position < 0:
            position = remaining.rfind(" ", 45, limit + 1)
        if position <= 0:
            position = remaining.find(" ", limit)
        if position <= 0:
            break
        parts.append(remaining[:position].strip())
        remaining = remaining[position:].strip()
    if remaining:
        parts.append(remaining)
    return parts


class SpeechManager:
    def __init__(self, config: dict):
        self.engine_name = str(config.get("engine", "edge")).lower()
        self.voice = str(config.get("voice", "ru-RU-SvetlanaNeural"))
        self.speed = float(config.get("speed", 1.0))
        self.fallback_to_windows = bool(config.get("fallback_to_windows", True))
        self.windows_voice = str(config.get("windows_voice", "Microsoft Irina Desktop - Russian"))
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._synthesis_queue: queue.Queue = queue.Queue()
        self._playback_queue: queue.Queue = queue.Queue()
        self._current_engine = None
        self._pygame_ready = False
        self._timing_started_at: float | None = None
        self._audio_started = False
        threading.Thread(target=self._synthesis_worker, daemon=True).start()
        threading.Thread(target=self._playback_worker, daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._current_engine is not None:
                try:
                    self._current_engine.stop()
                except Exception:
                    pass
            if self._pygame_ready:
                self._release_music()
        self._clear_queue(self._synthesis_queue)
        self._clear_queue(self._playback_queue)

    @staticmethod
    def _clear_queue(items: queue.Queue) -> None:
        while True:
            try:
                item = items.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], Path):
                item[1].unlink(missing_ok=True)

    def speak(self, text: str, timing_started_at: float | None = None) -> None:
        if not text.strip():
            return
        self.stop()
        self._stop_event = threading.Event()
        self._timing_started_at = timing_started_at
        self._audio_started = False
        fragments = split_long_text(text)
        self._synthesis_queue.put((fragments[0], self._stop_event))
        for fragment in fragments[1:]:
            self._synthesis_queue.put((fragment, self._stop_event))

    def enqueue(self, text: str) -> None:
        if text.strip() and not self._stop_event.is_set():
            for fragment in split_long_text(text):
                self._synthesis_queue.put((fragment, self._stop_event))

    def _synthesis_worker(self) -> None:
        while True:
            text, stop_event = self._synthesis_queue.get()
            if stop_event.is_set():
                continue
            if self.engine_name == "windows":
                self._playback_queue.put(("windows", text, stop_event))
                continue
            try:
                audio_file = self._synthesize_edge(text, stop_event)
                if audio_file is not None:
                    self._playback_queue.put(("edge", audio_file, stop_event))
            except Exception as error:
                if not stop_event.is_set() and self.fallback_to_windows:
                    print(f"Edge TTS недоступен ({error}), использую Windows TTS")
                    self._playback_queue.put(("windows", text, stop_event))
                elif not stop_event.is_set():
                    print(f"Edge TTS недоступен ({error}), фрагмент пропущен")

    def _playback_worker(self) -> None:
        while True:
            engine, value, stop_event = self._playback_queue.get()
            if stop_event.is_set():
                if engine == "edge":
                    value.unlink(missing_ok=True)
                continue
            if engine == "edge":
                self._play_edge_file(value, stop_event)
            else:
                self._speak_windows(value, stop_event)

    def _synthesize_edge(self, text: str, stop_event: threading.Event) -> Path | None:
        rate = f"{round((self.speed - 1) * 100):+d}%"
        for attempt in range(3):
            if stop_event.is_set():
                return None
            started_at = time.perf_counter()
            if self._timing_started_at is not None:
                print(f"Начало синтеза: {started_at - self._timing_started_at:.1f} секунд")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as file:
                audio_file = Path(file.name)
            try:
                asyncio.run(edge_tts.Communicate(text, self.voice, rate=rate).save(str(audio_file)))
                if stop_event.is_set():
                    audio_file.unlink(missing_ok=True)
                    return None
                if self._timing_started_at is not None:
                    print(f"Конец синтеза: {time.perf_counter() - self._timing_started_at:.1f} секунд")
                return audio_file
            except Exception:
                audio_file.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def _play_edge_file(self, audio_file: Path, stop_event: threading.Event) -> None:
        try:
            if not self._pygame_ready:
                pygame.mixer.init()
                self._pygame_ready = True
            pygame.mixer.music.load(str(audio_file))
            pygame.mixer.music.play()
            self._mark_audio_started()
            while pygame.mixer.music.get_busy() and not stop_event.wait(0.05):
                pass
        finally:
            self._release_music()
            try:
                audio_file.unlink(missing_ok=True)
            except OSError:
                pass

    def _release_music(self) -> None:
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        try:
            pygame.mixer.music.unload()
        except pygame.error:
            pass

    def _mark_audio_started(self) -> None:
        if not self._audio_started:
            self._audio_started = True
            if self._timing_started_at is not None:
                print(f"Время до начала звука: {time.perf_counter() - self._timing_started_at:.1f} секунд")

    def _speak_windows(self, text: str, stop_event: threading.Event) -> None:
        engine = pyttsx3.init()
        with self._lock:
            self._current_engine = engine
        engine.setProperty("rate", max(80, round(180 * self.speed)))
        engine.setProperty("volume", 1.0)
        for voice in engine.getProperty("voices"):
            voice_info = f"{voice.id} {voice.name} {voice.languages}".lower()
            if self.windows_voice.lower() in voice_info or (
                self.windows_voice == "auto" and "ru-ru" in voice_info
            ):
                engine.setProperty("voice", voice.id)
                break
        engine.say(text)
        try:
            self._mark_audio_started()
            engine.runAndWait()
        finally:
            with self._lock:
                self._current_engine = None
            if stop_event.is_set():
                engine.stop()
