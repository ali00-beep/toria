"""Запись голоса при удержании горячей клавиши."""

import json
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard
from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parent.parent
TARGET_SAMPLE_RATE = 16_000


def load_config() -> tuple[str, Path, str]:
    with (ROOT / "config.json").open(encoding="utf-8") as file:
        config = json.load(file)
    hotkey = str(config.get("hotkey", "F9")).upper()
    recordings_folder = ROOT / str(config.get("recordings_folder", "workspace"))
    whisper_model = str(config.get("whisper_model", "base"))
    return hotkey, recordings_folder, whisper_model


def transcribe(audio_file: Path, model_name: str) -> None:
    audio, sample_rate = sf.read(audio_file, dtype="float32", always_2d=True)
    if audio.shape[1] > 1:
        audio = audio.mean(axis=1)
    else:
        audio = audio[:, 0]

    if sample_rate != TARGET_SAMPLE_RATE and len(audio) > 0:
        target_length = round(len(audio) * TARGET_SAMPLE_RATE / sample_rate)
        source_positions = np.arange(len(audio), dtype=np.float32)
        target_positions = np.linspace(0, len(audio) - 1, target_length, dtype=np.float32)
        audio = np.interp(target_positions, source_positions, audio).astype(np.float32)
    else:
        audio = audio.astype(np.float32, copy=False)

    def run_model(model: WhisperModel) -> str:
        segments, _ = model.transcribe(audio, language="ru")
        return " ".join(segment.text.strip() for segment in segments).strip()

    try:
        text = run_model(WhisperModel(model_name, device="auto", compute_type="default"))
    except RuntimeError as error:
        if "cublas64_12.dll" not in str(error).lower():
            raise
        print("GPU недоступен (не найден CUDA cublas), повторяю на CPU...")
        text = run_model(WhisperModel(model_name, device="cpu", compute_type="int8"))
    print(f"Распознано: {text}")


def key_from_name(name: str):
    try:
        return getattr(keyboard.Key, name.lower())
    except AttributeError as error:
        raise ValueError(f"Неизвестная горячая клавиша: {name}") from error


def main() -> None:
    hotkey_name, recordings_folder, whisper_model = load_config()
    hotkey = key_from_name(hotkey_name)
    recordings_folder.mkdir(parents=True, exist_ok=True)

    recording = False
    stop_recording = threading.Event()
    audio_chunks: list = []
    started_at = 0.0

    def on_audio(data, frames, callback_time, status):
        if status:
            print(f"Предупреждение аудио: {status}")
        if recording:
            audio_chunks.append(data.copy())

    def on_press(key):
        nonlocal recording, started_at, audio_chunks
        if key == hotkey and not recording:
            recording = True
            started_at = time.monotonic()
            audio_chunks = []
            stop_recording.clear()
            print("Запись...")

    def on_release(key):
        if key == hotkey and recording:
            stop_recording.set()
        if key == keyboard.Key.esc:
            return False

    print(f"Удерживайте {hotkey_name} для записи. Для выхода нажмите Esc.")
    with sd.InputStream(samplerate=TARGET_SAMPLE_RATE, channels=1, dtype="float32", callback=on_audio):
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            while listener.is_alive():
                if stop_recording.wait(0.05):
                    recording = False
                    duration = time.monotonic() - started_at
                    output_file = recordings_folder / "test.wav"
                    if audio_chunks:
                        sf.write(output_file, np.concatenate(audio_chunks, axis=0), TARGET_SAMPLE_RATE)
                    else:
                        sf.write(output_file, [], TARGET_SAMPLE_RATE)
                    print(f"Запись сохранена, {duration:.1f} секунд")
                    transcribe(output_file, whisper_model)
                    stop_recording.clear()
                time.sleep(0.01)
            listener.join()


if __name__ == "__main__":
    main()
