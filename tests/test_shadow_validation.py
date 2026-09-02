import json
import sqlite3
from pathlib import Path

import pytest

from tools import v014_shadow_validation as shadow


def make_live_data(root: Path) -> tuple[Path, sqlite3.Connection]:
    live = root / "live-data"
    live.mkdir()
    db = live / shadow.DATABASE_NAME
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
    connection.execute("INSERT INTO orders (title) VALUES (?)", ("real committed order",))
    connection.commit()
    (live / "home-assistant-token").write_text("secret-copy-only", encoding="utf-8")
    (live / "nested").mkdir()
    (live / "nested" / "note.txt").write_text("keep me", encoding="utf-8")
    return live, connection


def test_candidate_is_exactly_versioned_and_digest_pinned():
    assert shadow.EXPECTED_VERSION == "0.14.0-dev.1"
    assert shadow.IMAGE.startswith(
        "ghcr.io/mikefox303/3d-print-cost-umbrel:0.14.0-dev.1@sha256:"
    )
    assert shadow.IMAGE.endswith(
        "ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0"
    )
    shadow.require_pinned_image()

    with pytest.raises(shadow.ShadowError, match="pinned"):
        shadow.require_pinned_image("ghcr.io/example/app:latest")


def test_snapshot_uses_sqlite_online_backup_and_copies_non_database_files(tmp_path):
    live, connection = make_live_data(tmp_path)
    try:
        snapshot = shadow.create_snapshot(live, tmp_path / "snapshots")

        with sqlite3.connect(snapshot / shadow.DATABASE_NAME) as copied:
            row = copied.execute("SELECT title FROM orders").fetchone()
            assert row == ("real committed order",)
            assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)

        assert (snapshot / "home-assistant-token").read_text(encoding="utf-8") == "secret-copy-only"
        assert (snapshot / "nested" / "note.txt").read_text(encoding="utf-8") == "keep me"
        assert not (snapshot / f"{shadow.DATABASE_NAME}-wal").exists()
        assert not (snapshot / f"{shadow.DATABASE_NAME}-shm").exists()

        marker = json.loads((snapshot / shadow.MARKER_NAME).read_text(encoding="utf-8"))
        assert marker["schema"] == "3d-print-cost-v014-shadow-v1"
        assert marker["source_data_dir"] == str(live.resolve())
        assert marker["image"] == shadow.IMAGE

        # The running/source DB remains untouched and readable.
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone() == (1,)
    finally:
        connection.close()


def test_snapshot_root_must_not_be_inside_live_data(tmp_path):
    live, connection = make_live_data(tmp_path)
    try:
        with pytest.raises(shadow.ShadowError, match="outside the live data"):
            shadow.create_snapshot(live, live / "bad-snapshot-root")
        assert not (live / "bad-snapshot-root").exists()
    finally:
        connection.close()


def test_docker_run_mounts_only_snapshot_and_uses_packaged_uid(tmp_path):
    live, connection = make_live_data(tmp_path)
    try:
        snapshot = shadow.create_snapshot(live, tmp_path / "snapshots")
        args = shadow.build_docker_run_args(snapshot, 18585)
        joined = " ".join(args)

        assert shadow.IMAGE == args[-1]
        assert "--user 1000:1000" in joined
        assert "0.0.0.0:18585:8080" in args
        assert f"{snapshot.resolve()}:/data:rw" in args
        assert not shadow._docker_args_include_live_path(args, live)
        assert f"{live.resolve()}:/data" not in joined
    finally:
        connection.close()


def test_cleanup_requires_marker_and_stopped_container(tmp_path, monkeypatch):
    live, connection = make_live_data(tmp_path)
    try:
        snapshot = shadow.create_snapshot(live, tmp_path / "snapshots")

        monkeypatch.setattr(shadow, "_container_exists", lambda: True)
        with pytest.raises(shadow.ShadowError, match="run stop first"):
            shadow.cleanup(snapshot)
        assert snapshot.exists()

        monkeypatch.setattr(shadow, "_container_exists", lambda: False)
        shadow.cleanup(snapshot)
        assert not snapshot.exists()

        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        with pytest.raises(shadow.ShadowError, match="no v0.14 shadow marker"):
            shadow.cleanup(unrelated)
        assert unrelated.exists()
    finally:
        connection.close()


def test_cleanup_rejects_tampered_marker(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / shadow.MARKER_NAME).write_text(
        json.dumps(
            {
                "schema": "3d-print-cost-v014-shadow-v1",
                "image": "ghcr.io/example/wrong@sha256:" + "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(shadow, "_container_exists", lambda: False)

    with pytest.raises(shadow.ShadowError, match="does not match"):
        shadow.cleanup(snapshot)
    assert snapshot.exists()


def test_port_validation_is_unprivileged_and_bounded():
    assert shadow.validate_port(18585) == 18585
    with pytest.raises(shadow.ShadowError):
        shadow.validate_port(80)
    with pytest.raises(shadow.ShadowError):
        shadow.validate_port(70000)
