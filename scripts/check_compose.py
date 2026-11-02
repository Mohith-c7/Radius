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
#: defaults allowed in the base file.
WAIVED_LITERALS: dict[tuple[str, str], str] = {
    ("postgres", "POSTGRES_PASSWORD"): "bundled local DB; port bound to loopback only",
    ("migrations", "DATABASE_URL"): "same bundled DB credential, container network only",
    ("api", "DATABASE_URL"): "same bundled DB credential, container network only",
    ("worker", "DATABASE_URL"): "same bundled DB credential, container network only",
}

#: Values that are placeholders, not secrets, when found in .env.example.
PLACEHOLDER = re.compile(
    r"^(|[0-9]+|your_[a-z0-9_]+|[a-z0-9._-]+@[a-z0-9.-]+|postgresql\+psycopg://radius:radius@localhost:\d+/radius|"
    r"claude-[a-z0-9-]+|pinned-tag|your-registry/[a-z0-9:/_.-]+|\*)$",
    re.IGNORECASE,
)
DEV_SERVICES = {"api", "dashboard", "worker"}


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
            has_literal_default = bool(re.search(r"\$\{[^}]*:?-[^}]+\}", value)) or (
                "${" not in value and value != ""
            )
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
