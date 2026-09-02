import json

import pytest

from tools import validate_v014_host as preflight
from tools.validate_v014_host import (
    CheckResult,
    Response,
    ValidationError,
    build_report,
    normalize_base_url,
    validate_health,
    validate_manifest,
    validate_shell,
    write_report,
)


def response(body, *, status=200, headers=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    return Response(status=status, headers=headers or {}, body=body)


def valid_manifest():
    return {
        "display": "standalone",
        "start_url": "/",
        "scope": "/",
        "icons": [
            {"sizes": "192x192", "src": "/static/icons/icon-192.png"},
            {"sizes": "512x512", "src": "/static/icons/icon-512.png"},
        ],
    }


def valid_shell():
    return (
        '<meta name="viewport" content="width=device-width, viewport-fit=cover">'
        '<link rel="manifest" href="/static/manifest.webmanifest">'
        '<div data-connectivity-banner></div>'
        '<script src="/static/connectivity.js"></script>'
    )


def test_normalize_base_url_requires_an_explicit_http_origin():
    assert normalize_base_url(" http://umbrel.local:8080/ ") == "http://umbrel.local:8080"
    assert normalize_base_url("https://example.test/apps/print/") == "https://example.test/apps/print"

    with pytest.raises(ValidationError):
        normalize_base_url("umbrel.local:8080")
    with pytest.raises(ValidationError):
        normalize_base_url("http://umbrel.local/?bad=1")
    with pytest.raises(ValidationError, match="embedded credentials"):
        normalize_base_url("http://user:secret@umbrel.local:18585")


def test_health_validator_checks_version_and_no_store_headers_case_insensitively():
    health = response(
        {"status": "ok", "version": "0.14.0-dev.1"},
        headers={"cache-control": "private, no-store", "PRAGMA": "no-cache"},
    )
    assert validate_health(health, "0.14.0-dev.1") == "0.14.0-dev.1"

    with pytest.raises(ValidationError, match="expected version"):
        validate_health(health, "0.15.0-dev.1")

    with pytest.raises(ValidationError, match="Cache-Control"):
        validate_health(
            response(
                {"status": "ok", "version": "0.14.0-dev.1"},
                headers={"Pragma": "no-cache"},
            ),
            "0.14.0-dev.1",
        )


def test_manifest_validator_requires_standalone_root_contract_and_icons():
    validate_manifest(response(valid_manifest()))

    with pytest.raises(ValidationError, match="192x192 and 512x512"):
        validate_manifest(
            response(
                {
                    "display": "standalone",
                    "start_url": "/",
                    "scope": "/",
                    "icons": [{"sizes": "192x192"}],
                }
            )
        )


def test_shell_validator_requires_pwa_and_connectivity_hooks():
    validate_shell(response(valid_shell()))

    with pytest.raises(ValidationError, match="connectivity.js"):
        validate_shell(
            response(
                '<meta name="viewport" content="viewport-fit=cover">'
                '<link rel="manifest" href="/static/manifest.webmanifest">'
                '<div data-connectivity-banner></div>'
            )
        )


def test_report_schema_uses_exact_candidate_and_aggregates_failures():
    report = build_report(
        base_url="http://umbrel.local:18585",
        expected_version="0.14.0-dev.1",
        generated_at="2026-09-02T00:00:00+00:00",
        results=[
            CheckResult("health_boundary", "Health/API boundary", "pass", detail="status=ok"),
            CheckResult("web_manifest", "Web app manifest", "fail", error="HTTP 500"),
        ],
    )

    assert report["schema"] == "3d-print-cost-v014-host-preflight-v1"
    assert report["generated_at"] == "2026-09-02T00:00:00+00:00"
    assert report["result"] == "fail"
    assert report["candidate"]["version"] == "0.14.0-dev.1"
    assert report["candidate"]["image"] == preflight.CANDIDATE_IMAGE
    assert report["candidate"]["image"].endswith(
        "@sha256:ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0"
    )
    assert report["checks"][1]["status"] == "fail"
    assert report["checks"][1]["error"] == "HTTP 500"


def test_write_report_persists_valid_utf8_json(tmp_path):
    report = build_report(
        base_url="http://umbrel.local:18585",
        expected_version="0.14.0-dev.1",
        generated_at="2026-09-02T00:00:00+00:00",
        results=[CheckResult("health_boundary", "Health/API boundary", "pass")],
    )
    path = write_report(tmp_path / "nested" / "preflight.json", report)

    assert path == (tmp_path / "nested" / "preflight.json").resolve()
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_run_writes_secret_free_success_report(tmp_path, monkeypatch):
    health = response(
        {"status": "ok", "version": "0.14.0-dev.1", "secret": "do-not-persist-body"},
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "Set-Cookie": "session=do-not-persist-cookie",
            "Authorization": "Bearer do-not-persist-header",
        },
    )
    shell = response(valid_shell() + "do-not-persist-html")

    def fake_fetch(base_url, path, timeout):
        assert base_url == "http://umbrel.local:18585"
        assert timeout == 1.0
        if path == "/healthz":
            return health
        if path == "/static/manifest.webmanifest":
            return response(valid_manifest())
        if path == "/":
            return shell
        return response("page")

    monkeypatch.setattr(preflight, "fetch", fake_fetch)
    report_path = tmp_path / "success.json"

    assert preflight.run(
        "http://umbrel.local:18585",
        "0.14.0-dev.1",
        1.0,
        json_out=report_path,
    ) == 0

    raw = report_path.read_text(encoding="utf-8")
    report = json.loads(raw)
    assert report["result"] == "pass"
    assert len(report["checks"]) == 8
    assert all(check["status"] == "pass" for check in report["checks"])
    assert "do-not-persist-body" not in raw
    assert "do-not-persist-cookie" not in raw
    assert "do-not-persist-header" not in raw
    assert "do-not-persist-html" not in raw


def test_run_writes_report_when_a_check_fails(tmp_path, monkeypatch):
    def fake_fetch(base_url, path, timeout):
        if path == "/healthz":
            return response(
                {"status": "ok", "version": "0.14.0-dev.1"},
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        if path == "/static/manifest.webmanifest":
            return response("broken", status=500)
        if path == "/":
            return response(valid_shell())
        return response("page")

    monkeypatch.setattr(preflight, "fetch", fake_fetch)
    report_path = tmp_path / "failure.json"

    assert preflight.run(
        "http://umbrel.local:18585",
        "0.14.0-dev.1",
        1.0,
        json_out=report_path,
    ) == 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["result"] == "fail"
    manifest = next(check for check in report["checks"] if check["check_id"] == "web_manifest")
    assert manifest["status"] == "fail"
    assert manifest["error"] == "manifest returned HTTP 500"
