"""Фоновая озвучка коротких ответов."""

import asyncio
import queue
import tempfile
import threading
import time
from pathlib import Path

import edge_tts
import pygame
import pyttsx3


class SpeechManager:
    def __init__(self, config: dict):
        self.engine_name = str(config.get("engine", "edge")).lower()
        self.voice = str(config.get("voice", "ru-RU-SvetlanaNeural"))
        self.speed = float(config.get("speed", 1.0))
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._queue: queue.Queue[tuple[str, threading.Event]] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._current_event: threading.Event | None = None
        self._timing_started_at: float | None = None
        self._audio_started = False
        self._windows_engine = None
        self._pygame_ready = False

    def stop(self) -> None:
        if self._current_event is not None:
            self._current_event.set()
        with self._lock:
            if self._windows_engine is not None:
                try:
                    self._windows_engine.stop()
                except Exception:
                    pass
            if self._pygame_ready:
                self._release_music()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def speak(self, text: str, timing_started_at: float | None = None) -> None:
        if not text.strip():
            return
        self.stop()
        self._current_event = threading.Event()
        self._timing_started_at = timing_started_at
        self._audio_started = False
        self._queue.put((text, self._current_event))

    def enqueue(self, text: str) -> None:
        if text.strip() and self._current_event is not None:
            self._queue.put((text, self._current_event))

    def _worker(self) -> None:
        while True:
            text, stop_event = self._queue.get()
            if not stop_event.is_set():
                self._run(text, stop_event)

    def _run(self, text: str, stop_event: threading.Event) -> None:
        if self.engine_name == "windows":
            self._speak_windows(text, stop_event)
            return
        try:
            self._speak_edge(text, stop_event)
        except Exception as error:
            if stop_event.is_set():
                return
            print(f"Edge TTS недоступен ({error}), использую Windows TTS")
            self._speak_windows(text, stop_event)

    def _speak_edge(self, text: str, stop_event: threading.Event) -> None:
        rate = f"{round((self.speed - 1) * 100):+d}%"
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as file:
            audio_file = Path(file.name)
        try:
            asyncio.run(edge_tts.Communicate(text, self.voice, rate=rate).save(str(audio_file)))
            if stop_event.is_set():
                return
            if not self._pygame_ready:
                pygame.mixer.init()
                self._pygame_ready = True
            pygame.mixer.music.load(str(audio_file))
            pygame.mixer.music.play()
            if not self._audio_started:
                self._audio_started = True
                if self._timing_started_at is not None:
                    print(f"Время до начала звука: {time.perf_counter() - self._timing_started_at:.1f} секунд")
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

    def _speak_windows(self, text: str, stop_event: threading.Event) -> None:
        engine = pyttsx3.init()
        with self._lock:
            self._windows_engine = engine
        engine.setProperty("rate", max(80, round(180 * self.speed)))
        engine.setProperty("volume", 1.0)
        for voice in engine.getProperty("voices"):
            if self.voice.lower() in f"{voice.id} {voice.name}".lower():
                engine.setProperty("voice", voice.id)
                break
        engine.say(text)
        try:
            if not self._audio_started:
                self._audio_started = True
                if self._timing_started_at is not None:
                    print(f"Время до начала звука: {time.perf_counter() - self._timing_started_at:.1f} секунд")
            engine.runAndWait()
        finally:
            with self._lock:
                self._windows_engine = None
            if stop_event.is_set():
                engine.stop()
