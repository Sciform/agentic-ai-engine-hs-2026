"""OpenTelemetry setup — exports traces to Google Cloud Trace via OTLP.

ADK already emits OTel spans following the GenAI semantic conventions
(``invoke_agent``, ``generate_content``, ``execute_tool``, ...) through the
global tracer provider, so installing a provider here is enough to capture the
full agent execution flow alongside FastAPI / httpx / requests HTTP spans.

Spans are exported with ADK's ``get_gcp_exporters`` helper, which sends them
over OTLP to ``telemetry.googleapis.com`` (the replacement for the deprecated
``CloudTraceSpanExporter``). This needs the Telemetry API enabled and
``roles/cloudtrace.agent`` (or ``roles/telemetry.tracesWriter``) on the
runtime service account.

Behaviour:
- On Cloud Run (``K_SERVICE`` set) — enabled by default, exports to Cloud Trace.
- Locally — disabled unless ``OTEL_ENABLED=true``.
- Force-disable anywhere with ``OTEL_ENABLED=false``.
"""

from __future__ import annotations

import os

import structlog
from fastapi import FastAPI

from app.config import GOOGLE_CLOUD_PROJECT, IS_CLOUD_RUN

logger = structlog.get_logger(__name__)

_initialised = False


def _enabled() -> bool:
    override = os.getenv("OTEL_ENABLED")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return IS_CLOUD_RUN


def configure_telemetry(app: FastAPI) -> None:
    """Install the Cloud Trace (OTLP) exporter and instrument the FastAPI app.

    Safe to call multiple times — only the first call has effect.
    """
    global _initialised
    if _initialised:
        return

    if not _enabled():
        logger.info("telemetry.disabled", reason="OTEL_ENABLED not set and not on Cloud Run")
        return

    try:
        import google.auth
        from google.adk.telemetry.google_cloud import get_gcp_exporters
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        logger.warning("telemetry.import_failed", error=str(exc))
        return

    service_name = os.getenv("K_SERVICE", "agentic-ai-engineering")
    sample_ratio = float(os.getenv("OTEL_TRACES_SAMPLER_RATIO", "1.0"))

    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        hooks = get_gcp_exporters(
            enable_cloud_tracing=True,
            google_auth=(credentials, GOOGLE_CLOUD_PROJECT),
        )
    except Exception as exc:  # no ADC credentials, etc.
        logger.warning("telemetry.exporter_failed", error=str(exc))
        return

    if not hooks.span_processors:
        logger.warning("telemetry.no_exporter", reason="OTLP exporter unavailable")
        return

    provider = TracerProvider(
        resource=Resource.create(
            {SERVICE_NAME: service_name, "gcp.project_id": GOOGLE_CLOUD_PROJECT}
        ),
        sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
    )
    for processor in hooks.span_processors:
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    RequestsInstrumentor().instrument()

    _initialised = True
    logger.info(
        "telemetry.enabled",
        exporter="otlp:telemetry.googleapis.com",
        project=GOOGLE_CLOUD_PROJECT,
        service=service_name,
        sample_ratio=sample_ratio,
    )
