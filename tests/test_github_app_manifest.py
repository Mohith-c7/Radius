"""Offline tests for scripts/github_app_manifest.py (no network, no secrets in the repo)."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import urllib.error
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "github_app_manifest.py"
_spec = importlib.util.spec_from_file_location("github_app_manifest", _SCRIPT)
gam = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gam
_spec.loader.exec_module(gam)

TEMPLATE = json.loads(gam.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
HOOK = "https://abc.trycloudflare.com/api/v1/webhooks/github"


def _manifest(**kw):
    return gam.build_manifest(
        TEMPLATE, webhook_url=HOOK, redirect_url="http://localhost:3456/callback", name="App", **kw
    )


def test_checked_in_manifest_matches_what_the_code_uses() -> None:
    perms = TEMPLATE["default_permissions"]
    assert perms["checks"] == "write"
    assert perms["pull_requests"] == "write"
    assert perms["contents"] == "read"
    assert perms["metadata"] == "read"
    assert {"pull_request", "push"} <= set(TEMPLATE["default_events"])
    assert "__WEBHOOK_URL__" in json.dumps(TEMPLATE)


def test_build_manifest_fills_placeholders() -> None:
    manifest = _manifest()
    assert manifest["hook_attributes"]["url"] == HOOK
    assert manifest["redirect_url"] == "http://localhost:3456/callback"
    assert manifest["name"] == "App"
    assert "__" not in json.dumps(manifest)


def test_minimal_drops_events_and_permissions_the_code_ignores() -> None:
    manifest = _manifest(minimal=True)
    assert manifest["default_events"] == ["pull_request", "push"]
    assert "issues" not in manifest["default_permissions"]
    assert manifest["default_permissions"]["checks"] == "write"


def test_plain_http_webhook_is_rejected() -> None:
    with pytest.raises(gam.ManifestError):
        gam.build_manifest(
            TEMPLATE, webhook_url="http://x/y", redirect_url="http://localhost/cb", name="A"
        )


def test_out_inside_repo_is_refused(tmp_path: Path) -> None:
    with pytest.raises(gam.ManifestError):
        gam.assert_outside_repo(gam.REPO_ROOT / "docs" / "secrets")
    with pytest.raises(gam.ManifestError):
        gam.assert_outside_repo(gam.REPO_ROOT)
    assert gam.assert_outside_repo(tmp_path / "x") == (tmp_path / "x").resolve()


CONVERSION = {
    "id": 424242,
    "slug": "radius-sandbox",
    "webhook_secret": "whsec-test-not-real",
    "pem": "-----BEGIN RSA PRIVATE KEY-----\nAAA\nBBB\n-----END RSA PRIVATE KEY-----\n",
    "client_secret": "must-not-be-written",
}


def test_format_env_single_line_pem_and_no_client_secret() -> None:
    text = gam.format_env(CONVERSION)
    assert "GITHUB_APP_ID=424242\n" in text
    assert "GITHUB_WEBHOOK_SECRET=whsec-test-not-real\n" in text
    assert "GITHUB_APP_PRIVATE_KEY='-----BEGIN RSA PRIVATE KEY-----\\nAAA\\nBBB\\n-----END RSA PRIVATE KEY-----'\n" in text
    assert "must-not-be-written" not in text
    assert "GITHUB_SINGLE_TENANT=true" in text


def test_format_env_requires_fields() -> None:
    with pytest.raises(gam.ManifestError):
        gam.format_env({"id": 1})


def test_write_outputs_is_private_and_never_overwrites(tmp_path: Path) -> None:
    paths = gam.write_outputs(tmp_path / "creds", CONVERSION)
    assert paths["env"].read_text().startswith("GITHUB_APP_ID=424242")
    assert paths["pem"].read_text().startswith("-----BEGIN RSA PRIVATE KEY-----")
    if os.name != "nt":
        assert stat.S_IMODE(paths["env"].stat().st_mode) == 0o600
        assert stat.S_IMODE(paths["pem"].stat().st_mode) == 0o600
    with pytest.raises(gam.ManifestError):
        gam.write_outputs(tmp_path / "creds", CONVERSION)


def test_exchange_code_posts_to_conversion_endpoint() -> None:
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(CONVERSION).encode()

    def opener(request, timeout):
        seen["url"], seen["method"] = request.full_url, request.get_method()
        return Resp()

    assert gam.exchange_code("abc123", opener=opener)["id"] == 424242
    assert seen == {
        "url": "https://api.github.com/app-manifests/abc123/conversions",
        "method": "POST",
    }


def test_exchange_code_rejects_bad_code_and_maps_http_errors() -> None:
    with pytest.raises(gam.ManifestError):
        gam.exchange_code("../x")

    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)

    with pytest.raises(gam.ManifestError, match="404"):
        gam.exchange_code("abc", opener=opener)


def test_state_check_and_form_html_escapes_manifest() -> None:
    assert gam.check_state("s", "s")
    assert not gam.check_state("s", "t")
    assert not gam.check_state("s", None)
    page = gam.start_form_html({"name": 'A"><script>'}, gam.post_url_for("my org"), "st")
    assert "<script>" not in page
    assert "organizations/my%20org/settings/apps/new?state=st" in page


def test_print_manifest_cli_is_offline(tmp_path: Path, capsys) -> None:
    code = gam.main(["--webhook-url", HOOK, "--out", str(tmp_path / "o"), "--print-manifest"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["hook_attributes"]["url"] == HOOK
    assert gam.main(["--webhook-url", HOOK, "--out", str(gam.REPO_ROOT / "x")]) == 2
