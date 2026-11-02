"""Tests for correlation ids, log redaction, tracing and metrics helpers."""

import io
import json
import logging
from uuid import uuid4

import pytest
from radius_shared.logging import JsonFormatter, RedactingFilter
from radius_shared.observability import (
    TRACE_CARRIERS,
    ObservabilitySettings,
    bind_correlation,
    configure_tracing,
    continue_trace,
    current_traceparent,
    get_correlation_context,
    metrics,
    reset_tracing,
    span,
    stage,
)
from radius_shared.redaction import REDACTED, redact_structure

# Seeded fake secrets. None are real credentials.
GH_TOKEN = "ghs_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAseededfakekeymaterial\n"
    "-----END RSA PRIVATE KEY-----"
)
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzZWVkZWQifQ.c2VlZGVkc2lnbmF0dXJl"
BEARER = "seeded-bearer-value-123456"
API_KEY = "seeded-api-key-value-987654"
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
ALL_SECRETS = (GH_TOKEN, "MIIEowIBAAKCAQEAseededfakekeymaterial", JWT, BEARER, API_KEY, AWS)


def _logger(stream: io.StringIO) -> logging.Logger:
    logger = logging.getLogger(f"radius.test.{uuid4().hex}")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return logger


def test_seeded_secrets_never_reach_log_output() -> None:
    stream = io.StringIO()
    logger = _logger(stream)

    logger.info("clone failed: https://x-access-token:%s@github.com/a/b.git", GH_TOKEN)
    logger.info("headers Authorization: Bearer %s", BEARER)
    logger.info("key material %s", PRIVATE_KEY)
    logger.info("session %s", JWT)
    logger.info("aws %s", AWS)
    logger.info(
        "extras",
        extra={
            "headers": {"Authorization": f"Bearer {BEARER}", "X-Request-ID": "ok"},
            "x_api_key": API_KEY,
            "nested": [{"private_key": PRIVATE_KEY}],
            "note": f"token={GH_TOKEN}",
        },
    )
    try:
        raise RuntimeError(f"failed with api_key={API_KEY} and {PRIVATE_KEY}")
    except RuntimeError:
        logger.exception("boom")

    output = stream.getvalue()
    assert output.count("\n") == 7
    for secret in ALL_SECRETS:
        assert secret not in output
    assert REDACTED in output
    # Non-secret structured data survives.
    assert '"X-Request-ID":"ok"' in output


def test_redaction_filter_protects_non_json_handlers() -> None:
    stream = io.StringIO()
    logger = logging.getLogger(f"radius.test.{uuid4().hex}")
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(token)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)

    logger.warning("auth Authorization: Bearer %s", BEARER, extra={"token": API_KEY})

    assert BEARER not in stream.getvalue()
    assert API_KEY not in stream.getvalue()


def test_redact_structure_keeps_shape_and_masks_sensitive_keys() -> None:
    value = {"user": "octocat", "password": "hunter2", "items": ["a", f"x {JWT}"]}

    redacted = redact_structure(value)

    assert redacted == {
        "user": "octocat",
        "password": REDACTED,
        "items": ["a", f"x {REDACTED}"],
    }


def test_correlation_ids_appear_in_json_logs_and_are_scoped() -> None:
    stream = io.StringIO()
    logger = _logger(stream)
    analysis_id, job_id, org_id = uuid4(), uuid4(), uuid4()

    with bind_correlation(organization_id=org_id, delivery_id="d-1"):
        with bind_correlation(analysis_id=analysis_id, job_id=job_id):
            logger.info("inside")
        logger.info("outer")
    logger.info("outside")

    inside, outer, outside = (json.loads(line) for line in stream.getvalue().splitlines())
    assert inside["analysis_id"] == str(analysis_id)
    assert inside["job_id"] == str(job_id)
    assert inside["organization_id"] == str(org_id)
    assert inside["delivery_id"] == "d-1"
    assert "analysis_id" not in outer and outer["delivery_id"] == "d-1"
    assert get_correlation_context() == {}
    assert not any(key in outside for key in ("delivery_id", "organization_id"))


def test_unknown_correlation_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        with bind_correlation(password="x"):
            pass


def test_tracing_is_a_noop_by_default() -> None:
    reset_tracing()

    assert configure_tracing(ObservabilitySettings()) is False
    with span("anything") as current:
        assert current is None
    assert current_traceparent() is None


def test_trace_context_round_trips_through_carrier_store() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    assert configure_tracing(span_exporter=exporter) is True
    try:
        analysis_id = uuid4()
        with span("producer"):
            TRACE_CARRIERS.put(analysis_id, current_traceparent())
        with continue_trace(TRACE_CARRIERS.pop(analysis_id)), span("consumer"):
            pass
        assert TRACE_CARRIERS.pop(analysis_id) is None

        producer, consumer = exporter.get_finished_spans()
        assert producer.context.trace_id == consumer.context.trace_id
        assert consumer.parent.span_id == producer.context.span_id
    finally:
        reset_tracing()


def test_stage_records_failure_and_error_span() -> None:
    pytest.importorskip("opentelemetry.sdk")
    pytest.importorskip("prometheus_client")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    configure_tracing(span_exporter=exporter)
    metrics.configure_metrics(True)
    try:
        with pytest.raises(RuntimeError):
            with stage("parse"):
                raise RuntimeError("bad")
        (finished,) = exporter.get_finished_spans()
        assert finished.name == "stage.parse"
        assert finished.status.status_code.name == "ERROR"
        text = metrics.render_metrics()[0].decode()
        assert 'radius_stage_failures_total{stage="parse"} 1.0' in text
    finally:
        reset_tracing()
        metrics.configure_metrics(False)


def test_metrics_are_disabled_by_default_and_noop() -> None:
    metrics.configure_metrics(False)

    metrics.record_retry()
    metrics.observe_job(1.0, "completed")

    assert metrics.metrics_enabled() is False
    assert metrics.render_metrics()[0] == b""


def test_metrics_render_expected_series_when_enabled() -> None:
    pytest.importorskip("prometheus_client")
    metrics.configure_metrics(True)
    try:
        metrics.set_queue_depth_provider(lambda: {"pending": 3, "running": 1})
        metrics.observe_job(2.0, "completed")
        metrics.record_retry()
        metrics.record_sandbox_kill("timeout")
        metrics.record_llm_cost(0.0)

        text = metrics.render_metrics()[0].decode()

        assert 'radius_queue_depth{status="pending"} 3.0' in text
        assert 'radius_job_duration_seconds_count{outcome="completed"} 1.0' in text
        assert "radius_job_retries_total 1.0" in text
        assert 'radius_sandbox_kills_total{reason="timeout"} 1.0' in text
        assert "radius_llm_cost_usd_total" in text
    finally:
        metrics.configure_metrics(False)


@pytest.mark.parametrize("bad", ["garbage", "00-xyz-abc-01", "", None])
def test_continue_trace_ignores_invalid_traceparent(bad) -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    assert configure_tracing(span_exporter=exporter) is True
    try:
        with continue_trace(bad), span("fresh"):
            pass
        (fresh,) = exporter.get_finished_spans()
        assert fresh.parent is None
    finally:
        reset_tracing()
