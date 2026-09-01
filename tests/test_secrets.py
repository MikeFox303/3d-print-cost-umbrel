import os
from pathlib import Path

from app.secrets import (
    clear_home_assistant_token,
    get_home_assistant_token,
    save_home_assistant_token,
)


def test_local_home_assistant_token_is_persistent_and_private(tmp_path, monkeypatch):
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)
    path = save_home_assistant_token("secret-value", data_dir=tmp_path)

    assert path == tmp_path / "secrets" / "home-assistant-token"
    assert path.read_text(encoding="utf-8").strip() == "secret-value"
    assert path.stat().st_mode & 0o777 == 0o600
    token, source = get_home_assistant_token(data_dir=tmp_path)
    assert token == "secret-value"
    assert source == "local_file"


def test_environment_token_overrides_local_file(tmp_path, monkeypatch):
    save_home_assistant_token("file-token", data_dir=tmp_path)
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "env-token")
    token, source = get_home_assistant_token(data_dir=tmp_path)
    assert token == "env-token"
    assert source == "environment"


def test_clear_local_token_does_not_touch_environment(tmp_path, monkeypatch):
    save_home_assistant_token("file-token", data_dir=tmp_path)
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "env-token")
    assert clear_home_assistant_token(data_dir=tmp_path) is True
    assert not (tmp_path / "secrets" / "home-assistant-token").exists()
    assert get_home_assistant_token(data_dir=tmp_path) == ("env-token", "environment")
