#!/usr/bin/env python3
"""Launch the immutable v0.14 candidate against a disposable copy of live data.

The installed Community App is never stopped or edited. The validation
container receives only a snapshot directory; the live data path is never
passed to Docker. SQLite is copied with the online backup API so the source app
can remain running while the snapshot is created.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

EXPECTED_VERSION = "0.14.0-dev.1"
IMAGE = (
    f"ghcr.io/mikefox303/3d-print-cost-umbrel:{EXPECTED_VERSION}"
    "@sha256:ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0"
)
CONTAINER_NAME = "3d-print-cost-v014-shadow"
DATABASE_NAME = "3d-cost.db"
MARKER_NAME = ".v014-shadow-validation.json"
DEFAULT_PORT = 18585


class ShadowError(RuntimeError):
    pass


def require_pinned_image(image: str = IMAGE) -> None:
    if "@sha256:" not in image:
        raise ShadowError("validation image must be pinned to an immutable sha256 digest")
    digest = image.rsplit("@sha256:", 1)[1]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise ShadowError("validation image contains an invalid sha256 digest")


def validate_live_data_dir(raw: str | Path) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ShadowError(f"live data directory does not exist: {path}")
    db = path / DATABASE_NAME
    if not db.is_file():
        raise ShadowError(f"expected SQLite database is missing: {db}")
    return path


def validate_port(port: int) -> int:
    if not 1024 <= int(port) <= 65535:
        raise ShadowError("port must be between 1024 and 65535")
    return int(port)


def ensure_port_available(port: int) -> int:
    port = validate_port(port)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", port))
    except OSError as exc:
        raise ShadowError(f"port {port} is not available on the host: {exc}") from exc
    finally:
        probe.close()
    return port


def validate_snapshot_root(live_data_dir: Path, snapshot_root: Path) -> Path:
    live_data_dir = live_data_dir.resolve()
    snapshot_root = snapshot_root.expanduser().resolve()
    if snapshot_root == live_data_dir or live_data_dir in snapshot_root.parents:
        raise ShadowError("snapshot root must be outside the live data directory")
    return snapshot_root


def _copy_non_database_files(source: Path, destination: Path) -> None:
    excluded = {DATABASE_NAME, f"{DATABASE_NAME}-wal", f"{DATABASE_NAME}-shm"}
    for item in source.iterdir():
        if item.name in excluded:
            continue
        target = destination / item.name
        if item.is_symlink():
            target.symlink_to(os.readlink(item))
        elif item.is_dir():
            shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target)


def _backup_sqlite(source_db: Path, destination_db: Path) -> None:
    source_uri = source_db.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True, timeout=10.0) as source:
            with sqlite3.connect(destination_db) as destination:
                source.backup(destination)
                row = destination.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise ShadowError(f"SQLite online snapshot failed: {exc}") from exc
    if not row or row[0] != "ok":
        raise ShadowError("snapshot SQLite integrity_check did not return 'ok'")


def create_snapshot(live_data_dir: Path, snapshot_root: Path) -> Path:
    live_data_dir = validate_live_data_dir(live_data_dir)
    snapshot_root = validate_snapshot_root(live_data_dir, snapshot_root)
    snapshot_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = snapshot_root / f"3d-print-cost-v014-{stamp}"
    suffix = 1
    while snapshot.exists():
        snapshot = snapshot_root / f"3d-print-cost-v014-{stamp}-{suffix}"
        suffix += 1
    snapshot.mkdir(mode=0o700)

    try:
        _copy_non_database_files(live_data_dir, snapshot)
        _backup_sqlite(live_data_dir / DATABASE_NAME, snapshot / DATABASE_NAME)
        marker = {
            "schema": "3d-print-cost-v014-shadow-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_data_dir": str(live_data_dir),
            "image": IMAGE,
            "database": DATABASE_NAME,
        }
        (snapshot / MARKER_NAME).write_text(
            json.dumps(marker, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise
    return snapshot


def build_docker_run_args(snapshot: Path, port: int) -> list[str]:
    snapshot = snapshot.resolve()
    port = validate_port(port)
    return [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "--restart",
        "no",
        "--user",
        "1000:1000",
        "--label",
        "3d-print-cost.validation=v0.14-shadow",
        "--label",
        f"3d-print-cost.snapshot={snapshot}",
        "-e",
        "DATA_DIR=/data",
        "-e",
        "PORT=8080",
        "-p",
        f"0.0.0.0:{port}:8080",
        "-v",
        f"{snapshot}:/data:rw",
        IMAGE,
    ]


def _run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise ShadowError(f"required command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ShadowError(f"command failed: {' '.join(command)}{': ' + detail if detail else ''}") from exc


def _container_exists() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", CONTAINER_NAME],
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise ShadowError("required command not found: docker") from exc
    if result.returncode == 0:
        return True
    detail = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
    lowered = detail.lower()
    if "no such object" in lowered or "no such container" in lowered:
        return False
    raise ShadowError(f"cannot inspect Docker state safely{': ' + detail if detail else ''}")


def _wait_for_health(port: int, timeout: float = 45.0) -> dict:
    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    version = str(payload.get("version") or "")
                    if version != EXPECTED_VERSION:
                        raise ShadowError(
                            f"shadow health endpoint reports {version!r}, expected {EXPECTED_VERSION!r}"
                        )
                    return payload
                last_error = f"HTTP {response.status}: {payload}"
        except ShadowError:
            raise
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(1.0)
    raise ShadowError(f"shadow container did not become healthy: {last_error}")


def _lan_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        output = _run(["hostname", "-I"]).stdout
        for token in output.split():
            try:
                parsed = socket.inet_aton(token)
            except OSError:
                continue
            if parsed and not token.startswith("127.") and token not in addresses:
                addresses.append(token)
    except ShadowError:
        pass
    return addresses


def _docker_args_include_live_path(args: list[str], live_data_dir: Path) -> bool:
    live = str(live_data_dir.resolve())
    return any(arg == live or arg.startswith(f"{live}:") for arg in args)


def start(live_data_dir: Path, snapshot_root: Path, port: int) -> Path:
    require_pinned_image()
    port = ensure_port_available(port)
    if os.name != "posix":
        raise ShadowError("shadow launcher is intended for the Linux Umbrel host")
    if hasattr(os, "geteuid") and os.geteuid() != 1000:
        raise ShadowError(
            "run this helper as the normal Umbrel user (UID 1000), not with sudo; "
            "the validation container intentionally matches the packaged runtime user"
        )
    if _container_exists():
        raise ShadowError(
            f"container {CONTAINER_NAME!r} already exists; run the stop command first"
        )

    live_data_dir = validate_live_data_dir(live_data_dir)
    snapshot_root = validate_snapshot_root(live_data_dir, snapshot_root)
    snapshot = create_snapshot(live_data_dir, snapshot_root)
    print(f"Snapshot created: {snapshot}")
    print("Pulling immutable v0.14 candidate...")
    try:
        _run(["docker", "pull", IMAGE], capture=False)
        args = build_docker_run_args(snapshot, port)
        if _docker_args_include_live_path(args, live_data_dir):
            raise ShadowError("internal safety check failed: live data path reached Docker args")
        _run(args)
        payload = _wait_for_health(port)
    except Exception:
        if _container_exists():
            subprocess.run(
                ["docker", "rm", "-f", CONTAINER_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        raise

    print(f"Shadow healthy: version={payload.get('version', '?')}")
    print(f"Local check: http://127.0.0.1:{port}")
    addresses = _lan_addresses()
    if addresses:
        print("iPhone/LAN URL candidates:")
        for address in addresses:
            print(f"  http://{address}:{port}")
    else:
        print(f"iPhone/LAN URL: http://<RASPBERRY-PI-IP>:{port}")
    print("Live v0.13 data was not mounted. The shadow is using only the snapshot above.")
    print("Keep this port LAN/VPN-only; do not forward it from the router to the public internet.")
    return snapshot


def stop() -> None:
    if not _container_exists():
        print(f"Shadow container {CONTAINER_NAME!r} is not present.")
        return
    snapshot = ""
    try:
        snapshot = _run(
            [
                "docker",
                "inspect",
                "--format",
                '{{ index .Config.Labels "3d-print-cost.snapshot" }}',
                CONTAINER_NAME,
            ]
        ).stdout.strip()
    except ShadowError:
        pass
    _run(["docker", "rm", "-f", CONTAINER_NAME])
    print("Shadow container removed. The installed Community App was not touched.")
    if snapshot:
        print(f"Snapshot preserved: {snapshot}")
        print(f"Delete it only when finished: {sys.executable} {Path(__file__).name} cleanup {snapshot!r}")


def cleanup(snapshot_raw: str | Path) -> None:
    if _container_exists():
        raise ShadowError("refusing cleanup while the shadow container exists; run stop first")
    snapshot = Path(snapshot_raw).expanduser().resolve()
    marker_path = snapshot / MARKER_NAME
    if not snapshot.is_dir() or not marker_path.is_file():
        raise ShadowError("refusing cleanup: directory has no v0.14 shadow marker")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowError("refusing cleanup: invalid v0.14 shadow marker") from exc
    if marker.get("schema") != "3d-print-cost-v014-shadow-v1" or marker.get("image") != IMAGE:
        raise ShadowError("refusing cleanup: marker does not match this v0.14 candidate")
    shutil.rmtree(snapshot)
    print(f"Deleted validation snapshot: {snapshot}")


def status() -> None:
    if not _container_exists():
        print("Shadow container: stopped/not present")
        return
    output = _run(
        [
            "docker",
            "inspect",
            "--format",
            'status={{.State.Status}} image={{.Config.Image}} snapshot={{ index .Config.Labels "3d-print-cost.snapshot" }}',
            CONTAINER_NAME,
        ]
    ).stdout.strip()
    print(f"Shadow container: {output}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the immutable v0.14 candidate beside the installed v0.13 app using a copied data snapshot."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start", help="create a safe data snapshot and launch the shadow container")
    start_parser.add_argument("--data-dir", required=True, help="live installed app data directory containing 3d-cost.db")
    start_parser.add_argument(
        "--snapshot-root",
        default="/tmp",
        help="parent directory for the copied validation snapshot (default: /tmp)",
    )
    start_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"LAN port (default: {DEFAULT_PORT})")

    sub.add_parser("stop", help="remove only the shadow container and preserve its snapshot")
    cleanup_parser = sub.add_parser("cleanup", help="delete a preserved snapshot after marker validation")
    cleanup_parser.add_argument("snapshot_dir")
    sub.add_parser("status", help="show shadow container state")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "start":
            start(Path(args.data_dir), Path(args.snapshot_root), args.port)
        elif args.command == "stop":
            stop()
        elif args.command == "cleanup":
            cleanup(args.snapshot_dir)
        elif args.command == "status":
            status()
        return 0
    except ShadowError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
