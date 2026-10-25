"""Генерация и безопасное сохранение кода локальным исполнителем."""

import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


EXTENSIONS = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "powershell": ".ps1",
    "powershell": ".ps1",
    "bash": ".sh",
    "sh": ".sh",
    "json": ".json",
}


def _extract_code(content: str) -> tuple[str, str]:
    match = re.search(r"```\s*([\w+-]*)\s*\n?(.*?)```", content, flags=re.DOTALL)
    if not match:
        raise ValueError("модель не вернула код в блоке Markdown")
    language = match.group(1).lower()
    code = match.group(2).strip()
    if not code:
        raise ValueError("блок кода пустой")
    return language, code + "\n"


def _extract_filename(content: str) -> str | None:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    if re.fullmatch(r"[a-z][a-z0-9_]{0,28}\.(?:py|js|ts|ps1|sh|json)", first_line):
        return first_line
    return None


def _next_output_path(output_dir: Path, filename: str) -> Path:
    candidate = output_dir / filename
    number = 2
    while candidate.exists():
        stem, extension = Path(filename).stem, Path(filename).suffix
        candidate = output_dir / f"{stem}_{number}{extension}"
        number += 1
    return candidate


def execute(task: str, original_text: str, config: dict, root: Path) -> Path:
    load_dotenv(root / ".env")
    provider = str(config.get("provider", "")).lower()
    api_key_env = config.get("api_key_env")
    api_key = os.getenv(str(api_key_env)) if api_key_env else None
    if not api_key:
        if provider == "ollama":
            api_key = "ollama"
        else:
            raise RuntimeError(f"в .env нет переменной {api_key_env or 'EXECUTOR_API_KEY'}")

    prompt_path = root / "prompts" / "executor.txt"
    system_prompt = prompt_path.read_text(encoding="utf-8")
    client = OpenAI(api_key=api_key, base_url=str(config.get("base_url", "")) or None)
    response = client.chat.completions.create(
        model=str(config.get("model", "CHANGE_ME")),
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Описание задачи исполнителю:\n{task}\n\nИсходная фраза пользователя:\n{original_text}",
            },
        ],
        temperature=float(config.get("temperature", 0.2)),
    )
    content = response.choices[0].message.content or ""
    filename = _extract_filename(content)
    language, code = _extract_code(content)
    output_dir = root / "workspace" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    if filename is None:
        filename = f"script_{datetime.now():%Y%m%d_%H%M%S}.py"
    output_path = _next_output_path(output_dir, filename)
    output_path.write_text(code, encoding="utf-8")
    return output_path
