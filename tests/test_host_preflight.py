import json

import pytest

from tools.validate_v014_host import (
    Response,
    ValidationError,
    normalize_base_url,
    validate_health,
    validate_manifest,
    validate_shell,
)


def response(body, *, status=200, headers=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    return Response(status=status, headers=headers or {}, body=body)


def test_normalize_base_url_requires_an_explicit_http_origin():
    assert normalize_base_url(" http://umbrel.local:8080/ ") == "http://umbrel.local:8080"
    assert normalize_base_url("https://example.test/apps/print/") == "https://example.test/apps/print"

    with pytest.raises(ValidationError):
        normalize_base_url("umbrel.local:8080")
    with pytest.raises(ValidationError):
        normalize_base_url("http://umbrel.local/?bad=1")


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
    validate_manifest(
        response(
            {
                "display": "standalone",
                "start_url": "/",
                "scope": "/",
                "icons": [
                    {"sizes": "192x192", "src": "/static/icons/icon-192.png"},
                    {"sizes": "512x512", "src": "/static/icons/icon-512.png"},
                ],
            }
        )
    )

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
    validate_shell(
        response(
            '<meta name="viewport" content="width=device-width, viewport-fit=cover">'
            '<link rel="manifest" href="/static/manifest.webmanifest">'
            '<div data-connectivity-banner></div>'
            '<script src="/static/connectivity.js"></script>'
        )
    )

    with pytest.raises(ValidationError, match="connectivity.js"):
        validate_shell(
            response(
                '<meta name="viewport" content="viewport-fit=cover">'
                '<link rel="manifest" href="/static/manifest.webmanifest">'
                '<div data-connectivity-banner></div>'
            )
        )
