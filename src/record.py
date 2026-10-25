"""Запись голоса при удержании горячей клавиши."""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


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
    from executor import execute, run_file, run_requested
    from log_utils import log_event
    from tts import SpeechManager
except ImportError:
    from .dispatcher import dispatch
    from .dispatcher import dispatch_stream
    from .executor import execute, run_file, run_requested
    from .log_utils import log_event
    from .tts import SpeechManager


ROOT = Path(__file__).resolve().parent.parent
TARGET_SAMPLE_RATE = 16_000


def load_config() -> tuple[str, Path, str, str, int, str, str, dict, dict, dict]:
    with (ROOT / "config.json").open(encoding="utf-8") as file:
        config = json.load(file)
    hotkey = str(config.get("hotkey", "F9")).upper()
    recordings_folder = ROOT / str(config.get("recordings_folder", "workspace"))
    whisper_model = str(config.get("whisper_model", "small"))
    whisper_device = str(config.get("whisper_device", "cpu")).lower()
    beam_size = int(config.get("beam_size", 5))
    language = str(config.get("language", "ru"))
    initial_prompt = str(config.get("initial_prompt", ""))
    dispatcher_config = config.get("dispatcher", {})
    tts_config = config.get("tts", {})
    voice_activation = config.get("voice_activation", {})
    return hotkey, recordings_folder, whisper_model, whisper_device, beam_size, language, initial_prompt, dispatcher_config, tts_config, voice_activation


def normalize_text(text: str) -> str:
    return " ".join(re.sub(r"[^а-яёa-z0-9]+", " ", text.lower()).split())


def extract_wake_command(text: str, wake_words: list[str]) -> tuple[bool, str]:
    normalized = normalize_text(text)
    for wake_word in sorted((normalize_text(word) for word in wake_words), key=len, reverse=True):
        if normalized == wake_word:
            return True, ""
        if normalized.startswith(wake_word + " "):
            return True, normalized[len(wake_word):].strip()
    return False, normalized


def is_stop_command(text: str) -> bool:
    return normalize_text(text) in {"стоп", "остановись", "отмена", "отменить", "хватит"}


