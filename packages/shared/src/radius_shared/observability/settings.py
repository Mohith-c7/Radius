"""Opt-in observability settings (everything is disabled by default)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObservabilitySettings(BaseSettings):
    """Environment-driven switches for tracing and metrics."""

    tracing_enabled: bool = Field(default=False, alias="RADIUS_TRACING_ENABLED")
    otlp_endpoint: str = Field(default="", alias="RADIUS_OTLP_ENDPOINT")
    """OTLP/HTTP traces endpoint, e.g. ``http://localhost:4318/v1/traces``.

    Empty means spans are created but not exported anywhere.
    """
    service_name: str = Field(default="radius", alias="RADIUS_OTEL_SERVICE_NAME")
    metrics_enabled: bool = Field(default=False, alias="RADIUS_METRICS_ENABLED")
    worker_metrics_port: int = Field(default=0, alias="RADIUS_WORKER_METRICS_PORT")
    """Port for the worker's Prometheus endpoint; ``0`` disables it."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
