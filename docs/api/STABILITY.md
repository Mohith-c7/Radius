# API stability policy

Status: policy for the HTTP API served under `/api/v1`. The machine-readable contract
is [`openapi.json`](openapi.json) (OpenAPI 3.1, generated, do not edit by hand).

## Versioning

* The major version is part of the path: `/api/v1/...`. A breaking change to a stable
  operation ships as `/api/v2/...` next to `/api/v1`; v1 then follows the deprecation
  policy below.
* The document's `info.version` is the application version (SemVer). Additive changes
  bump the minor version; fixes bump the patch version.
* Every operation and tag carries `x-stability` in the OpenAPI document.

## Stability levels and route map

| Level | Promise |
| --- | --- |
| `stable` | No breaking change within `/api/v1`. Deprecation policy applies. |
| `beta` | Shape is intended to last but may change in a minor release. Changes are announced in the CHANGELOG; no minimum notice. |
| `alpha` | May change or disappear at any time. Off by default behind a feature flag and not in `openapi.json`. |
| `internal` | Used by the Radius dashboard, GitHub or CI helpers. Not a client contract; may change in any release. |

| Route group (tag) | Level | Notes |
| --- | --- | --- |
| `health` (`/health`, `/ready`) | stable | Probe responses only add fields. |
| `repositories` | stable | |
| `analyses` (list, get, lookup, start, rerun) | stable | `blast-radius` is beta. |
| `confidence` | stable | The envelope and field names are stable. `confidence_score` is an uncalibrated heuristic (`score_kind`), so its values may change between releases. `verification_status` may gain values: treat unknown ones as "not verified". |
| `tests` (selection, results upload, results) | stable | `history`, `statistics`, `recent`, `flaky` are beta. |
| `graph` | beta | |
| `coverage` | beta | |
| `intent` | beta | ETag/If-Match semantics and error codes are intended to be stable; view shapes may still grow. |
| `verdict-v2` (`GET /analyses/{id}/verdict`) | alpha | Behind `RADIUS_FEATURE_VERDICT_V2` (`off` default, `shadow`, `on`). Hidden from `openapi.json` in every flag state; answers 404 today. |
| `github-webhooks` | internal | Called by GitHub; authenticated by HMAC signature. |
| `authentication` (`/auth/*`) | internal | Dashboard session cookie flow. |

The CLI flags, GitHub Action inputs and configuration keys follow the same levels and
are listed in their own references.

## What counts as a breaking change

For `stable` operations, any of these is breaking:

* removing or renaming an operation, path or `operationId`;
* removing a response field, changing its type, or making a non-null field nullable;
* removing a value that a response enum can return (adding one is allowed, see the
  client rules below);
* a new required request parameter, header or body property; narrowing the accepted
  type or enum of a request field; making an optional parameter required;
* removing a success status code, or changing the meaning of an existing status code
  or error `code`;
* tightening authentication or authorization for callers that were allowed;
* changing the envelope (`{success, data, error, meta}`) or the `ETag`/`If-Match`
  semantics.

Not breaking: new operations, new optional request fields, new response fields, new
error codes inside an already documented status, new enum values documented as open,
changes to `message` text, performance and rate-limit tuning within the documented
`429` contract.

`scripts/openapi_diff.py` enforces the structural part of this list (see below).

## Client rules for unknown fields

* Ignore response fields you do not know; never fail because an object has extra keys.
* Treat unknown enum values (`status`, `verification_status`, `risk_level`, ...) as an
  unknown state and fall back to the safe behaviour (for a verdict: not verified).
* Branch on `error.code`, not on `error.message`.
* Send only documented request fields; intent requests reject unknown fields with 422.
* Honor `Retry-After` on `429` and send the `ETag` back as `If-Match` on intent writes.

## Deprecation policy

1. Announce the deprecation in `CHANGELOG.md` (fragment type `deprecated`) and mark the
   operation `deprecated: true` in the OpenAPI document with a pointer to the
   replacement.
2. From the release that announces it, the operation answers with
   `Deprecation: true` (or an HTTP-date) and `Sunset: <HTTP-date>` headers
   (RFC 9745 and RFC 8594) and a `Link: <replacement>; rel="successor-version"` header.
3. Minimum notice for `stable` operations: at least one minor release and at least 90
   days, whichever is longer. For `beta`: announced in the CHANGELOG, at least one
   minor release when feasible. `alpha` and `internal`: none.
4. Removal ships in the next major version of the path (`/api/v2`) or, for beta,
   in a minor release at or after the `Sunset` date.

## Enforcement

* `python scripts/export_openapi.py --check` (run by `apps/api/tests/test_openapi_contract.py`)
  fails when `docs/api/openapi.json` is stale. Regenerate with
  `python scripts/export_openapi.py` and commit the result.
* `python scripts/openapi_diff.py --base origin/develop` compares the spec with the
  previously committed one and fails on removed or renamed stable operations, new
  required inputs, removed response fields and narrowed types. The same check runs as
  a test when `origin/develop` is reachable. It is a deliberately small stand-in for
  [`oasdiff`](https://github.com/oasdiff/oasdiff); use oasdiff locally for deeper
  analysis (`oneOf`, polymorphism, media types), which the guard does not model.
* An intentional break is acknowledged by listing `METHOD /path` in
  [`breaking-changes-ack.txt`](breaking-changes-ack.txt), in the same change as the
  CHANGELOG entry and the version bump.

## Python client

`clients/python/radius_client` is a hand-written, dependency-free client for the stable
routes. See its README. It is not published to a package index.
