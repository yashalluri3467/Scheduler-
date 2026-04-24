"""
env.py - lightweight .env loader for local configuration.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
_DOTENV_LOADED = False


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]

    return key, value


def load_dotenv(dotenv_path: Optional[str | Path] = None) -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    path = Path(dotenv_path) if dotenv_path else BASE_DIR / ".env"
    if not path.exists():
        _DOTENV_LOADED = True
        return

    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                parsed = _parse_dotenv_line(raw_line)
                if not parsed:
                    continue
                key, value = parsed
                os.environ.setdefault(key, value)
    finally:
        _DOTENV_LOADED = True


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    load_dotenv()
    return os.getenv(name, default)


def resolve_path(value: Optional[str], base_dir: Optional[Path] = None) -> Optional[Path]:
    if not value:
        return None

    base = base_dir or BASE_DIR
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path
