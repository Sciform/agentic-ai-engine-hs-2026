"""Application configuration and structured logging setup."""

import logging
import os

import structlog

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------
# Cloud Run sets K_SERVICE automatically; if present we are running in the cloud.
IS_CLOUD_RUN: bool = "K_SERVICE" in os.environ

# Only load .env file for local development
if not IS_CLOUD_RUN:
    from dotenv import load_dotenv
    load_dotenv()


# ---------------------------------------------------------------------------
# Application settings
# ---------------------------------------------------------------------------

USER_ID = "user-12345"  # In a real application, this would be dynamic and based on the authenticated user

# Automatically set to "gcp" on Cloud Run, "console" locally
LOG_ENV: str = "gcp" if IS_CLOUD_RUN else "console"

# Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# ---------------------------------------------------------------------------
# Google Cloud Platform settings (from env vars)
# ---------------------------------------------------------------------------

GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "agentic-ai-eng-489113")
# Region for Gemini, RAG Engine, Sessions and Memory Bank. europe-west3 (Frankfurt)
# offers all of them (RAG Engine GA) in one EU region.
GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "europe-west3")
GOOGLE_CLOUD_STORAGE_BUCKET: str = os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET", "agentic-ai-eng-bucket-ew3")

# Default agent to use when a connection starts
DEFAULT_AGENT_ID: str = os.getenv("DEFAULT_AGENT_ID", "greeting_agent")

# Default LLM model for agents (must be served in GOOGLE_CLOUD_LOCATION;
# gemini-3.5-flash is the newest Flash available in europe-west3).
DEFAULT_LLM_MODEL: str = os.getenv("DEFAULT_LLM_MODEL", "gemini-3.5-flash")

# Embedding model for Memory Bank similarity search. gemini-embedding-2 is not served
# in single EU regions, only via the "eu" multi-region endpoint (processing stays in the EU).
# Only applied when the Agent Runtime is created — an existing one keeps its model.
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
EMBEDDING_LOCATION: str = os.getenv("EMBEDDING_LOCATION", "eu")

# Embedding model for the RAG corpus. RAG Engine does not accept Gemini embedding
# models yet and requires the model in the corpus region; text-embedding-005 is the
# newest it supports (use text-multilingual-embedding-002 for non-English documents).
# Only applied when a corpus is created — an existing corpus keeps its model.
RAG_EMBEDDING_MODEL: str = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-005")

# Agent Platform Agent Runtime (formerly Vertex AI Agent Engine) ID (required for
# Sessions and Memory Bank). Auto-created on first start if empty.
AGENT_ENGINE_ID: str = os.getenv("AGENT_ENGINE_ID", "")

# Region for Agent Runtime (Sessions + Memory Bank). Defaults to GOOGLE_CLOUD_LOCATION.
MEMORY_BANK_LOCATION: str = os.getenv("MEMORY_BANK_LOCATION", GOOGLE_CLOUD_LOCATION)

# Session backend: "VERTEX" for VertexAiSessionService, "IN_MEMORY" for InMemorySessionService.
# Defaults to "IN_MEMORY" locally, "VERTEX" on Cloud Run.
SESSION_BACKEND: str = os.getenv("SESSION_BACKEND", "VERTEX" if IS_CLOUD_RUN else "IN_MEMORY")

# Agent Platform RAG Engine corpus resource name (auto-created if empty).
# Format: projects/{project}/locations/{location}/ragCorpora/{id}
RAG_CORPUS: str = os.getenv("RAG_CORPUS", "")


# ---------------------------------------------------------------------------
# Gemini Enterprise Agent Platform initialization (formerly Vertex AI)
# ---------------------------------------------------------------------------

# FALSE when running outside GCP (e.g. Hugging Face Spaces) with the Google AI
# API key backend; Agent Runtime, Memory Bank and RAG Engine are then disabled.
# GOOGLE_GENAI_USE_ENTERPRISE replaces the deprecated GOOGLE_GENAI_USE_VERTEXAI;
# the old name is still honoured as a fallback.
USE_ENTERPRISE: bool = os.getenv(
    "GOOGLE_GENAI_USE_ENTERPRISE", os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
).upper() == "TRUE"


def publisher_model(model: str, location: str | None = None) -> str:
    """Return the full publisher-model resource name for *model*."""
    return (
        f"projects/{GOOGLE_CLOUD_PROJECT}/locations/{location or GOOGLE_CLOUD_LOCATION}"
        f"/publishers/google/models/{model}"
    )

# ---------------------------------------------------------------------------
# Structlog configuration
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """Configure structlog for either local console or GCP Cloud Logging.

    Call this once at application startup (e.g. in main.py / entrypoint).

    LOG_ENV="console"  → coloured, human-readable dev output
    LOG_ENV="gcp"      → JSON lines compatible with GCP Cloud Logging
    """
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    # Shared processors applied to every log event
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _inject_otel_trace_context,
    ]

    if LOG_ENV == "gcp":
        # GCP Cloud Logging expects JSON with specific field names.
        # "severity" is mapped from the log level by the GCP processor.
        shared_processors += [
            # Rename "level" → "severity" for Cloud Logging
            _rename_level_to_severity,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Local / console development output
        shared_processors += [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libraries respect the level
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )


def _rename_level_to_severity(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Rename ``level`` to ``severity`` for GCP Cloud Logging compatibility."""
    level = event_dict.pop("level", method_name)
    event_dict["severity"] = level.upper()
    return event_dict


def _inject_otel_trace_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Attach the active OTel trace/span IDs in Cloud Logging's expected format.

    Cloud Logging shows a "View trace" link on entries that include
    ``logging.googleapis.com/trace`` and ``logging.googleapis.com/spanId``.
    """
    try:
        from opentelemetry import trace as _trace
    except ImportError:
        return event_dict

    span = _trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if not ctx or not ctx.is_valid:
        return event_dict

    trace_id = format(ctx.trace_id, "032x")
    span_id = format(ctx.span_id, "016x")
    event_dict["logging.googleapis.com/trace"] = (
        f"projects/{GOOGLE_CLOUD_PROJECT}/traces/{trace_id}"
    )
    event_dict["logging.googleapis.com/spanId"] = span_id
    event_dict["logging.googleapis.com/trace_sampled"] = bool(ctx.trace_flags.sampled)
    return event_dict