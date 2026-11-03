"""Seeded random fuzz of the webhook signature check and JSON body parsing.

hypothesis is not a project dependency, so this uses ``random.Random`` with fixed
seeds (reproducible). Properties: (1) a wrong or malformed signature is always
rejected with 403, never 500; (2) a correctly signed but malformed/odd body never
produces a 5xx.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import string
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

SECRET = "fuzz-webhook-secret"
URL = "/api/v1/webhooks/github"
EVENTS = ["ping", "push", "pull_request", "issues", "installation", "installation_repositories", "x"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    org_id = uuid4()
    with Session(engine) as session:
        session.add(db_models.Organization(id=org_id, name="Fuzz"))
        session.commit()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("GITHUB_SINGLE_TENANT", "true")
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(org_id))
    get_api_settings.cache_clear()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def post(client, body: bytes, signature: str | None, event: str = "ping"):
    headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": str(uuid4())}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post(URL, content=body, headers=headers)


def random_text(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.printable + "é€\u0000") for _ in range(n))


def random_json_value(rng: random.Random, depth: int = 0):
    kinds = ["null", "bool", "int", "float", "str", "list", "dict"]
    kind = rng.choice(kinds if depth < 3 else kinds[:5])
    if kind == "null":
        return None
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "int":
        return rng.randint(-(2**70), 2**70)
    if kind == "float":
        return rng.uniform(-1e9, 1e9)
    if kind == "str":
        return random_text(rng, rng.randint(0, 20))
    if kind == "list":
        return [random_json_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {random_text(rng, 4): random_json_value(rng, depth + 1) for _ in range(rng.randint(0, 4))}


def test_invalid_signature_always_rejected(client) -> None:
    rng = random.Random(20261103)
    body = json.dumps({"zen": "x"}).encode()
    good = sign(body)
    candidates = [None, "", "sha256=", "sha256=" + "0" * 64, good.upper(), good[:-1], good + "0", "sha1=abc"]
    for _ in range(60):
        candidates.append(random_text(rng, rng.randint(0, 80)))
        candidates.append("sha256=" + "".join(rng.choice("0123456789abcdef") for _ in range(64)))
    for signature in candidates:
        if signature == good:
            continue
        try:
            response = post(client, body, signature)
        except UnicodeEncodeError:
            continue  # header value not representable on the wire; the client refuses it
        assert response.status_code == 403, (signature, response.status_code)
    # body tampered after signing
    assert post(client, body + b" ", good).status_code == 403


def test_signed_ping_is_accepted(client) -> None:
    body = json.dumps({"zen": "x"}).encode()
    assert post(client, body, sign(body)).status_code == 202


def test_signed_arbitrary_bodies_never_5xx(client) -> None:
    rng = random.Random(7)
    bodies: list[bytes] = [b"", b"null", b"[]", b"1", b'"s"', b"{", b"\xff\xfe", b"{}", b"[1,2]"]
    for _ in range(80):
        bodies.append(json.dumps(random_json_value(rng)).encode())
        bodies.append(bytes(rng.randrange(256) for _ in range(rng.randint(0, 64))))
    failures = []
    for body in bodies:
        for event in rng.sample(EVENTS, 3):
            response = post(client, body, sign(body), event)
            if response.status_code >= 500:
                failures.append((event, body[:40], response.status_code))
    assert not failures, failures[:5]
