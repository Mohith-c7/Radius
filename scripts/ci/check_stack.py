"""Assert that the Docker Compose stack really boots and stays up (used by stack.yml).

Runs after ``docker compose ... up -d --wait``. Stdlib only. It checks, in order:

1. every long-running service is still ``running`` (and healthy where it has a health
   check) after a stability window, which catches crash loops and late import errors;
   the one-shot ``migrations`` service must have exited with code 0;
2. API ``/api/v1/health`` and ``/api/v1/ready`` answer 200;
3. the dashboard answers 200 on ``/`` (after the redirect to sign-in) and on ``/login``;
4. the worker log contains its ready line.

Exit code 0 = all good, 1 = at least one problem (each is printed).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

LONG_RUNNING = ("postgres", "api", "worker", "dashboard")
ONE_SHOT = ("migrations",)
WORKER_READY_LINE = "Radius worker ready"


def parse_ps(output: str) -> list[dict]:
    """Parse ``docker compose ps --format json`` (a JSON array or one object per line)."""

    text = output.strip()
    if not text:
        return []
    if text.startswith("["):
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def evaluate_services(rows: list[dict]) -> list[str]:
    """Return one message per service that is not in its expected state."""

    by_service = {row.get("Service"): row for row in rows}
    problems: list[str] = []
    for name in LONG_RUNNING:
        row = by_service.get(name)
        if row is None:
            problems.append(f"{name}: no container found")
            continue
        state = row.get("State")
        health = row.get("Health") or ""
        if state != "running":
            problems.append(
                f"{name}: state is {state!r} (exit code {row.get('ExitCode')}), expected 'running'"
            )
        elif health not in ("", "healthy"):
            problems.append(f"{name}: health is {health!r}, expected 'healthy'")
    for name in ONE_SHOT:
        row = by_service.get(name)
        if row is None:
            problems.append(f"{name}: no container found")
        elif row.get("State") != "exited" or row.get("ExitCode") != 0:
            problems.append(
                f"{name}: expected exited with code 0, got state {row.get('State')!r} exit {row.get('ExitCode')}"
            )
    return problems


def worker_is_ready(log_text: str) -> bool:
    return WORKER_READY_LINE in log_text


def http_status(url: str, timeout: float = 10.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed http URLs
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return 0


def wait_for_200(url: str, seconds: float) -> int:
    deadline = time.monotonic() + seconds
    status = http_status(url)
    while status != 200 and time.monotonic() < deadline:
        time.sleep(2)
        status = http_status(url)
    return status


def compose(base: list[str], *args: str) -> str:
    result = subprocess.run([*base, *args], capture_output=True, text=True, check=False)  # noqa: S603
    return result.stdout + result.stderr if args[0] == "logs" else result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stability-seconds", type=int, default=60)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--dashboard", default="http://127.0.0.1:3000")
    parser.add_argument(
        "--compose",
        nargs="+",
        default=[
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
        ],
    )
    args = parser.parse_args(argv)

    problems: list[str] = []
    print(f"waiting {args.stability_seconds}s to catch crash loops ...", flush=True)
    time.sleep(args.stability_seconds)

    problems += evaluate_services(
        parse_ps(compose(args.compose, "ps", "-a", "--format", "json"))
    )

    for url in (
        f"{args.api}/api/v1/health",
        f"{args.api}/api/v1/ready",
        f"{args.dashboard}/",
        f"{args.dashboard}/login",
    ):
        status = wait_for_200(url, 30)
        print(f"GET {url} -> {status}")
        if status != 200:
            problems.append(f"GET {url} returned {status}, expected 200")

    if not worker_is_ready(compose(args.compose, "logs", "--no-color", "worker")):
        problems.append(f"worker log does not contain {WORKER_READY_LINE!r}")

    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    print("stack checks: " + ("FAILED" if problems else "ok"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
