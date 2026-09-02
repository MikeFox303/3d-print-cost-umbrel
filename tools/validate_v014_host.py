#!/usr/bin/env python3
"""Network-only preflight for a physical 3D Print Cost umbrelOS install.

This tool intentionally performs only HTTP GET requests against the app itself.
It does not connect to SQLite, Spoolman, Home Assistant or Bambuddy and never
writes business data. Optional JSON output contains only check metadata/results;
HTTP response bodies, headers, cookies and credentials are never persisted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_EXPECTED_VERSION = "0.14.0-dev.1"
CANDIDATE_IMAGE = (
    "ghcr.io/mikefox303/3d-print-cost-umbrel:0.14.0-dev.1"
    "@sha256:ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0"
)
REPORT_SCHEMA = "3d-print-cost-v014-host-preflight-v1"
KEY_PAGES = ("/", "/orders/new", "/filaments", "/stats", "/system")


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    label: str
    status: str
    detail: str = ""
    error: str = ""


def normalize_base_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("base URL must include http:// or https:// and a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("base URL must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValidationError("base URL must not contain a query string or fragment")
    return value


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return str(value)
    return ""


def validate_health(response: Response, expected_version: str) -> str:
    if response.status != 200:
        raise ValidationError(f"/healthz returned HTTP {response.status}")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("/healthz did not return valid UTF-8 JSON") from exc

    if payload.get("status") != "ok":
        raise ValidationError("/healthz status is not 'ok'")
    version = str(payload.get("version") or "")
    if not version:
        raise ValidationError("/healthz did not report an app version")
    if expected_version and version != expected_version:
        raise ValidationError(
            f"expected version {expected_version}, but Umbrel reports {version}"
        )

    cache_control = _header(response.headers, "Cache-Control").lower()
    pragma = _header(response.headers, "Pragma").lower()
    if "no-store" not in cache_control:
        raise ValidationError("/healthz is missing Cache-Control: no-store")
    if "no-cache" not in pragma:
        raise ValidationError("/healthz is missing Pragma: no-cache")
    return version


def validate_manifest(response: Response) -> None:
    if response.status != 200:
        raise ValidationError(f"manifest returned HTTP {response.status}")
    try:
        manifest = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("manifest is not valid UTF-8 JSON") from exc

    if manifest.get("display") != "standalone":
        raise ValidationError("manifest display must be 'standalone'")
    if manifest.get("start_url") != "/" or manifest.get("scope") != "/":
        raise ValidationError("manifest start_url and scope must both be '/'")

    icons = manifest.get("icons") or []
    sizes = {str(icon.get("sizes") or "") for icon in icons if isinstance(icon, dict)}
    if not {"192x192", "512x512"}.issubset(sizes):
        raise ValidationError("manifest must expose 192x192 and 512x512 icons")


def validate_shell(response: Response) -> None:
    if response.status != 200:
        raise ValidationError(f"dashboard returned HTTP {response.status}")
    try:
        html = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("dashboard is not valid UTF-8 HTML") from exc

    required = (
        'rel="manifest" href="/static/manifest.webmanifest"',
        'src="/static/connectivity.js"',
        "data-connectivity-banner",
        "viewport-fit=cover",
    )
    missing = [token for token in required if token not in html]
    if missing:
        raise ValidationError(f"dashboard shell is missing: {', '.join(missing)}")


def fetch(base_url: str, path: str, timeout: float) -> Response:
    url = urljoin(base_url + "/", path.lstrip("/"))
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "*/*",
            "Cache-Control": "no-cache",
            "User-Agent": "3d-print-cost-v014-preflight/1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as raw:
            return Response(
                status=int(raw.status),
                headers=dict(raw.headers.items()),
                body=raw.read(),
            )
    except HTTPError as exc:
        return Response(
            status=int(exc.code),
            headers=dict(exc.headers.items()) if exc.headers else {},
            body=exc.read(),
        )
    except (URLError, TimeoutError, OSError) as exc:
        raise ValidationError(f"cannot reach {url}: {exc}") from exc


def _run_check(check_id: str, label: str, action) -> CheckResult:
    try:
        detail = str(action() or "")
    except ValidationError as exc:
        error = str(exc)
        print(f"[FAIL] {label}: {error}")
        return CheckResult(check_id=check_id, label=label, status="fail", error=error)
    suffix = f": {detail}" if detail else ""
    print(f"[PASS] {label}{suffix}")
    return CheckResult(check_id=check_id, label=label, status="pass", detail=detail)


def build_report(
    *,
    base_url: str,
    expected_version: str,
    results: list[CheckResult],
    generated_at: str | None = None,
) -> dict:
    passed = bool(results) and all(result.status == "pass" for result in results)
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "candidate": {
            "version": DEFAULT_EXPECTED_VERSION,
            "image": CANDIDATE_IMAGE,
        },
        "target": {
            "base_url": base_url,
            "expected_version": expected_version,
        },
        "result": "pass" if passed else "fail",
        "checks": [asdict(result) for result in results],
    }


def write_report(path_raw: str | Path, report: dict) -> Path:
    path = Path(path_raw).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ValidationError(f"cannot write JSON report {path}: {exc}") from exc
    return path


def run(
    base_url: str,
    expected_version: str,
    timeout: float,
    *,
    json_out: str | Path | None = None,
) -> int:
    base_url = normalize_base_url(base_url)
    print("3D Print Cost v0.14 real-host preflight")
    print(f"Target: {base_url}")
    print(f"Expected version: {expected_version or 'any'}")
    print()

    results: list[CheckResult] = []

    def health_check():
        response = fetch(base_url, "/healthz", timeout)
        version = validate_health(response, expected_version)
        return f"status=ok version={version}, dynamic no-store headers OK"

    results.append(_run_check("health_boundary", "Health/API boundary", health_check))

    def manifest_check():
        validate_manifest(fetch(base_url, "/static/manifest.webmanifest", timeout))
        return "standalone/root scope/icons OK"

    results.append(_run_check("web_manifest", "Web app manifest", manifest_check))

    def shell_check():
        validate_shell(fetch(base_url, "/", timeout))
        return "manifest + connectivity shell linked"

    results.append(_run_check("phone_shell", "Shared phone shell", shell_check))

    for path in KEY_PAGES:
        def page_check(path=path):
            response = fetch(base_url, path, timeout)
            if response.status != 200:
                raise ValidationError(f"HTTP {response.status}")
            return "HTTP 200"

        check_id = "page_root" if path == "/" else f"page_{path.strip('/').replace('/', '_').replace('-', '_')}"
        results.append(_run_check(check_id, f"Page {path}", page_check))

    report = build_report(
        base_url=base_url,
        expected_version=expected_version,
        results=results,
    )
    if json_out is not None:
        report_path = write_report(json_out, report)
        print()
        print(f"JSON report: {report_path}")

    print()
    if report["result"] == "pass":
        print("PRECHECK PASSED — server-side v0.14 checks are ready for iPhone validation.")
        return 0
    print("PRECHECK FAILED — fix the failed server-side checks before iPhone validation.")
    return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a physical 3D Print Cost v0.14 Umbrel installation over HTTP."
    )
    parser.add_argument("base_url", help="Installed app URL, e.g. http://umbrel.local:8080")
    parser.add_argument(
        "--expected-version",
        default=DEFAULT_EXPECTED_VERSION,
        help=f"Expected /healthz version (default: {DEFAULT_EXPECTED_VERSION}); use '' to accept any.",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--json-out",
        help="Optional local path for a secret-free machine-readable validation report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(
            args.base_url,
            args.expected_version,
            args.timeout,
            json_out=args.json_out,
        )
    except ValidationError as exc:
        print(f"[FAIL] Input/report: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
