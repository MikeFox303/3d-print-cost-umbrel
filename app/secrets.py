from __future__ import annotations

import os
from pathlib import Path

from .db import DATA_DIR

HOME_ASSISTANT_TOKEN_ENV = "HOME_ASSISTANT_TOKEN"
HOME_ASSISTANT_TOKEN_FILE = "home-assistant-token"


def _secret_file(data_dir: Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    return root / "secrets" / HOME_ASSISTANT_TOKEN_FILE


def get_home_assistant_token(data_dir: Path | None = None) -> tuple[str, str | None]:
    """Return the HA token and its source without ever logging or exposing it."""
    env_token = os.getenv(HOME_ASSISTANT_TOKEN_ENV, "").strip()
    if env_token:
        return env_token, "environment"

    path = _secret_file(data_dir)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "", None
    except OSError:
        return "", None
    return (token, "local_file") if token else ("", None)


def save_home_assistant_token(token: str, data_dir: Path | None = None) -> Path:
    token = str(token or "").strip()
    if not token:
        raise ValueError("Home Assistant token must not be empty")

    path = _secret_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    temporary = path.with_suffix(".tmp")
    temporary.write_text(token + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
    return path


def clear_home_assistant_token(data_dir: Path | None = None) -> bool:
    path = _secret_file(data_dir)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
