# radius-client (Python)

A small, typed, **dependency-free** client for the stable routes of the Radius HTTP API
(`/api/v1`). It uses only the standard library (`urllib`, `dataclasses`, `typing`) and is
**not published** to any package index; install it from the repository:

```bash
pip install ./clients/python      # or add clients/python to PYTHONPATH
```

Stable here means the routes marked `x-stability: stable` in
[`docs/api/openapi.json`](../../docs/api/openapi.json) (see
[`docs/api/STABILITY.md`](../../docs/api/STABILITY.md)). Intent is beta; its read and
confirm calls are included because CI and review tooling use them.

## Examples

```python
from radius_client import RadiusClient, StaleEtagError, NotFoundError

client = RadiusClient("https://radius.example.com", ORG_ID, API_KEY)

# Analyses
for analysis in client.list_analyses(status="completed"):
    print(analysis["id"], analysis["commit_sha"])
analysis = client.lookup_analysis(pull_request=42, commit_sha=head_sha, repository="acme/api")

# Confidence and the evidence-gated verdict
report = client.get_confidence(analysis["id"])
if report["verification_status"] != "verified":      # unknown values: treat as not verified
    print(report["summary"])

# Upload a CI test report (JUnit XML or Radius JSON) bound to the analysed commit
with open("junit.xml", "rb") as handle:
    client.upload_test_results(analysis["id"], handle.read(), commit_sha=head_sha)

# Intent: read with the ETag, confirm with If-Match
snapshot = client.get_intent(analysis["id"])           # Versioned[IntentSnapshot]
criterion = snapshot.data["criteria"][0]
try:
    client.confirm_criterion(analysis["id"], criterion["id"], if_match=snapshot)
except StaleEtagError:
    snapshot = client.get_intent(analysis["id"])       # someone else changed it: re-read
```

## Behaviour

* **Errors are typed.** Non-2xx answers raise a subclass of `ApiError` carrying `status`,
  `code` (from the error envelope) and `message`: `AuthError` (401/403), `NotFoundError`,
  `ConflictError` (`StaleEtagError` for `INTENT_STALE`), `ValidationFailedError`,
  `PayloadTooLargeError`, `UnsupportedMediaTypeError`, `RateLimitedError`, `ServerError`.
  Connection problems raise `TransportError`. All derive from `RadiusError`.
* **Retries.** `429` is retried (any method; the server rejected it before processing)
  honoring `Retry-After` (seconds or HTTP-date), falling back to exponential backoff.
  A `Retry-After` longer than `max_retry_after` (default 60 s) is raised as
  `RateLimitedError` instead of sleeping. `GET` also retries 502/503/504 and connection
  errors. Writes are never retried on 5xx. Tune with `max_retries`, `backoff_base`.
* **ETags.** Reads that return an `ETag` give a `Versioned` value (`.data`, `.etag`);
  pass it (or the raw string) as `if_match` on writes.
* **Unknown fields are preserved.** Payloads are plain dicts annotated with `TypedDict`,
  so fields added by newer servers are not dropped.
* **Redirects are not followed**, so credentials never go to another host. The API key is
  never shown in `repr()`.
* **Custom transport.** Pass any object with `request(method, url, headers, body, timeout)
  -> TransportResponse` (used by the tests, proxies, or an async bridge).

## Tests

```bash
python -m pytest clients/python/tests
```

`test_client.py` uses an in-process fake transport. `test_contract_against_app.py` runs the
client against the real ASGI app (it is skipped when the API sources are not importable).
