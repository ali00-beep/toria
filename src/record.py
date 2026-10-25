"""Запись голоса при удержании горячей клавиши."""

import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard


_CUDA_DLL_HANDLES = []
if os.name == "nt":
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    for relative_path in (
        "nvidia/cublas/bin",
        "nvidia/cudnn/bin",
        "nvidia/cuda_nvrtc/bin",
    ):
        dll_path = site_packages / relative_path
        if dll_path.is_dir():
            os.environ["PATH"] = str(dll_path) + os.pathsep + os.environ.get("PATH", "")
            _CUDA_DLL_HANDLES.append(os.add_dll_directory(str(dll_path)))

from faster_whisper import WhisperModel
try:
    from dispatcher import dispatch
    from dispatcher import dispatch_stream
    from tts import SpeechManager
except ImportError:
    from .dispatcher import dispatch
    from .dispatcher import dispatch_stream
    from .tts import SpeechManager


ROOT = Path(__file__).resolve().parent.parent
TARGET_SAMPLE_RATE = 16_000


def load_config() -> tuple[str, Path, str, str, int, str, dict, dict]:
    with (ROOT / "config.json").open(encoding="utf-8") as file:
        config = json.load(file)
    hotkey = str(config.get("hotkey", "F9")).upper()
    recordings_folder = ROOT / str(config.get("recordings_folder", "workspace"))
    whisper_model = str(config.get("whisper_model", "small"))
    whisper_device = str(config.get("whisper_device", "cpu")).lower()
    beam_size = int(config.get("beam_size", 5))
    language = str(config.get("language", "ru"))
    dispatcher_config = config.get("dispatcher", {})
    tts_config = config.get("tts", {})
    return hotkey, recordings_folder, whisper_model, whisper_device, beam_size, language, dispatcher_config, tts_config


def transcribe(
    audio_file: Path,
    model_name: str,
    device: str,
    beam_size: int,
    language: str,
    model_cache: dict | None = None,
) -> str:
    started_at = time.perf_counter()
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
        segments, _ = model.transcribe(audio, language=language, beam_size=beam_size)
        return " ".join(segment.text.strip() for segment in segments).strip()

    if model_cache is None:
        model_cache = {}

    model = model_cache.get("model")
    if model is None:
        compute_type = "float16" if device == "cuda" else "int8"
        model = WhisperModel(model_name, device=device, compute_type=compute_type)

    try:
        text = run_model(model)
        model_cache["model"] = model
    except RuntimeError as error:
        if "cublas64_12.dll" not in str(error).lower():
            raise
        print("GPU недоступен (не найден CUDA cublas), повторяю на CPU...")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        text = run_model(model)
        model_cache["model"] = model
    print(f"Распознано: {text}")
    print(f"Распознавание заняло: {time.perf_counter() - started_at:.1f} секунд")
    return text


def key_from_name(name: str):
    try:
        return getattr(keyboard.Key, name.lower())
    except AttributeError as error:
        raise ValueError(f"Неизвестная горячая клавиша: {name}") from error


def warmup_whisper(model_name: str, device: str, beam_size: int, language: str, model_cache: dict) -> None:
    started_at = time.perf_counter()
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        list(model.transcribe(np.zeros(TARGET_SAMPLE_RATE // 10, dtype=np.float32), language=language, beam_size=beam_size)[0])
    except RuntimeError as error:
        if device != "cuda" or "cublas64_12.dll" not in str(error).lower():
            print(f"Прогрев Whisper не выполнен: {error}")
            return
        print("GPU недоступен при прогреве, использую CPU")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        list(model.transcribe(np.zeros(TARGET_SAMPLE_RATE // 10, dtype=np.float32), language=language, beam_size=beam_size)[0])
    model_cache["model"] = model
    print(f"Whisper прогрет за: {time.perf_counter() - started_at:.1f} секунд")


def warmup_dispatcher(dispatcher_config: dict) -> None:
    print("Прогрев диспетчера...")
    result = dispatch(
        'Короткая проверка прогрева. Верни JSON с say "Готово" и пустым task.',
        dispatcher_config,
        ROOT,
        timeout=90.0,
    )
    if result is None:
        print("Предупреждение: прогрев диспетчера не удался, продолжаю работу")
    else:
        print("Диспетчер готов")


def main() -> None:
    hotkey_name, recordings_folder, whisper_model, whisper_device, beam_size, language, dispatcher_config, tts_config = load_config()
    hotkey = key_from_name(hotkey_name)
    recordings_folder.mkdir(parents=True, exist_ok=True)

    recording = False
    stop_recording = threading.Event()
    audio_chunks: list = []
    started_at = 0.0
    model_cache: dict = {}
    speech = SpeechManager(tts_config)
    print("Прогрев Whisper...")
    warmup_whisper(whisper_model, whisper_device, beam_size, language, model_cache)
    threading.Thread(target=warmup_dispatcher, args=(dispatcher_config,), daemon=True).start()

    def on_audio(data, frames, callback_time, status):
        if status:
            print(f"Предупреждение аудио: {status}")
        if recording:
            audio_chunks.append(data.copy())

    def on_press(key):
        nonlocal recording, started_at, audio_chunks
        if key == hotkey and not recording:
            speech.stop()
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
                    recognized_text = transcribe(
                        output_file, whisper_model, whisper_device, beam_size, language, model_cache
                    )
                    response_started_at = time.perf_counter()

                    def on_sentence(sentence: str) -> None:
                        if not getattr(on_sentence, "started", False):
                            on_sentence.started = True
                            speech.speak(sentence, response_started_at)
                        else:
                            speech.enqueue(sentence)
                        print(f"Скажу: {sentence}")

                    result = dispatch_stream(recognized_text, dispatcher_config, ROOT, on_sentence)
                    if result is not None:
                        print(f"Задача: {result['task'] or 'нет'}")
                    stop_recording.clear()
                time.sleep(0.01)
            listener.join()


if __name__ == "__main__":
    main()
