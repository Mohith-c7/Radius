#!/usr/bin/env python3
"""Generate ``docs/operations/CONFIGURATION.md`` from the code (PRD-17).

Sources, in order of authority:

1. The pydantic settings classes (``ApiSettings``, ``WorkerSettings``,
   ``GitHubAppSettings``, ``ObservabilitySettings`` and the auth-module
   ``Settings``): env name, type, default and description are read from the
   class definitions, never retyped here.
2. Environment variables that are read outside pydantic (LLM extraction and
   re-ranking, the legacy Gemini pruner, the dashboard, Docker/Compose). Their
   names live in ``EXTRA`` below; defaults of the LLM extraction knobs are read
   from the config dataclasses. Every ``EXTRA`` entry names the file that reads
   it and the generator fails if that file no longer mentions the variable.
3. A scan of the Python sources for ``RADIUS_*`` / ``WORKER_*`` style string
   literals. Anything found there that is neither pydantic-backed nor in
   ``EXTRA`` is listed as ``undocumented`` and makes ``--check`` fail.

Usage::

    python scripts/gen_config_reference.py            # rewrite the file
    python scripts/gen_config_reference.py --check    # exit 1 if it drifted

``tests/test_config_reference.py`` runs the ``--check`` logic in CI.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "operations" / "CONFIGURATION.md"

for _src in (
    "apps/api",
    "apps/api/src",
    "apps/worker/src",
    "packages/shared/src",
    "packages/github/src",
    "packages/analysis/src",
    "packages/intent/src",
    "packages/linking/src",
    "packages/testing/src",
    "packages/evidence/src",
):
    _p = str(ROOT / _src)
    if _p not in sys.path:
        sys.path.insert(0, _p)

SECRET_RE = re.compile(r"(SECRET|PASSWORD|PRIVATE_KEY|API_KEY)")
#: Credentials embedded in the value although the name does not say so.
EXTRA_SECRET = {"DATABASE_URL"}
#: Names that look like env vars in the source but are not.
NOT_ENV = {"RADIUS_ERROR", "RADIUS_DATA_", "GITHUB_RATE_LIMITED"}  # last: an error code, not a variable
#: Variables set by tooling or CI rather than read by the application.
SCAN_PATTERN = re.compile(r"""["']((?:RADIUS|WORKER|GITHUB|REPOSITORY|STORAGE)_[A-Z0-9_]*[A-Z0-9])["']""")
STATUS_OVERRIDE = {
    "RADIUS_FEATURE_VERDICT_V2": "alpha flag: off, shadow or on",
    "RADIUS_FEATURE_INTENT_INGESTION": "feature flag, off until live validation",
    "RADIUS_FEATURE_GEMINI_PRUNER": "legacy opt-in, not on the live path",
    "WORKER_TEST_EXECUTION_MODE": "safety switch: disabled, sandbox or unsafe_in_process",
    "WORKER_EXECUTE_TESTS": "deprecated (use WORKER_TEST_EXECUTION_MODE)",
}


#: Descriptions for variables whose settings field has none in the code. Each
#: line was checked against the code that reads the setting. Prefer adding a
#: ``description=`` to the field; the code text always wins over this table.
DESCRIPTIONS = {
    "API_BASE_URL": "Auth module: public API base URL. Declared in the auth settings; no other code reads it (verified by grep).",
    "API_KEYS": "Comma-separated `org_id:key` pairs accepted in `X-Radius-API-Key` / Bearer auth. With none configured the API rejects requests unless `RADIUS_ALLOW_INSECURE_DEV` applies (development/test only).",
    "DASHBOARD_BASE_URL": "Canonical public dashboard URL; the worker uses it to build the analysis link in the check run and PR comment.",
    "DATABASE_URL": "PostgreSQL URL for the API, worker and migrations. `postgres://` and `postgresql://` are normalised to `postgresql+psycopg://`. The auth module (sign-in tables) reads the same variable, but its own default is `sqlite:///./radius.db`, so when the variable is unset the auth tables go to a local SQLite file while the main settings default to the local PostgreSQL URL. Always set it explicitly.",
    "EMAIL_DELIVERY_MODE": "Auth module: `smtp` (default) sends mail over SMTP when `SMTP_USERNAME` and `SMTP_PASSWORD` are set; `log` writes the message, including the verification or reset link, to the API log instead (local development only, refused when `RADIUS_ENV=production`). Any other value is rejected at start-up.",
    "FRONTEND_ORIGIN": "Auth module: dashboard origin used in e-mail verification/reset links, OAuth redirects and the auth CORS allow-list.",
    "GITHUB_API_BASE_URL": "GitHub REST base URL (change for GitHub Enterprise Server).",
    "GITHUB_API_VERSION": "Value of the `X-GitHub-Api-Version` header sent to GitHub.",
    "GITHUB_APP_ID": "GitHub App id. The worker publishes results only when both this and the private key are set.",
    "GITHUB_APP_PRIVATE_KEY": "GitHub App private key (PEM). Newlines may be written as `\n`.",
    "GITHUB_CLIENT_ID": "Auth module: GitHub OAuth sign-in client id (optional).",
    "GITHUB_CLIENT_SECRET": "Auth module: GitHub OAuth sign-in client secret (optional).",
    "GITHUB_DEFAULT_ORGANIZATION_ID": "Organization UUID used for webhook-created analyses when `GITHUB_SINGLE_TENANT` is true.",
    "GITHUB_INSTALLATION_ID": "Fixed GitHub App installation id for the worker. When unset (empty or 0) the worker uses the organization's stored `github_installation_id` and fails the publish if neither exists.",
    "GITHUB_PUBLISH_RESULTS": "Worker: publish check runs and PR comments to GitHub. Also requires GitHub App credentials.",
    "GITHUB_REDIRECT_URI": "Auth module: GitHub OAuth redirect URI (optional).",
    "GITHUB_TIMEOUT_SECONDS": "Timeout in seconds for GitHub REST calls.",
    "GITHUB_WEBHOOK_SECRET": "HMAC secret that signs GitHub webhooks. Unsigned webhooks are rejected unless `RADIUS_ALLOW_INSECURE_DEV` applies.",
    "GOOGLE_CLIENT_ID": "Auth module: Google OAuth sign-in client id (optional).",
    "GOOGLE_CLIENT_SECRET": "Auth module: Google OAuth sign-in client secret (optional).",
    "GOOGLE_REDIRECT_URI": "Auth module: Google OAuth redirect URI (optional).",
    "RADIUS_CORS_ALLOW_CREDENTIALS": "Send `Access-Control-Allow-Credentials`. Never combined with `*`.",
    "RADIUS_ENV": "Runtime environment: `development`, `test`, `uat` or `production`. Production tightens CORS validation (https origins only, no wildcard, no automatic localhost), ignores demo seeding, refuses the public session secret and `EMAIL_DELIVERY_MODE=log`. `docker-compose.yml` pins `production`; `docker-compose.dev.yml` (used by `make dev`) sets `development` for the api.",
    "RADIUS_HSTS_MAX_AGE": "`max-age` in seconds of the Strict-Transport-Security header when HSTS is enabled.",
    "RADIUS_LOG_LEVEL": "Structured log level: DEBUG, INFO, WARNING, ERROR or CRITICAL.",
    "RADIUS_MAX_BODY_BYTES": "Default request body cap in bytes; over it the API answers 413.",
    "RADIUS_METRICS_ENABLED": "Expose Prometheus metrics (`/metrics` on the API, plus the worker port). Off by default.",
    "RADIUS_OTEL_SERVICE_NAME": "OpenTelemetry service name.",
    "RADIUS_RATE_LIMIT_AUTH": "Token bucket for auth routes, `<requests>/<window seconds>`. In memory, per replica.",
    "RADIUS_RATE_LIMIT_ENABLED": "Master switch for the API rate limiter.",
    "RADIUS_RATE_LIMIT_EXPENSIVE": "Token bucket for expensive routes, `<requests>/<window seconds>`.",
    "RADIUS_RATE_LIMIT_GENERAL": "Token bucket for general routes, `<requests>/<window seconds>`.",
    "RADIUS_RATE_LIMIT_WEBHOOK": "Token bucket for the GitHub webhook route, `<requests>/<window seconds>`.",
    "RADIUS_TRACING_ENABLED": "Create OpenTelemetry spans (needs the `observability` extra). Off by default.",
    "RADIUS_UPLOAD_MAX_BODY_BYTES": "Body cap in bytes for CI test-report uploads.",
    "RADIUS_WEBHOOK_MAX_BODY_BYTES": "Body cap in bytes for GitHub webhook deliveries.",
    "REPOSITORY_CACHE_DIR": "Worker: directory for cloned repositories (a volume in Compose: `/var/lib/radius/repositories`).",
    "SERVICE_NAME": "Service name used in logs. Defaults differ per service (`radius-api`, `radius-worker`); normally left alone.",
    "SESSION_COOKIE_SECURE": "Auth module: set the Secure flag on the session cookie. Set true behind TLS.",
    "SESSION_SECRET": "Auth module: secret used to sign sessions (minimum 32 characters). The default in code and the `.env.example` placeholder are public; with `RADIUS_ENV=production` the API refuses to start with either. `docker-compose.yml` has no default and stops if it is unset; `make env` generates a random one for local dev.",
    "SMTP_FROM_EMAIL": "Auth module: From address of verification and reset e-mails.",
    "SMTP_HOST": "Auth module: SMTP server.",
    "SMTP_PASSWORD": "Auth module: SMTP password.",
    "SMTP_PORT": "Auth module: SMTP port (STARTTLS).",
    "SMTP_USERNAME": "Auth module: SMTP user. E-mail is sent only when user and password are both set.",
    "STORAGE_BACKEND": "API storage: `memory` (default; data is lost on restart) or `sql` (PostgreSQL). Compose sets `sql`.",
    "WORKER_JOB_MAX_ATTEMPTS": "Attempts before a job is marked failed.",
    "WORKER_JOB_STALE_AFTER_SECONDS": "A job in `running` longer than this is returned to `pending` (or marked `failed` when its attempts are exhausted) by stale-job recovery.",
    "WORKER_POLL_INTERVAL_SECONDS": "Seconds between queue polls when idle.",
    "WORKER_REAPER_INTERVAL_SECONDS": "How often the reaper looks for analyses past the deadline.",
    "WORKER_SANDBOX_CPUS": "CPU limit of each sandbox container (`--cpus`).",
    "WORKER_SANDBOX_MAX_FILE_SIZE_BYTES": "Maximum size of a file written inside the sandbox (ulimit).",
    "WORKER_SANDBOX_MEMORY": "Memory limit of each sandbox container.",
    "WORKER_SANDBOX_NOFILE_LIMIT": "Open file descriptor limit inside the sandbox.",
    "WORKER_SANDBOX_PIDS_LIMIT": "Process limit inside the sandbox.",
    "WORKER_SANDBOX_RUNTIME": "Container runtime CLI used for sandbox mode (default `docker`).",
    "WORKER_SANDBOX_TMPFS_SIZE": "Size of the writable tmpfs in the sandbox.",
    "WORKER_TEST_TIMEOUT_SECONDS": "Timeout per test command; with reruns the worst case is `(1 + WORKER_TEST_RERUNS)` times this.",
}


@dataclass
class Entry:
    name: str
    type: str = ""
    default: str = ""
    description: str = ""
    services: set[str] = field(default_factory=set)
    source: str = ""
    status: str = ""

    @property
    def secret(self) -> bool:
        return bool(SECRET_RE.search(self.name)) or self.name in EXTRA_SECRET


# --------------------------------------------------------------------------- pydantic


def _attribute_docstrings(cls: type) -> dict[str, str]:
    """Map field name -> the string literal that follows its annotation, if any."""

    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    except (OSError, TypeError):
        return {}
    class_def = tree.body[0]
    result: dict[str, str] = {}
    body = class_def.body  # type: ignore[attr-defined]
    for current, following in zip(body, body[1:], strict=False):
        if (
            isinstance(current, ast.AnnAssign)
            and isinstance(current.target, ast.Name)
            and isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ):
            result[current.target.id] = " ".join(following.value.value.split())
    return result


def _type_name(annotation: Any) -> str:
    text = getattr(annotation, "__name__", None)
    if text and not getattr(annotation, "__args__", None):
        return text
    return str(annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")


def _default_text(value: Any) -> str:
    if hasattr(value, "value") and type(value).__module__ != "builtins" and hasattr(type(value), "__members__"):
        return str(value.value)
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return value.as_posix()
    if value == "":
        return "empty"
    return str(value)


def pydantic_entries() -> dict[str, Entry]:
    from app.config import Settings as AuthSettings
    from radius_api.config import ApiSettings
    from radius_github.client import GitHubAppSettings
    from radius_shared.observability.settings import ObservabilitySettings
    from radius_worker.config import WorkerSettings
    from pydantic_core import PydanticUndefined

    classes: list[tuple[type, str, str]] = [
        (ApiSettings, "api", "apps/api/src/radius_api/config.py"),
        (WorkerSettings, "worker", "apps/worker/src/radius_worker/config.py"),
        (GitHubAppSettings, "api, worker", "packages/github/src/radius_github/client.py"),
        (ObservabilitySettings, "api, worker", "packages/shared/src/radius_shared/observability/settings.py"),
        (AuthSettings, "api", "apps/api/src/app/config.py"),
    ]
    entries: dict[str, Entry] = {}
    for cls, services, source in classes:
        docstrings: dict[str, str] = {}
        for klass in reversed(cls.__mro__):
            if isinstance(klass, type) and klass.__module__.split(".")[0] in {
                "radius_api",
                "radius_worker",
                "radius_github",
                "radius_shared",
                "app",
            }:
                docstrings.update(_attribute_docstrings(klass))
        for fname, info in cls.model_fields.items():
            env = info.alias or fname.upper()
            default = info.default
            if default is PydanticUndefined:
                default_text = "required"
            else:
                default_text = _default_text(default)
            description = info.description or docstrings.get(fname, "")
            entry = entries.get(env)
            if entry is None:
                entry = Entry(env, _type_name(info.annotation), default_text, " ".join(description.split()))
                entries[env] = entry
            # Same variable declared by several classes: keep the first description.
            if not entry.description and description:
                entry.description = " ".join(description.split())
            for service in services.split(", "):
                entry.services.add(service)
            entry.source = entry.source or source
    return entries


# --------------------------------------------------------------------------- extras


def _llm_entries() -> list[Entry]:
    from radius_intent.infrastructure.llm.config import LlmExtractionConfig
    from radius_linking.infrastructure.rerank.llm import LlmRerankConfig

    d = LlmExtractionConfig()
    r = LlmRerankConfig()
    src_i = "packages/intent/src/radius_intent/infrastructure/llm/config.py"
    src_r = "packages/linking/src/radius_linking/infrastructure/rerank/llm.py"
    rows = [
        ("RADIUS_LLM_INTENT_ENABLED", "bool", d.enabled, "IN-04: master switch for LLM-assisted criterion extraction. The LLM only proposes criteria, never a verdict (DEC-009)."),
        ("RADIUS_LLM_INTENT_ORGS", "csv", ",".join(sorted(d.orgs)), "Organization ids allowed to use it (`*` = all). Egress also needs the flag above (DEC-015)."),
        ("RADIUS_LLM_INTENT_MODEL", "str", d.model, "Model id for the Anthropic adapter."),
        ("RADIUS_LLM_INTENT_MAX_OUTPUT_TOKENS", "int", d.max_output_tokens, "Output token cap per call."),
        ("RADIUS_LLM_INTENT_TIMEOUT_S", "float", d.timeout_s, "Per-call timeout in seconds."),
        ("RADIUS_LLM_INTENT_SEED", "int", d.seed, "Sampling seed passed to the provider."),
        ("RADIUS_LLM_INTENT_MAX_ATTEMPTS", "int", d.max_attempts, "Bounded retries per call."),
        ("RADIUS_LLM_INTENT_BREAKER_THRESHOLD", "int", d.breaker_threshold, "Consecutive failures that open the circuit breaker."),
        ("RADIUS_LLM_INTENT_BREAKER_COOLDOWN_S", "float", d.breaker_cooldown_s, "Seconds the breaker stays open."),
        ("RADIUS_LLM_INTENT_ANALYSIS_TOKEN_CAP", "int", d.analysis_token_cap, "Token cap per analysis; calls that would exceed it are skipped."),
        ("RADIUS_LLM_INTENT_ORG_TOKEN_CAP", "int", d.org_token_cap, "Token cap per organization, kept in memory (process lifetime)."),
        ("RADIUS_LLM_INTENT_MAX_CRITERIA", "int", d.max_criteria, "Cap on criteria the LLM may propose."),
    ]
    out = []
    for name, typ, default, desc in rows:
        out.append(Entry(name, typ, _default_text(default), desc, {"api"}, src_i, "opt-in, off by default" if name.endswith("_ENABLED") else ""))
    rrows = [
        ("RADIUS_LLM_LINK_RERANK_ENABLED", "bool", r.enabled, "LK-02: optional LLM re-ranker of criterion-to-symbol candidates. Sends criterion text, symbol names and file paths (no source code). Library only: not called by the API or worker today."),
        ("RADIUS_LLM_LINK_RERANK_ORGS", "csv", ",".join(sorted(r.orgs)), "Organization ids allowed to use the re-ranker (`*` = all)."),
        ("RADIUS_LLM_LINK_RERANK_MODEL", "str", r.model, "Model id for the re-ranker."),
    ]
    for name, typ, default, desc in rrows:
        out.append(Entry(name, typ, _default_text(default), desc, {"library"}, src_r, "opt-in, off by default" if name.endswith("_ENABLED") else ""))
    return out


def extra_entries() -> list[Entry]:
    e = Entry
    items = [
        e("ANTHROPIC_API_KEY", "str", "unset", "Credential for the Anthropic adapter, read only when LLM intent extraction is enabled for the org. Missing key or missing `anthropic` package: the API logs a warning and skips the LLM extractor.", {"api"}, "packages/intent/src/radius_intent/infrastructure/llm/anthropic_provider.py"),
        e("GEMINI_API_KEY", "str", "unset", "Legacy Gemini SemanticPruner. Used only when RADIUS_FEATURE_GEMINI_PRUNER is also true. Sends caller source and diffs to Google; not covered by the DEC-021 egress policy. Leave unset.", {"none (legacy)"}, "packages/analysis/src/radius_analysis/ai/pruner.py"),
        e("RADIUS_FEATURE_GEMINI_PRUNER", "bool", "false", "Explicit opt-in for the legacy Gemini SemanticPruner. The pruner is not called by the live analysis pipeline (only by `scripts/run_phase2_poc.py` and tests).", {"none (legacy)"}, "packages/analysis/src/radius_analysis/ai/pruner.py", "legacy opt-in, not on the live path"),
        e("RADIUS_FEATURE_ASSERTION_EXTRACTION", "bool", "false", "LK-04 library entry point also reads this flag from the process environment (the worker reads it through its settings, see above).", {"worker"}, "packages/testing/src/radius_testing/assertions/service.py"),
        e("RADIUS_FEATURE_MUTATION", "bool", "false", "EV-04/05 mutation-evidence prototype library flag (`radius_testing.mutation`). Library only: nothing in the worker calls it yet.", {"library"}, "packages/testing/src/radius_testing/mutation/__init__.py"),
        e("RADIUS_MUTATION_ALLOW_LOCAL", "bool", "unset", "Dev/tests only: allows the mutation prototype's local subprocess runner, which executes code on the host and is unsafe for untrusted repositories. Never set in production.", {"library"}, "packages/testing/src/radius_testing/mutation/runner.py"),
        e("RADIUS_FEATURE_COVERAGE_CONTEXTS", "bool", "false", "LK-03 library entry point reads this flag directly from the process environment.", {"worker"}, "packages/testing/src/radius_testing/linking/dynamic.py"),
        e("RADIUS_EVAL_ALLOW_REAL_LLM", "str", "unset", "Intent evaluation CLI only: must be `1`, together with `--allow-real-llm`, before a real provider is used. Tests and CI never set it.", {"evaluation CLI"}, "packages/intent/src/radius_intent/evaluation/extractors.py"),
        e("DEV_AUTO_VERIFY_EMAIL", "str", "unset", "Auth module: when set, `true/1/yes` auto-verifies new accounts without e-mail and any other value disables it, in any environment. Development convenience; leave unset in production.", {"api"}, "apps/api/src/app/auth.py"),
        e("DEV_AUTO_VERIFY", "bool", "true", "Auth module: when `RADIUS_ENV=development` (and DEV_AUTO_VERIFY_EMAIL is unset), accounts are verified without e-mail unless this is `false`. In any other environment accounts are not auto-verified.", {"api"}, "apps/api/src/app/auth.py"),
        e("RADIUS_API_KEY", "str", "empty", "Server-only secret the dashboard proxy (`/api/radius/*`) sends as `X-Radius-API-Key`. Must never carry a `NEXT_PUBLIC_` prefix.", {"dashboard"}, "apps/dashboard/lib/proxy.ts"),
        e("RADIUS_API_BASE_URL", "str", "http://api:8000 (compose)", "Server-side API origin used by the dashboard proxy. Falls back to NEXT_PUBLIC_RADIUS_API_BASE_URL.", {"dashboard"}, "apps/dashboard/lib/proxy.ts"),
        e("RADIUS_ORGANIZATION_ID", "str", "empty", "Server-side organization id for the dashboard proxy. Falls back to NEXT_PUBLIC_RADIUS_ORGANIZATION_ID.", {"dashboard"}, "apps/dashboard/lib/proxy.ts"),
        e("NEXT_PUBLIC_RADIUS_API_BASE_URL", "str", "http://localhost:8000", "API origin as seen by the browser; also used for the dashboard CSP `connect-src`. Inlined at build time.", {"dashboard"}, "apps/dashboard/lib/api.ts"),
        e("NEXT_PUBLIC_RADIUS_ORGANIZATION_ID", "str", "empty", "Organization UUID the dashboard loads. The dashboard asks you to set it when empty. Inlined at build time.", {"dashboard"}, "apps/dashboard/lib/api.ts"),
        e("NEXT_PUBLIC_API_URL", "str", "http://localhost:8000/api/v1", "Base URL used by the dashboard sign-in/auth client.", {"dashboard"}, "apps/dashboard/lib/auth.ts"),
        e("NEXT_PUBLIC_GITHUB_APP_URL", "str", "unset", "Link target for the GitHub App install button in the dashboard.", {"dashboard"}, "apps/dashboard/components/data-panels.tsx"),
        e("RADIUS_DASHBOARD_INTERNAL_URL", "str", "http://localhost:3000", "Dashboard origin used for server-side calls to its own proxy.", {"dashboard"}, "apps/dashboard/lib/api.ts"),
        e("RADIUS_HSTS_ENABLED", "bool", "false", "Dashboard side of the flag defined for the API: send Strict-Transport-Security and CSP `upgrade-insecure-requests`. Enable only behind TLS.", {"dashboard"}, "apps/dashboard/middleware.ts"),
        e("PORT", "int", "8000 (api), 3000 (dashboard)", "Listen port in the API and dashboard images (`uvicorn --port ${PORT:-8000}`; dashboard `PORT=3000`).", {"api", "dashboard"}, "apps/api/Dockerfile"),
        e("RADIUS_EXTRAS", "str", "empty", "Compose build argument: extra Python dependency groups to install in the api and worker images (for example `llm`, `observability`).", {"compose build"}, "docker-compose.yml"),
        e("POSTGRES_HOST_PORT", "int", "5432", "Compose: host port published for the bundled PostgreSQL.", {"compose"}, "docker-compose.yml"),
    ]
    return [*items, *_llm_entries()]


# --------------------------------------------------------------------------- scan


def scan_literals() -> set[str]:
    """Env-looking string literals in non-test Python sources and the dashboard."""

    found: set[str] = set()
    roots = [*(ROOT / "apps").glob("*/src"), *(ROOT / "packages").glob("*/src")]
    for root in roots:
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found.update(SCAN_PATTERN.findall(text))
    for path in (ROOT / "apps" / "dashboard").rglob("*.ts*"):
        if "node_modules" in path.parts or ".next" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(re.findall(r"process\.env\.([A-Z][A-Z0-9_]+)", text))
    return {n for n in found if n not in NOT_ENV and not n.endswith("_")}


# --------------------------------------------------------------------------- build


def collect() -> tuple[list[Entry], list[str]]:
    entries = pydantic_entries()
    problems: list[str] = []
    for extra in extra_entries():
        if extra.name in entries:
            continue
        source = ROOT / extra.source
        if not source.is_file() or extra.name not in source.read_text(encoding="utf-8", errors="replace").replace("${PORT", "PORT"):
            if not (extra.name == "PORT" and source.is_file()):
                problems.append(f"{extra.name}: not found in {extra.source}")
        entries[extra.name] = extra
    for name, entry in entries.items():
        if not entry.description:
            entry.description = DESCRIPTIONS.get(name, "")
        if name.startswith("RADIUS_FEATURE_") and not entry.status:
            entry.status = "feature flag, off by default" if entry.default in {"false", "off"} else "feature flag, on by default"
        if name in STATUS_OVERRIDE:
            entry.status = STATUS_OVERRIDE[name]
    undocumented = sorted(scan_literals() - set(entries) - {"NODE_ENV"})
    ordered = sorted(entries.values(), key=lambda x: (_group(x), x.name))
    return ordered, undocumented


def _group(entry: Entry) -> int:
    name = entry.name
    if name.startswith("RADIUS_FEATURE_"):
        return 2
    if name.startswith(("RADIUS_LLM_", "ANTHROPIC", "GEMINI")):
        return 3
    if name.startswith(("WORKER_", "REPOSITORY_")):
        return 1
    if name.startswith(("NEXT_PUBLIC", "RADIUS_DASHBOARD", "RADIUS_API_KEY", "RADIUS_API_BASE", "RADIUS_ORGANIZATION")):
        return 4
    return 0


GROUP_TITLES = {
    0: "Core, API, GitHub and observability",
    1: "Worker, queue and test execution",
    2: "Feature flags",
    3: "LLM and third-party egress",
    4: "Dashboard",
}

HEADER = """\
# Configuration reference

> Generated by `scripts/gen_config_reference.py` from the pydantic settings classes and the
> other places the code reads the environment. Do not edit by hand: run
> `python scripts/gen_config_reference.py` and commit the result. `tests/test_config_reference.py`
> fails when this file drifts from the code.

How to read it.

- **Variable**: the environment variable name (pydantic `alias`, or the upper-cased field name).
- **Service**: which process reads it. `api`, `worker`, `dashboard`; `library` means a package
  reads it but neither service calls that code today; `none (legacy)` means no live code path.
- **Default**: the value used when the variable is unset or empty (`env_ignore_empty` is on for the
  shared settings classes). `empty` is the empty string; `unset` is `None`.
- **Secret**: yes means the value is a credential or contains one. Never log it, never commit it,
  never give it a `NEXT_PUBLIC_` prefix.
- **Status**: feature flags and opt-ins. A flag marked "off by default" changes nothing until you set it.
- `docker-compose.yml` only forwards the variables it lists. Variables that are not forwarded
  (for example `CORS_ORIGINS`) must be added to the service `environment:` block or supplied some
  other way; see [INSTALL.md](INSTALL.md).
- Unparseable values: booleans accept `true/false/1/0/yes/no/on/off`; the hand-parsed LLM variables
  (`RADIUS_LLM_*`) silently fall back to their default on a bad number.

"""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ") if text else "-"


def render() -> str:
    entries, undocumented = collect()
    lines = [HEADER]
    lines.append(f"Variables documented: **{len(entries)}** "
                 f"({sum(1 for e in entries if e.secret)} secret, "
                 f"{sum(1 for e in entries if e.name.startswith('RADIUS_FEATURE_'))} feature flags).\n")
    for group in sorted(GROUP_TITLES):
        rows = [e for e in entries if _group(e) == group]
        if not rows:
            continue
        lines.append(f"## {GROUP_TITLES[group]}\n")
        lines.append("| Variable | Type | Default | Service | Secret | Status | Description |")
        lines.append("|---|---|---|---|---|---|---|")
        for e in rows:
            default = "(secret, no default)" if e.secret and e.default in {"empty", "unset"} else e.default
            if e.secret and e.default not in {"empty", "unset", "required"}:
                default = "(placeholder in code, change it)" if e.name == "SESSION_SECRET" else e.default
            lines.append(
                f"| `{e.name}` | {_cell(e.type)} | `{_cell(default)}` | {_cell(', '.join(sorted(e.services)))} "
                f"| {'yes' if e.secret else 'no'} | {_cell(e.status)} | {_cell(e.description)} |"
            )
        lines.append("")
    if undocumented:
        lines.append("## Undocumented (found in source)\n")
        lines.extend(f"- `{name}`" for name in undocumented)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def problems() -> list[str]:
    entries, undocumented = collect()
    out = [f"undocumented variable found in source: {n}" for n in undocumented]
    for e in entries:
        if not e.description:
            out.append(f"{e.name}: no description in the code")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is out of date")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.exists() else ""
        issues = problems()
        if current != text:
            issues.insert(0, f"{_rel(OUTPUT)} is out of date; run scripts/gen_config_reference.py")
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1 if issues else 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {_rel(OUTPUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
