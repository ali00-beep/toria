"""Вызов OpenAI-совместимого API диспетчера."""

import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


SYSTEM_PROMPT = (
    "Ты голосовой ассистент на ПК. Отвечай по-русски, максимум 2 коротких предложения. "
    "Если нужно что-то сделать на компьютере или написать код, поставь в поле task "
    "описание задачи для исполнителя, а в say скажи коротко, что приступаешь. "
    "Код и длинные тексты в say не пиши."
)


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

    if not isinstance(data, dict) or not isinstance(data.get("say"), str) or not isinstance(data.get("task"), str):
        raise ValueError("JSON должен содержать строковые поля say и task")
    return {"say": data["say"].strip(), "task": data["task"].strip()}


def dispatch(text: str, config: dict, root: Path) -> dict[str, str] | None:
    load_dotenv(root / ".env")
    api_key_env = str(config.get("api_key_env", "DISPATCHER_API_KEY"))
    import os

    api_key = os.getenv(api_key_env)
    if not api_key:
        print(f"Диспетчер не настроен: в .env нет переменной {api_key_env}")
        return None

    model = str(config.get("model", "CHANGE_ME"))
    if model == "CHANGE_ME":
        print("Диспетчер не настроен: укажите название модели в config.json")
        return None

    try:
        client = OpenAI(api_key=api_key, base_url=str(config.get("base_url", "")) or None)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        return parse_response(content)
    except Exception as error:
        print(f"Ошибка диспетчера: {error}")
        return None
