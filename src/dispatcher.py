"""Вызов OpenAI-совместимого API диспетчера."""

import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def parse_response(content: str) -> dict[str, str]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("ответ не содержит JSON") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError("ответ содержит некорректный JSON") from error

    if not isinstance(data, dict):
        raise ValueError("ответ JSON должен быть объектом")

    say = data.get("say")
    if not isinstance(say, str) or not say.strip():
        raise ValueError("поле say должно быть непустой строкой")

    task = data.get("task")
    normalized_task = task.strip() if isinstance(task, str) and task.strip() else ""
    return {"say": say.strip(), "task": normalized_task}


def _client_and_request(config: dict, root: Path, timeout: float | None = None):
    load_dotenv(root / ".env")
    provider = str(config.get("provider", "")).lower()
    api_key_env = config.get("api_key_env")
    api_key = os.getenv(str(api_key_env)) if api_key_env else None
    if not api_key:
        if provider == "ollama":
            api_key = "ollama"
        else:
            env_name = str(api_key_env or "DISPATCHER_API_KEY")
            print(f"Диспетчер не настроен: в .env нет переменной {env_name}")
            return None, None
    model = str(config.get("model", "CHANGE_ME"))
    if model == "CHANGE_ME":
        print("Диспетчер не настроен: укажите название модели в config.json")
        return None, None
    prompt_path = root / "prompts" / "dispatcher.txt"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"Ошибка диспетчера: не удалось прочитать {prompt_path}: {error}")
        return None, None
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
        ],
        "temperature": float(config.get("temperature", 0.2)),
    }
    if provider == "ollama":
        request["response_format"] = {"type": "json_object"}
    client_options = {"api_key": api_key, "base_url": str(config.get("base_url", "")) or None}
    if timeout is not None:
        client_options["timeout"] = timeout
    return OpenAI(**client_options), request


def _say_fragment(raw: str) -> tuple[str, bool]:
    match = re.search(r'"say"\s*:\s*"', raw)
    if not match:
        return "", False
    start = match.end()
    escaped = False
    end = len(raw)
    for index in range(start, len(raw)):
        char = raw[index]
        if char == '"' and not escaped:
            end = index
            break
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    closed = end < len(raw)
    return raw[start:end].replace("\\n", "\n").replace('\\"', '"'), closed


def _take_sentences(text: str, final: bool = False) -> tuple[list[str], str]:
    matches = list(re.finditer(r".+?(?:[.!?…]+(?=\s|$)|$)", text, flags=re.S))
    if not matches:
        return [], text
    sentences = []
    consumed = 0
    for match in matches:
        value = match.group(0).strip()
        if not value:
            continue
        if not final and not re.search(r"[.!?…]+$", value):
            break
        sentences.append(value)
        consumed = match.end()
    return sentences, text[consumed:]


def dispatch_stream(text: str, config: dict, root: Path, on_sentence) -> dict[str, str] | None:
    client, request = _client_and_request(config, root)
    if client is None:
        return None
    request["messages"].append({"role": "user", "content": text})
    started_at = time.perf_counter()
    first_fragment_at = None
    raw = ""
    say_seen = ""
    say_sent = False
    try:
        response = client.chat.completions.create(**request, stream=True)
        for chunk in response:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            if first_fragment_at is None:
                first_fragment_at = time.perf_counter()
            raw += delta
            current_say, say_closed = _say_fragment(raw)
            if current_say.startswith(say_seen):
                say_seen = current_say
                if say_closed and not say_sent:
                    say_sent = True
                    print(f"Время до закрытия поля say: {time.perf_counter() - started_at:.1f} секунд")
                    for sentence in _take_sentences(current_say, final=True)[0]:
                        on_sentence(sentence)
        result = parse_response(raw)
        if not say_sent:
            for sentence in _take_sentences(result["say"], final=True)[0]:
                on_sentence(sentence)
        print(f"Время до первого фрагмента ответа: {(first_fragment_at - started_at) if first_fragment_at else 0:.1f} секунд")
        return result
    except Exception as error:
        print(f"Потоковый ответ недоступен ({error}), использую обычный JSON")
        result = dispatch(text, config, root)
        print(f"Время до первого фрагмента ответа: {time.perf_counter() - started_at:.1f} секунд")
        if result is not None:
            on_sentence(result["say"])
        return result


def dispatch(text: str, config: dict, root: Path, timeout: float | None = None) -> dict[str, str] | None:
    try:
        client, request = _client_and_request(config, root, timeout)
        if client is None:
            return None
        request["messages"].append({"role": "user", "content": text})
        response = client.chat.completions.create(**request)
        content = response.choices[0].message.content or ""
        try:
            return parse_response(content)
        except ValueError as error:
            print(f"Ошибка разбора ответа диспетчера: {error}")
            print(f"Сырой ответ модели: {content}")
            return None
    except Exception as error:
        print(f"Ошибка диспетчера: {error}")
        return None
