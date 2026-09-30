"""Configuration: environment variables with a .env fallback.

Every script reads settings through `cfg()`. Values come from the process
environment first, then from a `.env` file next to the project root. Nothing
here is secret-aware; keep real secrets out of git (see .gitignore).
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("WACAL_STATE_DIR", PROJECT_ROOT / "state"))


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        values[key.strip()] = val
    return values


_DOTENV = _load_dotenv(PROJECT_ROOT / ".env")


def cfg(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.environ.get(name) or _DOTENV.get(name) or default
    if required and not val:
        raise SystemExit(
            f"Missing required setting {name}. Set it in the environment or in "
            f"{PROJECT_ROOT / '.env'} (see .env.example)."
        )
    return val


def state_path(name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / name
