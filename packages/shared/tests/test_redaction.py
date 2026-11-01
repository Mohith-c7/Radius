import json
import logging

import pytest
from radius_shared.logging import JsonFormatter
from radius_shared.redaction import REDACTED, redact_secrets

TOKEN = "ghs_abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.mark.parametrize(
    "text",
    [
        f"https://x-access-token:{TOKEN}@github.com/acme/radius.git",
        f"http.extraheader=Authorization: Bearer {TOKEN}",
        f"Authorization: token {TOKEN}",
        f"Bearer {TOKEN}",
        f"X-Radius-API-Key: {TOKEN}",
        f"POST /x?api_key={TOKEN}&a=1",
        f"leaked {TOKEN} in output",
        f"-----BEGIN RSA PRIVATE KEY-----\n{TOKEN}\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_redact_secrets_removes_credentials(text: str) -> None:
    redacted = redact_secrets(text)

    assert TOKEN not in redacted
    assert REDACTED in redacted


def test_redact_secrets_keeps_ordinary_text_and_truncates_after_redaction() -> None:
    assert redact_secrets("Recovered stale running job.") == "Recovered stale running job."
    assert redact_secrets("https://github.com/acme/radius.git") == "https://github.com/acme/radius.git"
    truncated = redact_secrets(f"{TOKEN} " + "x" * 100, max_length=20)
    assert len(truncated) == 20
    assert "ghs_" not in truncated


def test_json_formatter_redacts_message_extras_and_exception() -> None:
    try:
        raise RuntimeError(f"clone https://x-access-token:{TOKEN}@github.com/a/b.git")
    except RuntimeError:
        record = logging.LogRecord(
            "radius", logging.ERROR, __file__, 1, "failed with %s", (TOKEN,), exc_info=None
        )
        import sys

        record.exc_info = sys.exc_info()
    record.error = f"Authorization: Bearer {TOKEN}"

    payload = json.loads(JsonFormatter().format(record))

    assert TOKEN not in json.dumps(payload)
    assert payload["error"] == f"Authorization: {REDACTED}"


@pytest.mark.parametrize(
    "text",
    [
        # key=value rule must not consume only the BEGIN marker and leave the body.
        f"private_key=-----BEGIN RSA PRIVATE KEY-----\nMIIEbody{TOKEN}\n-----END RSA PRIVATE KEY-----",
        # Truncated output without an END marker.
        f"error: -----BEGIN RSA PRIVATE KEY-----\nMIIEbody{TOKEN}\n",
        # JSON-quoted secrets.
        f'{{"secret": "{TOKEN}", "ok": 1}}',
        f'{{"api_key":"{TOKEN}"}}',
    ],
)
def test_redact_secrets_handles_pem_bodies_truncation_and_json(text: str) -> None:
    redacted = redact_secrets(text)

    assert TOKEN not in redacted
    assert "MIIEbody" not in redacted
    assert REDACTED in redacted