def transcribe(
    audio_file: Path,
    model_name: str,
    device: str,
    beam_size: int,
    language: str,
    initial_prompt: str,
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
        segments, _ = model.transcribe(
            audio, language=language, beam_size=beam_size, initial_prompt=initial_prompt
        )
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


def warmup_whisper(
    model_name: str, device: str, beam_size: int, language: str, initial_prompt: str, model_cache: dict
) -> None:
    started_at = time.perf_counter()
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        list(model.transcribe(np.zeros(TARGET_SAMPLE_RATE // 10, dtype=np.float32), language=language, beam_size=beam_size, initial_prompt=initial_prompt)[0])
    except RuntimeError as error:
        if device != "cuda" or "cublas64_12.dll" not in str(error).lower():
            print(f"Прогрев Whisper не выполнен: {error}")
            return
        print("GPU недоступен при прогреве, использую CPU")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        list(model.transcribe(np.zeros(TARGET_SAMPLE_RATE // 10, dtype=np.float32), language=language, beam_size=beam_size, initial_prompt=initial_prompt)[0])
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


def run_executor(task: str, original_text: str, executor_config: dict, speech: SpeechManager, on_finished, is_current) -> None:
    print("Исполнитель работает...")
    try:
        result = execute(task, original_text, executor_config, ROOT)
        log_event(ROOT, "Результат исполнителя", str(result))
        if result["status"] != "ok":
            print(f"Ошибка исполнителя: {result['details']}")
            speech.speak(result["summary"])
            on_finished(None, False, RuntimeError(result["details"]))
            return
        output_match = re.search(r"Файл: (.+)$", result["details"])
        if output_match is None:
            raise RuntimeError("исполнитель не вернул путь сохранённого файла")
        output_path = Path(output_match.group(1))
        if not is_current():
            print("Результат исполнителя отменён: началась новая запись")
            on_finished(None, False, None)
            return
        print(f"Файл сохранён: {output_path}")
        if run_requested(original_text):
            run_file(output_path, ROOT)
            print(f"Файл запущен: {output_path}")
            speech.speak("Готово, файл запущен")
        else:
            speech.speak(f"Готово, файл сохранён. Выполнить: {output_path.name}? Скажи да или нет")
        on_finished(output_path, run_requested(original_text), None)
    except Exception as error:
        log_event(ROOT, "Исключение исполнителя", str(error))
        print(f"Ошибка исполнителя: {error}")
        speech.speak("Не получилось")
        on_finished(None, False, error)


def main() -> None:
    hotkey_name, recordings_folder, whisper_model, whisper_device, beam_size, language, initial_prompt, dispatcher_config, tts_config, voice_activation = load_config()
    with (ROOT / "config.json").open(encoding="utf-8") as file:
        executor_config = json.load(file).get("executor", {})
    hotkey = key_from_name(hotkey_name)
    always_listen = bool(voice_activation.get("always_listen", True))
    wake_words = [str(word) for word in voice_activation.get("wake_words", ["тора", "ториа", "тори"])]
    wake_response = str(voice_activation.get("wake_response", "Да, слушаю."))
    voice_threshold = float(voice_activation.get("voice_threshold", 0.015))
    silence_duration = float(voice_activation.get("silence_duration", 0.8))
    command_timeout = float(voice_activation.get("command_timeout", 8.0))
    recordings_folder.mkdir(parents=True, exist_ok=True)

    recording = False
    recording_mode = "manual"
    stop_recording = threading.Event()
    audio_chunks: list = []
    started_at = 0.0
    last_voice_at = 0.0
    awaiting_command_until = 0.0
    model_cache: dict = {}
    speech = SpeechManager(tts_config)
    pending_execution = {"path": None, "deadline": 0.0}
    recording_number = 0
    print("Прогрев Whisper...")
    warmup_whisper(whisper_model, whisper_device, beam_size, language, initial_prompt, model_cache)
    threading.Thread(target=warmup_dispatcher, args=(dispatcher_config,), daemon=True).start()

    def on_audio(data, frames, callback_time, status):
        nonlocal recording, recording_mode, audio_chunks, started_at, last_voice_at, recording_number
        if status:
            print(f"Предупреждение аудио: {status}")
        if recording:
            audio_chunks.append(data.copy())
            if always_listen and recording_mode == "voice":
                level = float(np.sqrt(np.mean(np.square(data))))
                if level >= voice_threshold:
                    last_voice_at = time.monotonic()
                elif time.monotonic() - last_voice_at >= silence_duration:
                    stop_recording.set()
        elif always_listen:
            level = float(np.sqrt(np.mean(np.square(data))))
            if level >= voice_threshold:
                recording = True
                recording_mode = "voice"
                recording_number += 1
                started_at = time.monotonic()
                audio_chunks = [data.copy()]
                last_voice_at = started_at
                stop_recording.clear()
                print("Слушаю...")

    def on_press(key):
        nonlocal recording, recording_mode, started_at, audio_chunks, recording_number
        if key == hotkey and not recording:
            speech.stop()
            recording_number += 1
            recording = True
            recording_mode = "manual"
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
                    captured_number = recording_number
                    captured_chunks = audio_chunks
                    captured_mode = recording_mode
                    recording = False
                    duration = time.monotonic() - started_at
                    output_file = recordings_folder / "test.wav"
                    if captured_chunks:
                        sf.write(output_file, np.concatenate(captured_chunks, axis=0), TARGET_SAMPLE_RATE)
                    else:
                        sf.write(output_file, [], TARGET_SAMPLE_RATE)
                    print(f"Запись сохранена, {duration:.1f} секунд")
                    recognized_text = transcribe(
                        output_file, whisper_model, whisper_device, beam_size, language, initial_prompt, model_cache
                    )
                    log_event(ROOT, "Распознанная команда", recognized_text)

                    if captured_number != recording_number:
                        print("Предыдущая запись отменена: началась новая запись")
                        continue

                    if captured_mode == "voice":
                        was_wake, command_text = extract_wake_command(recognized_text, wake_words)
                        if time.monotonic() <= awaiting_command_until:
                            was_wake = True
                            command_text = normalize_text(recognized_text)
                        if not was_wake:
                            stop_recording.clear()
                            continue
                        if not command_text:
                            awaiting_command_until = time.monotonic() + command_timeout
                            speech.speak(wake_response)
                            stop_recording.clear()
                            continue
                        recognized_text = command_text
                        awaiting_command_until = 0.0

                    if is_stop_command(recognized_text):
                        speech.stop()
                        recording_number += 1
                        pending_execution["path"] = None
                        print("Остановлено")
                        stop_recording.clear()
                        continue

                    if pending_execution["path"] is not None:
                        answer = recognized_text.lower().strip()
                        path = pending_execution["path"]
                        pending_execution["path"] = None
                        if time.monotonic() > pending_execution["deadline"]:
                            speech.speak("Время подтверждения истекло")
                        elif answer in {"да", "давай", "выполняй", "подтверждаю"}:
                            try:
                                run_file(path, ROOT)
                                print(f"Файл запущен: {path}")
                                speech.speak("Готово, файл запущен")
                            except Exception as error:
                                print(f"Ошибка запуска файла: {error}")
                                speech.speak("Не получилось")
                        elif answer in {"нет", "отмена", "не надо"}:
                            print("Запуск файла отклонён")
                            speech.speak("Запуск отменён")
                        else:
                            print("Подтверждение не распознано, запуск отменён")
                            speech.speak("Нужно сказать да или нет")
                        stop_recording.clear()
                        continue

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
                        log_event(ROOT, "Ответ диспетчера", str(result))
                        print(f"Задача: {result['task'] or 'нет'}")
                        if result["task"]:
                            log_event(ROOT, "Задача исполнителю", result["task"])
                            def executor_finished(path, started, error):
                                if path is not None and not started:
                                    pending_execution["path"] = path
                                    pending_execution["deadline"] = time.monotonic() + 15
                            threading.Thread(
                                target=run_executor,
                                args=(
                                    result["task"],
                                    recognized_text,
                                    executor_config,
                                    speech,
                                    executor_finished,
                                    lambda number=captured_number: number == recording_number,
                                ),
                                daemon=True,
                            ).start()
                    stop_recording.clear()
                time.sleep(0.01)
            listener.join()


if __name__ == "__main__":
    main()
