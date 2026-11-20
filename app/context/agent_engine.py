"""Shared Agent Runtime provider – resolves or creates the Agent Runtime ID.

Both the session handler and the memory bank handler require an
``agent_engine_id`` backed by Agent Platform Agent Runtime (formerly
Vertex AI Agent Engine).  This module centralises that resolution so it
only happens once per process.

Uses the ``agentplatform`` client (``client.runtimes``), which replaces the
deprecated ``vertexai.agent_engines`` module.
"""

from __future__ import annotations

import threading

import agentplatform
import structlog

from app import config

logger = structlog.get_logger(__name__)

_DISPLAY_NAME = "agentic-ai-engineering-memory"

# Cached value – populated on first call to ``get_agent_engine_id()``.
_cached_id: str | None = None
_lock = threading.Lock()


def _memory_bank_context_spec() -> dict:
    """Memory Bank config pinning the generation and embedding models.

    Pinning them explicitly keeps Memory Bank in ``MEMORY_BANK_LOCATION`` and
    avoids server-side defaults that may be retired or not served there.
    """
    location = config.MEMORY_BANK_LOCATION
    return {
        "memory_bank_config": {
            "generation_config": {
                "model": config.publisher_model(config.DEFAULT_LLM_MODEL, location),
            },
            "similarity_search_config": {
                "embedding_model": config.publisher_model(
                    config.EMBEDDING_MODEL, config.EMBEDDING_LOCATION
                ),
            },
        },
    }


def get_agent_engine_id() -> str:
    """Return the Agent Runtime ID, creating a bare runtime if needed.

    The runtime lives in ``MEMORY_BANK_LOCATION``.  The result is cached for
    the lifetime of the process.

    Raises:
        RuntimeError: If the Agent Platform backend is disabled
            (``GOOGLE_GENAI_USE_ENTERPRISE=FALSE``).
    """
    global _cached_id
    if _cached_id is not None:
        return _cached_id

    with _lock:
        if _cached_id is not None:
            return _cached_id

        if config.AGENT_ENGINE_ID:
            logger.info("Using configured Agent Runtime ID", agent_engine_id=config.AGENT_ENGINE_ID)
            _cached_id = config.AGENT_ENGINE_ID
            return _cached_id

        if not config.USE_ENTERPRISE:
            raise RuntimeError("Agent Runtime requires GOOGLE_GENAI_USE_ENTERPRISE=TRUE")

        client = agentplatform.Client(
            project=config.GOOGLE_CLOUD_PROJECT,
            location=config.MEMORY_BANK_LOCATION,
        )

        # Search for an existing runtime with our display name
        for runtime in client.runtimes.list(config={"filter": f'display_name="{_DISPLAY_NAME}"'}):
            resource_name = runtime.api_resource.name
            logger.info(
                "Found existing Agent Runtime",
                agent_engine_id=resource_name.rsplit("/", 1)[-1],
                resource_name=resource_name,
            )
            _cached_id = resource_name.rsplit("/", 1)[-1]
            return _cached_id

        # None found – create a bare runtime (no deployed code) with Memory Bank configured
        logger.info(
            "No Agent Runtime found, creating a new one",
            display_name=_DISPLAY_NAME,
            location=config.MEMORY_BANK_LOCATION,
        )
        runtime = client.runtimes.create(
            config={
                "display_name": _DISPLAY_NAME,
                "context_spec": _memory_bank_context_spec(),
            },
        )
        resource_name = runtime.api_resource.name
        logger.info("Created Agent Runtime", resource_name=resource_name)
        _cached_id = resource_name.rsplit("/", 1)[-1]
        return _cached_id
