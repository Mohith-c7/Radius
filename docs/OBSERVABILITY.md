# Observability

Task F-10. Structured logs with correlation ids are always on. Tracing and
metrics are optional and **off by default**; with the defaults, behaviour is
unchanged.

Code lives in `packages/shared/src/radius_shared/observability/`, plus
`logging.py` and `redaction.py` in the same package.

## Structured logs

Every log line is one JSON object. Correlation ids bound through
`radius_shared.observability.bind_correlation` (contextvars, so they are
per-request and per-job) are added automatically:

| Field | Set by |
| --- | --- |
| `request_id` | API middleware (`X-Request-ID` header is honoured if it is 1-64 chars of `A-Za-z0-9._-`, otherwise generated; echoed in the response) |
| `delivery_id` | webhook handler (`X-GitHub-Delivery`) |
| `organization_id` | webhook handler (resolved tenant); worker (the analysis' repository organization) |
| `analysis_id`, `job_id` | worker, around each claimed job |
| `trace_id` | added when a span is active |

Lines logged before a job is bound (for example the queue's "claimed" line)
carry `analysis_id`/`job_id` from their own `extra` only.

### Redaction

Secrets are removed by `radius_shared.redaction` before a line is written:
the JSON formatter redacts the message, exception text and every extra field,
and `RedactingFilter` (installed by `configure_logging`) does the same for any
handler on the logger. Covered: Authorization/Bearer headers, `token`,
`password`, `secret`, `api_key`, `private_key` style fields (whole value
replaced when the key name is sensitive, including inside nested dicts and
lists), PEM private key blocks, credentials in URLs, GitHub tokens, JWTs, AWS
access key ids and `sk-` style keys. Redaction is pattern based: a secret in
an unrecognised format and under an innocuous key name would not be caught.
Tests: `packages/shared/tests/test_observability.py`.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `RADIUS_TRACING_ENABLED` | `false` | Create OpenTelemetry spans. Needs the `observability` extra. |
| `RADIUS_OTLP_ENDPOINT` | empty | OTLP/HTTP traces URL, e.g. `http://localhost:4318/v1/traces`. Empty: spans are recorded but not exported. |
| `RADIUS_OTEL_SERVICE_NAME` | `radius-api` / `radius-worker` | `service.name` resource attribute. |
| `RADIUS_METRICS_ENABLED` | `false` | Serve Prometheus metrics. Needs the `observability` extra. |
| `RADIUS_WORKER_METRICS_PORT` | `0` | Worker metrics HTTP port (`0` = off). |

Install the libraries with `pip install ".[observability]"`. They are also in
the `dev` extra so tests run them. If a flag is on but the libraries are
missing, a warning is logged and the feature stays off.

## Traces

Spans: `http.request` (API middleware) -> `webhook.handle` -> `queue.enqueue`
-> `worker.job` -> `stage.<name>` for `analyze_changes`, `parse`,
`build_graph`, `discover_tests`, `select_tests`, `run_tests`, `blast_radius`,
`confidence` and `publish`. Correlation ids are span attributes
(`radius.analysis_id`, ...).

### Cross-process propagation

The W3C `traceparent` of the enqueuing span is stored in the nullable
`analysis_jobs.traceparent` text column (migration `20261102_0010`) by
`queue.enqueue`, and returned on the claimed job. The worker starts
`worker.job` as a child of it, so API and worker spans form one trace even in
separate containers. The value is kept across retries, so every attempt
continues the same trace (one `worker.job` span per attempt). An explicit
re-enqueue of a failed job replaces it with the new caller's trace.

The column is NULL when tracing is off, for rows created before the migration,
and when the stored value is malformed; in those cases the worker silently
starts a fresh trace. `radius.analysis_id` remains a join key across traces.

## Metrics

Exposed at `GET /metrics` on the API (404 when disabled) and on the worker's
`RADIUS_WORKER_METRICS_PORT`.

| Metric | Type | Notes |
| --- | --- | --- |
| `radius_job_duration_seconds{outcome}` | histogram | one job attempt, `completed`/`failed` |
| `radius_stage_duration_seconds{stage}` | histogram | per pipeline stage |
| `radius_stage_failures_total{stage}` | counter | failures by stage |
| `radius_job_retries_total` | counter | attempts requeued (worker) |
| `radius_queue_depth{status}` | gauge | jobs by status, read from the DB at scrape time |
| `radius_sandbox_kills_total{reason}` | counter | containers killed on timeout |
| `radius_llm_cost_usd_total` | counter | **placeholder**: nothing records to it yet |

Job, stage, retry and failure series come from the worker process, so they
appear on the worker endpoint, not the API's. Queue depth is on both.

## Health and readiness

- `GET /api/v1/health`: liveness; unchanged.
- `GET /api/v1/ready`: with SQL storage runs `select 1` and reads the
  `analysis_jobs` table; with memory storage checks the in-process queue.
  Response on success is unchanged. On failure it returns **503** with the
  standard error envelope (`code: not_ready`); previously an unhandled error
  produced a 500. Exception detail is logged, not returned.

## Viewing a trace locally

Use the optional compose profile (Jaeger for traces, Prometheus for metrics):

```bash
export RADIUS_EXTRAS="[observability]"           # install the libraries in the images
export RADIUS_TRACING_ENABLED=true
export RADIUS_OTLP_ENDPOINT=http://jaeger:4318/v1/traces
export RADIUS_METRICS_ENABLED=true
export RADIUS_WORKER_METRICS_PORT=9100
docker compose --profile observability up -d --build
```

- Jaeger UI: <http://localhost:16686> (services `radius-api`, `radius-worker`)
- Prometheus: <http://localhost:9090> (targets configured in
  `infra/observability/prometheus.yml`)
- API metrics: <http://localhost:8000/metrics>

Without Docker, set `RADIUS_TRACING_ENABLED=true` and an OTLP endpoint
pointing at any OTLP/HTTP collector, or run the acceptance test, which
exports to an in-memory exporter:

```bash
python -m pytest apps/worker/tests/test_observability_flow.py
```

## Follow-ups

- Record real LLM token cost into `radius_llm_cost_usd_total`.
- Propagate correlation ids into sandboxed test runs if useful.
