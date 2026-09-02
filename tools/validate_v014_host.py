#!/usr/bin/env python3
"""Network-only preflight for a physical 3D Print Cost umbrelOS install.

This tool intentionally performs only HTTP GET requests against the app itself.
It does not connect to SQLite, Spoolman, Home Assistant or Bambuddy and never
writes business data.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_EXPECTED_VERSION = "0.14.0-dev.1"
KEY_PAGES = ("/", "/orders/new", "/filaments", "/stats", "/system")


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


def normalize_base_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("base URL must include http:// or https:// and a host")
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


def _run_check(label: str, action) -> bool:
    try:
        detail = action()
    except ValidationError as exc:
        print(f"[FAIL] {label}: {exc}")
        return False
    suffix = f": {detail}" if detail else ""
    print(f"[PASS] {label}{suffix}")
    return True


def run(base_url: str, expected_version: str, timeout: float) -> int:
    base_url = normalize_base_url(base_url)
    print(f"3D Print Cost v0.14 real-host preflight")
    print(f"Target: {base_url}")
    print(f"Expected version: {expected_version or 'any'}")
    print()

    passed = True

    def health_check():
        response = fetch(base_url, "/healthz", timeout)
        version = validate_health(response, expected_version)
        return f"status=ok version={version}, dynamic no-store headers OK"

    passed &= _run_check("Health/API boundary", health_check)

    def manifest_check():
        validate_manifest(fetch(base_url, "/static/manifest.webmanifest", timeout))
        return "standalone/root scope/icons OK"

    passed &= _run_check("Web app manifest", manifest_check)

    def shell_check():
        validate_shell(fetch(base_url, "/", timeout))
        return "manifest + connectivity shell linked"

    passed &= _run_check("Shared phone shell", shell_check)

    for path in KEY_PAGES:
        def page_check(path=path):
            response = fetch(base_url, path, timeout)
            if response.status != 200:
                raise ValidationError(f"HTTP {response.status}")
            return "HTTP 200"

        passed &= _run_check(f"Page {path}", page_check)

    print()
    if passed:
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args.base_url, args.expected_version, args.timeout)
    except ValidationError as exc:
        print(f"[FAIL] Input: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
