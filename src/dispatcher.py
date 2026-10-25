"""Вызов OpenAI-совместимого API диспетчера."""

import json
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


def dispatch(text: str, config: dict, root: Path) -> dict[str, str] | None:
    load_dotenv(root / ".env")
    prompt_path = root / "prompts" / "dispatcher.txt"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"Ошибка диспетчера: не удалось прочитать {prompt_path}: {error}")
        return None
    import os

    provider = str(config.get("provider", "")).lower()
    api_key_env = config.get("api_key_env")
    api_key = os.getenv(str(api_key_env)) if api_key_env else None
    if not api_key:
        if provider == "ollama":
            api_key = "ollama"
        else:
            env_name = str(api_key_env or "DISPATCHER_API_KEY")
            print(f"Диспетчер не настроен: в .env нет переменной {env_name}")
            return None

    model = str(config.get("model", "CHANGE_ME"))
    if model == "CHANGE_ME":
        print("Диспетчер не настроен: укажите название модели в config.json")
        return None

    try:
        client = OpenAI(api_key=api_key, base_url=str(config.get("base_url", "")) or None)
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": float(config.get("temperature", 0.2)),
        }
        if provider == "ollama":
            request["response_format"] = {"type": "json_object"}
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
