"""Create the Radius sandbox GitHub App through GitHub's manifest flow (F-06).

Stdlib only. Serves a page on 127.0.0.1 that POSTs ``docs/github-app-validation/
app-manifest.json`` (placeholders filled in) to GitHub, receives the redirect
``?code=...``, exchanges it for the App id, webhook secret and private key, and
writes them to files OUTSIDE the repository. Secrets are never printed and never
placed inside the repo (this script refuses an ``--out`` inside the checkout).

Usage
    python scripts/github_app_manifest.py --webhook-url https://x.trycloudflare.com/api/v1/webhooks/github \
        --out ~/radius-github-app
    python scripts/github_app_manifest.py --webhook-url ... --out ... --print-manifest   # no server, no network

The only network call is the one-time ``POST /app-manifests/{code}/conversions``
to api.github.com, made after you approve the App in your browser.
"""

from __future__ import annotations

import argparse
import hmac
import html
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "github-app-validation" / "app-manifest.json"
DEFAULT_PORT = 3456
GITHUB_WEB = "https://github.com"
GITHUB_API = "https://api.github.com"
# Present only in the full F-06 list; the code only acts on pull_request and push.
OPTIONAL_EVENTS = ("issues", "issue_comment", "check_run")
OPTIONAL_PERMISSIONS = ("issues",)


class ManifestError(Exception):
    """Raised for invalid input; message is safe to print."""


def build_manifest(
    template: dict,
    *,
    webhook_url: str,
    redirect_url: str,
    name: str,
    minimal: bool = False,
) -> dict:
    """Fill the template placeholders. ``minimal`` drops events/permissions the code ignores."""

    if not webhook_url.startswith("https://"):
        raise ManifestError("--webhook-url must be an https:// URL (GitHub will not call plain http).")
    text = json.dumps(template)
    for placeholder, value in (
        ("__WEBHOOK_URL__", webhook_url),
        ("__REDIRECT_URL__", redirect_url),
        ("__APP_NAME__", name),
    ):
        text = text.replace(placeholder, json.dumps(value)[1:-1])
    manifest = json.loads(text)
    if minimal:
        manifest["default_events"] = [e for e in manifest["default_events"] if e not in OPTIONAL_EVENTS]
        for permission in OPTIONAL_PERMISSIONS:
            manifest["default_permissions"].pop(permission, None)
    return manifest


def assert_outside_repo(out: Path, repo_root: Path = REPO_ROOT) -> Path:
    """Resolve ``out`` and refuse any location inside the repository checkout."""

    resolved = out.expanduser().resolve()
    root = repo_root.resolve()
    if resolved == root or root in resolved.parents:
        raise ManifestError(f"--out must be outside the repository ({root}); got {resolved}.")
    return resolved


def format_env(conversion: dict) -> str:
    """Render the env lines Radius needs. The PEM is one line with literal ``\\n`` (client expands it)."""

    for key in ("id", "pem", "webhook_secret"):
        if not conversion.get(key):
            raise ManifestError(f"GitHub conversion response is missing '{key}'.")
    pem = str(conversion["pem"]).strip().replace("\r\n", "\n").replace("\n", "\\n")
    return (
        f"GITHUB_APP_ID={conversion['id']}\n"
        f"GITHUB_WEBHOOK_SECRET={conversion['webhook_secret']}\n"
        f"GITHUB_APP_PRIVATE_KEY='{pem}'\n"
        "GITHUB_PUBLISH_RESULTS=true\n"
        "GITHUB_SINGLE_TENANT=true\n"
    )


