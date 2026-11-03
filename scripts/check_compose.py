"""Static checker for docker-compose.yml, docker-compose.dev.yml and .env.example.

No Docker needed; reads the files only. Run ``python scripts/check_compose.py``
(exit 1 on problems). ``tests/test_check_compose.py`` runs it in CI.

Rules
  R1  Every ``${VAR}`` reference has a default (``:-``/``-``), is a required form
      (``:?``/``?``), or is documented in ``.env.example``.
  R2  Required (``:?``) variables are documented in ``.env.example``.
  R3  The production-like base file has no literal default for secret-looking
      settings (names containing SECRET, PASSWORD, TOKEN, KEY, PEPPER). Waivers
      are listed in ``WAIVED_LITERALS`` with a reason.
  R4  The base file runs api/worker with RADIUS_ENV=production and has no
      dev-only switches (``DEV_AUTO_VERIFY_EMAIL`` literal, ``EMAIL_DELIVERY_MODE: log``).
  R5  Published ports: no duplicate host ports across the base file, and the
      bundled PostgreSQL is bound to loopback.
  R6  postgres and api define a healthcheck, and every ``service_healthy``
      dependency points at a service that has one.
  R7  The dev override only touches known services, sets RADIUS_ENV=development
      for the api, publishes no ports, and its secrets come from variables
      (no literal values).
  R8  ``.env.example`` holds no value that looks like a real secret (only empty
      values or recognised placeholders for secret-looking names).
  R9  No literal database credential in the base file: ``POSTGRES_PASSWORD`` and the
      password inside every ``DATABASE_URL`` must be a required variable (C-21).
  R10 api and dashboard publish their ports on a configurable bind address that
      defaults to 127.0.0.1 (C-21); production exposure is an explicit choice.
  R11 postgres, api, worker and dashboard have a restart policy, and the worker has a
      ``stop_grace_period`` of at least one minute so ``compose stop`` drains it (C-09).
  R12 Every worker setting (``WorkerSettings`` alias) is forwarded to the worker service
      unless it is listed in ``WORKER_NOT_FORWARDED`` with a reason (C-10).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "docker-compose.yml"
DEV = ROOT / "docker-compose.dev.yml"
ENV_EXAMPLE = ROOT / ".env.example"

SECRET_NAME = re.compile(r"(SECRET|PASSWORD|TOKEN|KEY|PEPPER)", re.IGNORECASE)
VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?P<op>:?[-?+][^}]*)?\}")

#: (service, setting) -> reason. These are the only literal secret-looking
#: defaults allowed in the base file. None are needed today: the database password is
#: a required variable (C-21).
WAIVED_LITERALS: dict[tuple[str, str], str] = {}

#: Worker settings that docker-compose.yml intentionally does not forward (C-10).
_SANDBOX = "sandbox / in-process test execution needs a container runtime the compose worker does not have"
WORKER_NOT_FORWARDED: dict[str, str] = {
    "RADIUS_ALLOW_INSECURE_DEV": "dev-only switch; the base file pins RADIUS_ENV=production",
    "SERVICE_NAME": "log label, not an operator setting",
    "WORKER_HEALTH_FILE": "set by the worker image (ENV) for its healthcheck",
    "WORKER_EXECUTE_TESTS": "legacy flag for in-process test execution; " + _SANDBOX,
    "RADIUS_ALLOW_UNSAFE_EXECUTION": "only relevant to unsafe in-process execution; " + _SANDBOX,
    "RADIUS_FEATURE_COVERAGE_CONTEXTS": "library entry point only, not wired into the pipeline",
    "GITHUB_APP_PRIVATE_KEY_PATH": "a host path is not mounted in the compose worker; use GITHUB_APP_PRIVATE_KEY",
    "WORKER_TEST_RERUNS": _SANDBOX,
    "WORKER_FLAKY_POLICY": _SANDBOX,
    "WORKER_SANDBOX_RUNTIME": _SANDBOX,
    "WORKER_SANDBOX_IMAGE": _SANDBOX,
    "WORKER_SANDBOX_MEMORY": _SANDBOX,
    "WORKER_SANDBOX_CPUS": _SANDBOX,
    "WORKER_SANDBOX_PIDS_LIMIT": _SANDBOX,
    "WORKER_SANDBOX_TMPFS_SIZE": _SANDBOX,
    "WORKER_SANDBOX_NOFILE_LIMIT": _SANDBOX,
    "WORKER_SANDBOX_MAX_FILE_SIZE_BYTES": _SANDBOX,
    "WORKER_SANDBOX_MAX_OUTPUT_BYTES": _SANDBOX,
    "WORKER_SANDBOX_SECCOMP_PROFILE": _SANDBOX,
}
LOOPBACK_BIND = re.compile(r"^\$\{[A-Z_]+:-127\.0\.0\.1\}:|^127\.0\.0\.1:")
RESTARTED = ("postgres", "api", "worker", "dashboard")

#: Values that are placeholders, not secrets, when found in .env.example.
PLACEHOLDER = re.compile(
    r"^(|[0-9]+|your_[a-z0-9_]+|[a-z0-9._-]+@[a-z0-9.-]+|postgresql\+psycopg://radius:radius@localhost:\d+/radius|"
    r"claude-[a-z0-9-]+|pinned-tag|your-registry/[a-z0-9:/_.-]+|\*)$",
    re.IGNORECASE,
)
DEV_SERVICES = {"api", "dashboard", "worker"}


def _default_of(op: str) -> str:
    """The default text of a ``:-`` / ``-`` expansion operator ('' for other operators)."""

    if op.startswith(":-"):
        return op[2:]
    if op.startswith("-"):
        return op[1:]
    return ""


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def parse_env_example(path: Path = ENV_EXAMPLE) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2)
    return values


def walk_strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_strings(value)


def environment_of(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return {item.split("=", 1)[0]: item.split("=", 1)[1] if "=" in item else "" for item in env}
    return {str(k): "" if v is None else str(v) for k, v in env.items()}


def check_var_refs(label: str, doc: dict[str, Any], documented: set[str]) -> list[str]:
    problems: list[str] = []
    for text in walk_strings(doc):
        for match in VAR_REF.finditer(text):
            name, op = match.group(1), match.group("op") or ""
            has_default = op.startswith(("-", ":-"))
            required = op.startswith(("?", ":?"))
            if required and name not in documented:
                problems.append(f"R2 {label}: required ${{{name}}} is not documented in .env.example")
            elif not (has_default or required) and name not in documented:
                problems.append(f"R1 {label}: ${{{name}}} has no default and is not in .env.example")
    return problems


def check_base(base: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    services: dict[str, Any] = base.get("services", {})
    ports_seen: dict[str, str] = {}
    for name, service in services.items():
        env = environment_of(service)
        for setting, value in env.items():
            if not SECRET_NAME.search(setting):
                continue
            literal = VAR_REF.sub("", value).strip()
            has_literal_default = any(
                _default_of(m.group("op") or "") != "" for m in VAR_REF.finditer(value)
            ) or ("${" not in value and value != "")
            if (has_literal_default or literal) and (name, setting) not in WAIVED_LITERALS:
                problems.append(f"R3 base: {name}.{setting} has a literal default")
        if name in {"api", "worker"} and env.get("RADIUS_ENV") != "production":
            problems.append(f"R4 base: {name} must set RADIUS_ENV: production")
        if env.get("DEV_AUTO_VERIFY_EMAIL", "").lower() in {"true", "1", "yes"}:
            problems.append(f"R4 base: {name} hard-codes DEV_AUTO_VERIFY_EMAIL")
        if env.get("EMAIL_DELIVERY_MODE", "") == "log":
            problems.append(f"R4 base: {name} hard-codes EMAIL_DELIVERY_MODE: log")
        for port in service.get("ports", []) or []:
            text = str(port)
            host_part = text.rsplit(":", 1)[0]
            key = re.sub(r"\$\{[A-Za-z_]+:-?([^}]*)\}", r"\1", host_part)
            if key in ports_seen:
                problems.append(f"R5 base: host port {key} published by {ports_seen[key]} and {name}")
            ports_seen[key] = name
            if name == "postgres" and not text.startswith("127.0.0.1:"):
                problems.append("R5 base: postgres must be published on 127.0.0.1 only")
            if name in {"api", "dashboard"} and not LOOPBACK_BIND.match(text):
                problems.append(
                    f"R10 base: {name} port {text} must bind ${{VAR:-127.0.0.1}} by default"
                )
        for setting, value in env.items():
            if setting == "POSTGRES_PASSWORD" or (
                setting == "DATABASE_URL" and "@postgres" in value
            ):
                credential = re.sub(r"\$\{[^}]*\}", "", value)
                literal_password = re.search(r"//[^:@/]+:([^@]+)@", credential)
                required = "${POSTGRES_PASSWORD:?" in value
                if setting == "POSTGRES_PASSWORD":
                    ok = value.startswith("${POSTGRES_PASSWORD:?")
                else:
                    ok = required and not literal_password
                if not ok:
                    problems.append(
                        f"R9 base: {name}.{setting} must use the required ${{POSTGRES_PASSWORD:?...}} variable"
                    )
    for name in RESTARTED:
        if name in services and not services[name].get("restart"):
            problems.append(f"R11 base: {name} needs a restart policy (restart: unless-stopped)")
    worker = services.get("worker", {})
    if worker and _grace_seconds(worker.get("stop_grace_period")) < 60:
        problems.append("R11 base: worker needs stop_grace_period >= 1m so `compose stop` drains it")
    problems.extend(check_worker_forwarding(worker))
    for required in ("postgres", "api"):
        if required not in services or not services[required].get("healthcheck"):
            problems.append(f"R6 base: {required} needs a healthcheck")
    for name, service in services.items():
        depends = service.get("depends_on") or {}
        if isinstance(depends, dict):
            for dep, cond in depends.items():
                if (cond or {}).get("condition") == "service_healthy" and not services.get(dep, {}).get(
                    "healthcheck"
                ):
                    problems.append(f"R6 base: {name} waits for {dep} to be healthy but {dep} has no healthcheck")
    return problems


def _grace_seconds(value: Any) -> float:
    """Seconds of a compose duration such as ``15m``, ``90s`` or ``${VAR:-15m}``; 0 when absent."""

    text = str(value or "")
    default = re.search(r"\$\{[A-Z_]+:-([^}]*)\}", text)
    if default:
        text = default.group(1)
    total = 0.0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)(h|m|s)", text):
        total += float(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def worker_setting_aliases() -> list[str] | None:
    """Env var names of ``WorkerSettings`` (``None`` when the packages cannot be imported)."""

    import importlib

    for src in [*(ROOT / "packages").glob("*/src"), ROOT / "apps" / "worker" / "src"]:
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
    try:
        config = importlib.import_module("radius_worker.config")
    except Exception:  # noqa: BLE001 - optional rule when the environment lacks the deps
        return None
    return [field.alias or name.upper() for name, field in config.WorkerSettings.model_fields.items()]


def check_worker_forwarding(worker: dict[str, Any]) -> list[str]:
    aliases = worker_setting_aliases()
    if aliases is None or not worker:
        return []
    forwarded = set(environment_of(worker))
    return [
        f"R12 base: worker setting {alias} is not forwarded by docker-compose.yml "
        "(add it, or list it in WORKER_NOT_FORWARDED with a reason)"
        for alias in aliases
        if alias not in forwarded and alias not in WORKER_NOT_FORWARDED
    ]


def check_dev(dev: dict[str, Any], base: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    services: dict[str, Any] = dev.get("services", {})
    for name, service in services.items():
        if name not in DEV_SERVICES or name not in base.get("services", {}):
            problems.append(f"R7 dev: unexpected service {name}")
        if service.get("ports"):
            problems.append(f"R7 dev: {name} must not publish ports")
        for setting, value in environment_of(service).items():
            if SECRET_NAME.search(setting) and "${" not in value:
                problems.append(f"R7 dev: {name}.{setting} must come from a variable, not a literal")
    if environment_of(services.get("api", {})).get("RADIUS_ENV") != "development":
        problems.append("R7 dev: api must set RADIUS_ENV: development")
    return problems


def check_env_example(values: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for name, value in values.items():
        if SECRET_NAME.search(name) and not PLACEHOLDER.match(value.strip()):
            problems.append(f"R8 .env.example: {name} has a non-placeholder value")
    return problems


def run(
    base_path: Path = BASE, dev_path: Path = DEV, env_path: Path = ENV_EXAMPLE
) -> list[str]:
    env_values = parse_env_example(env_path)
    documented = set(env_values)
    base, dev = load_yaml(base_path), load_yaml(dev_path)
    return [
        *check_var_refs("base", base, documented),
        *check_var_refs("dev", dev, documented),
        *check_base(base),
        *check_dev(dev, base),
        *check_env_example(env_values),
    ]


def main() -> int:
    problems = run()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("compose files and .env.example are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
