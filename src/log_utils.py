"""Дневной журнал работы ассистента."""

from datetime import datetime
from pathlib import Path


def log_event(root: Path, event: str, details: str = "") -> None:
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (logs_dir / f"{datetime.now():%Y-%m-%d}.log").open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {event}: {details}\n")
