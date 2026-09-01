from __future__ import annotations

import platform
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import __version__
from .db import DATA_DIR, engine
from .migrations import migration_status
from .secrets import get_home_assistant_token


def _storage_status(data_dir: Path) -> dict:
    data_dir = Path(data_dir)
    result = {
        "path": str(data_dir),
        "exists": data_dir.exists(),
        "is_directory": data_dir.is_dir(),
        "writable": False,
    }
    if not result["is_directory"]:
        return result

    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".system-check-",
            dir=data_dir,
            delete=False,
        ) as probe:
            probe.write("ok\n")
            probe_path = Path(probe.name)
        result["writable"] = True
    except OSError:
        result["writable"] = False
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink()
            except OSError:
                pass
    return result


def _database_file_status(db_engine: Engine) -> dict:
    if db_engine.dialect.name != "sqlite":
        return {"dialect": db_engine.dialect.name, "name": None, "exists": None, "size_bytes": None}

    database = db_engine.url.database
    if not database or database == ":memory:":
        return {"dialect": "sqlite", "name": ":memory:", "exists": True, "size_bytes": None}

    path = Path(database).expanduser()
    try:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
    except OSError:
        exists = False
        size = None
    return {
        "dialect": "sqlite",
        "name": path.name,
        "exists": exists,
        "size_bytes": size,
    }


def build_system_check(
    settings: dict,
    *,
    db_engine: Engine = engine,
    data_dir: Path = DATA_DIR,
) -> dict:
    """Build a browser-safe runtime report without network calls or secret values."""

    storage = _storage_status(Path(data_dir))
    database_file = _database_file_status(db_engine)

    database_reachable = False
    database_error: str | None = None
    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_reachable = True
    except Exception as exc:  # diagnostics must report failure instead of crashing the page
        database_error = type(exc).__name__

    try:
        schema = migration_status(db_engine)
        schema_error = None
    except Exception as exc:  # do not expose raw DB exception strings in the browser
        schema = {"head_version": None, "applied_versions": [], "up_to_date": False}
        schema_error = type(exc).__name__

    token, token_source = get_home_assistant_token(Path(data_dir))
    spoolman_enabled = bool(settings.get("spoolman_enabled"))
    spoolman_configured = bool(str(settings.get("spoolman_url") or "").strip())
    home_assistant_enabled = bool(settings.get("home_assistant_enabled"))
    home_assistant_base_configured = bool(
        str(settings.get("home_assistant_url") or "").strip()
        and str(settings.get("home_assistant_energy_entity") or "").strip()
    )
    home_assistant_configured = home_assistant_base_configured and bool(token)

    checks = {
        "persistent_storage": "ok" if storage["writable"] else "error",
        "database": "ok" if database_reachable else "error",
        "migrations": "ok" if schema.get("up_to_date") else "error",
        "spoolman": (
            "ok" if not spoolman_enabled or spoolman_configured else "warning"
        ),
        "home_assistant": (
            "ok" if not home_assistant_enabled or home_assistant_configured else "warning"
        ),
    }
    critical_ok = all(checks[name] == "ok" for name in ("persistent_storage", "database", "migrations"))
    optional_ok = all(checks[name] == "ok" for name in ("spoolman", "home_assistant"))

    return {
        "status": "ok" if critical_ok and optional_ok else "degraded",
        "version": __version__,
        "runtime": {
            "python": platform.python_version(),
            "machine": platform.machine() or "unknown",
            "platform": sys.platform,
        },
        "storage": storage,
        "database": {
            "reachable": database_reachable,
            "error_type": database_error,
            **database_file,
        },
        "migrations": {
            **schema,
            "error_type": schema_error,
        },
        "integrations": {
            "spoolman": {
                "enabled": spoolman_enabled,
                "configured": spoolman_configured,
                "read_only": True,
            },
            "home_assistant": {
                "enabled": home_assistant_enabled,
                "configured": home_assistant_configured,
                "token_configured": bool(token),
                "token_source": token_source,
                "read_only": True,
            },
        },
        "checks": checks,
        "secrets_exposed": False,
        "network_requests_performed": False,
    }