def _write_private(path: Path, content: str) -> None:
    """Create ``path`` exclusively with owner-only permissions (0600 where the OS honours it)."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platform specific
        pass


def write_outputs(out_dir: Path, conversion: dict) -> dict[str, Path]:
    """Write ``radius-github.env`` and ``app.pem`` into ``out_dir``; never overwrites."""

    env_text = format_env(conversion)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:  # pragma: no cover - platform specific
        pass
    env_path, pem_path = out_dir / "radius-github.env", out_dir / "app.pem"
    for path in (env_path, pem_path):
        if path.exists():
            raise ManifestError(f"{path} already exists; move it away first (refusing to overwrite secrets).")
    _write_private(env_path, env_text)
    _write_private(pem_path, str(conversion["pem"]).strip() + "\n")
    return {"env": env_path, "pem": pem_path}


def exchange_code(code: str, *, opener=urllib.request.urlopen, api_base: str = GITHUB_API) -> dict:
    """Exchange the one-time manifest ``code`` (valid 1 hour) for the App credentials."""

    if not code or not all(c.isalnum() or c in "-_" for c in code):
        raise ManifestError("Invalid manifest code in the redirect.")
    request = urllib.request.Request(
        f"{api_base}/app-manifests/{urllib.parse.quote(code)}/conversions",
        data=b"",
        method="POST",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "radius-f06-manifest"},
    )
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ManifestError(f"GitHub rejected the code (HTTP {exc.code}); restart the flow.") from exc
    except urllib.error.URLError as exc:
        raise ManifestError(f"Could not reach GitHub: {exc.reason}") from exc


def start_form_html(manifest: dict, post_url: str, state: str) -> str:
    """Page whose button POSTs the manifest to GitHub (GitHub requires a form POST)."""

    action = f"{post_url}?state={urllib.parse.quote(state)}"
    return (
        "<!doctype html><meta charset=utf-8><title>Create Radius GitHub App</title>"
        "<h1>Create the Radius sandbox GitHub App</h1>"
        "<p>Review the permissions below, then continue to GitHub.</p>"
        f"<pre>{html.escape(json.dumps(manifest, indent=2))}</pre>"
        f'<form method="post" action="{html.escape(action, quote=True)}">'
        f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(manifest), quote=True)}">'
        "<button type=submit>Create GitHub App on GitHub</button></form>"
    )


def post_url_for(org: str | None) -> str:
    if org:
        return f"{GITHUB_WEB}/organizations/{urllib.parse.quote(org)}/settings/apps/new"
    return f"{GITHUB_WEB}/settings/apps/new"


def check_state(expected: str, received: str | None) -> bool:
    return received is not None and hmac.compare_digest(expected, received)


def _next_steps(slug: str | None, paths: dict[str, Path]) -> str:
    install = f"{GITHUB_WEB}/apps/{slug}/installations/new" if slug else f"{GITHUB_WEB}/settings/apps"
    return (
        "App created. Credentials were written (not shown):\n"
        f"  env file : {paths['env']}   -> copy these lines into the repo's local .env (gitignored)\n"
        f"  PEM      : {paths['pem']}   -> keep outside the repo\n"
        f"Next: install the App on the sandbox repo: {install}\n"
        "Then follow docs/github-app-validation/RUNBOOK.md section 4."
    )


def make_handler(manifest: dict, state: str, out_dir: Path, org: str | None, done: threading.Event, result: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # keep codes/secrets out of logs
            return

        def _send(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/":
                self._send(200, start_form_html(manifest, post_url_for(org), state))
            elif parsed.path == "/callback":
                if not check_state(state, (query.get("state") or [None])[0]):
                    self._send(400, "State mismatch; restart the helper.")
                    return
                try:
                    conversion = exchange_code((query.get("code") or [""])[0])
                    paths = write_outputs(out_dir, conversion)
                except ManifestError as exc:
                    result["error"] = str(exc)
                    self._send(500, html.escape(str(exc)))
                    done.set()
                    return
                result["message"] = _next_steps(conversion.get("slug"), paths)
                self._send(200, f"<pre>{html.escape(result['message'])}</pre>You can close this tab.")
                done.set()
            else:
                self._send(404, "not found")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--webhook-url", required=True, help="Public https URL GitHub should POST to.")
    parser.add_argument("--out", required=True, type=Path, help="Directory OUTSIDE the repo for credentials.")
    parser.add_argument("--name", default="Radius Sandbox (F-06)", help="App name (must be globally unique).")
    parser.add_argument("--org", help="Create under this organization instead of your user account.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--minimal", action="store_true", help="Only pull_request/push events, no issues:read.")
    parser.add_argument("--print-manifest", action="store_true", help="Print the manifest and exit (offline).")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        out_dir = assert_outside_repo(args.out)
        template = json.loads(args.manifest.read_text(encoding="utf-8"))
        manifest = build_manifest(
            template,
            webhook_url=args.webhook_url,
            redirect_url=f"http://localhost:{args.port}/callback",
            name=args.name,
            minimal=args.minimal,
        )
    except (ManifestError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.print_manifest:
        print(json.dumps(manifest, indent=2))
        return 0
    state, done, result = secrets.token_urlsafe(24), threading.Event(), {}
    server = HTTPServer(("127.0.0.1", args.port), make_handler(manifest, state, out_dir, args.org, done, result))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://localhost:{args.port}/"
    print(f"Open {url} in your browser and click the button (waiting up to 15 minutes)...")
    if not args.no_browser:
        webbrowser.open(url)
    done.wait(timeout=900)
    server.shutdown()
    if "error" in result or "message" not in result:
        print(f"error: {result.get('error', 'timed out waiting for the GitHub redirect')}", file=sys.stderr)
        return 1
    print(result["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
