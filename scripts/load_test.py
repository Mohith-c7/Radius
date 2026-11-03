"""Small asyncio load test for a LOCAL Radius stack (stdlib only, no extra dependencies).

Exercises the API read paths (health, ready, repositories, analyses) with API-key
headers and the GitHub webhook endpoint with correctly signed ``ping`` deliveries,
at a configurable concurrency, then prints a JSON report with p50/p95/p99 latency
and error rate per scenario. ``--budget`` turns it into a pass/fail check.

Refuses to run against a non-loopback host unless ``--allow-remote`` is given:
it is meant for your own ``docker compose`` stack, never for third-party systems.

Example (dev stack from ``make dev``; values come from ``.env``):

    python scripts/load_test.py --base-url http://127.0.0.1:8000 \
        --organization-id "$GITHUB_DEFAULT_ORGANIZATION_ID" --api-key "$RADIUS_API_KEY" \
        --webhook-secret "$GITHUB_WEBHOOK_SECRET" --concurrency 8 --requests 400 \
        --budget p95_ms=500,error_rate=0.01

Exit code: 0 ok, 1 budget exceeded, 2 usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import math
import sys
import time
import uuid
from urllib.parse import urlsplit

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
BUDGET_KEYS = {"p50_ms", "p95_ms", "p99_ms", "error_rate"}


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (0 < pct <= 100). Empty input gives 0.0."""

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def sign_payload(secret: str, body: bytes) -> str:
    """GitHub-style ``X-Hub-Signature-256`` value."""

    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def summarize(latencies_ms: list[float], errors: int, elapsed_s: float) -> dict:
    total = len(latencies_ms)
    return {
        "requests": total,
        "errors": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "p50_ms": round(percentile(latencies_ms, 50), 2),
        "p95_ms": round(percentile(latencies_ms, 95), 2),
        "p99_ms": round(percentile(latencies_ms, 99), 2),
        "rps": round(total / elapsed_s, 2) if elapsed_s > 0 else 0.0,
    }


def parse_budget(text: str) -> dict[str, float]:
    budget: dict[str, float] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        key, sep, value = item.partition("=")
        if not sep or key not in BUDGET_KEYS:
            msg = f"bad budget item {item!r}; keys: {', '.join(sorted(BUDGET_KEYS))}"
            raise ValueError(msg)
        budget[key] = float(value)
    return budget


def check_budget(results: dict[str, dict], budget: dict[str, float]) -> list[str]:
    """Return one message per scenario metric above its budget."""

    violations: list[str] = []
    for name, stats in results.items():
        for key, limit in budget.items():
            if stats[key] > limit:
                violations.append(f"{name}: {key}={stats[key]} exceeds budget {limit}")
    return violations


def ping_request(secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps({"zen": "load test", "hook_id": 1}).encode()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": str(uuid.uuid4()),
        "X-Hub-Signature-256": sign_payload(secret, body),
    }
    return body, headers


async def http_request(
    host: str, port: int, method: str, path: str, headers: dict[str, str], body: bytes = b"",
    timeout: float = 15.0,
) -> int:
    """Minimal HTTP/1.1 request over asyncio streams; returns the status code (0 on failure)."""

    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}:{port}", "Connection: close"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    if body:
        lines.append(f"Content-Length: {len(body)}")
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.write(raw)
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout)
        writer.close()
        return int(status_line.split()[1])
    except (TimeoutError, OSError, ValueError, IndexError):
        return 0


async def run_scenario(
    make_request, total: int, concurrency: int
) -> dict:
    """Run ``total`` requests with at most ``concurrency`` in flight; 2xx counts as success."""

    latencies: list[float] = []
    errors = 0
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(total):
        queue.put_nowait(index)

    async def worker() -> None:
        nonlocal errors
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            started = time.perf_counter()
            status = await make_request()
            latencies.append((time.perf_counter() - started) * 1000)
            if not 200 <= status < 300:
                errors += 1

    begin = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    return summarize(latencies, errors, time.perf_counter() - begin)


async def run_all(args: argparse.Namespace) -> dict[str, dict]:
    parts = urlsplit(args.base_url)
    host, port = parts.hostname or "127.0.0.1", parts.port or 80
    auth = {
        "X-Radius-Organization-Id": args.organization_id or "",
        "X-Radius-API-Key": args.api_key or "",
    }
    prefix = parts.path.rstrip("/") + "/api/v1"
    scenarios: dict[str, object] = {
        "health": lambda: http_request(host, port, "GET", f"{prefix}/health", {}),
        "ready": lambda: http_request(host, port, "GET", f"{prefix}/ready", {}),
    }
    if args.organization_id and args.api_key:
        for name in ("repositories", "analyses"):
            scenarios[f"read_{name}"] = (
                lambda n=name: http_request(host, port, "GET", f"{prefix}/{n}", auth)
            )
    if args.webhook_secret:

        async def webhook() -> int:
            body, headers = ping_request(args.webhook_secret)
            return await http_request(host, port, "POST", f"{prefix}/webhooks/github", headers, body)

        scenarios["webhook_ping_signed"] = webhook
    results = {}
    for name, factory in scenarios.items():
        results[name] = await run_scenario(factory, args.requests, args.concurrency)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--organization-id")
    parser.add_argument("--api-key")
    parser.add_argument("--webhook-secret")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--requests", type=int, default=200, help="requests per scenario")
    parser.add_argument("--budget", default="", help="e.g. p95_ms=500,p99_ms=1500,error_rate=0.01")
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args(argv)

    host = urlsplit(args.base_url).hostname
    if host not in LOOPBACK and not args.allow_remote:
        print(f"refusing non-loopback host {host!r}; use --allow-remote only for your own system", file=sys.stderr)
        return 2
    try:
        budget = parse_budget(args.budget)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    results = asyncio.run(run_all(args))
    violations = check_budget(results, budget)
    print(json.dumps({"results": results, "budget": budget, "violations": violations}, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
