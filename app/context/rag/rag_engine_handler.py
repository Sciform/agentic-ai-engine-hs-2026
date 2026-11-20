"""RAG engine handler – manages an Agent Platform RAG corpus for document retrieval.

Auto-provisions a RAG corpus on first use if ``RAG_CORPUS`` is not set.
Provides helpers for importing files and listing documents.

Uses the ``agentplatform`` client (``client.rag``), which replaces the
deprecated ``vertexai.preview.rag`` module.
"""

from __future__ import annotations

import asyncio
import threading
from functools import cache

import agentplatform
import structlog
from agentplatform import types
from google.genai import types as genai_types

from app import config

logger = structlog.get_logger(__name__)

_DISPLAY_NAME = "agentic-ai-engineering-rag"


@cache
def _rag():
    """Return the RAG API module bound to ``GOOGLE_CLOUD_LOCATION`` (RAG Engine is regional)."""
    client = agentplatform.Client(
        project=config.GOOGLE_CLOUD_PROJECT,
        location=config.GOOGLE_CLOUD_LOCATION,
    )
    return client.rag


def _get_or_create_corpus() -> str | None:
    """Return the RAG corpus resource name, creating one if needed.

    Returns ``None`` if corpus creation fails.
    """
    if config.RAG_CORPUS:
        logger.info("Using configured RAG corpus", rag_corpus=config.RAG_CORPUS)
        return config.RAG_CORPUS

    if not config.USE_ENTERPRISE:
        logger.info("RAG disabled (GOOGLE_GENAI_USE_ENTERPRISE=FALSE)")
        return None

    try:
        rag = _rag()
        # Look for an existing corpus with our display name (paginated).
        page_token = None
        while True:
            page = rag.list_corpora(config=types.ListRagCorporaConfig(page_token=page_token))
            for corpus in page.rag_corpora or []:
                if corpus.display_name == _DISPLAY_NAME:
                    logger.info(
                        "Found existing RAG corpus",
                        corpus_name=corpus.name,
                        display_name=corpus.display_name,
                    )
                    return corpus.name
            page_token = page.next_page_token
            if not page_token:
                break

        # Create a new corpus
        logger.info("No RAG corpus found, creating a new one", display_name=_DISPLAY_NAME)
        corpus = rag.create_corpus(
            rag_corpus=types.RagCorpus(
                display_name=_DISPLAY_NAME,
                vector_db_config=types.RagVectorDbConfig(
                    rag_embedding_model_config=types.RagEmbeddingModelConfig(
                        vertex_prediction_endpoint=types.RagEmbeddingModelConfigVertexPredictionEndpoint(
                            endpoint=config.publisher_model(config.RAG_EMBEDDING_MODEL),
                        ),
                    ),
                ),
            ),
        )
        logger.info("Created RAG corpus", corpus_name=corpus.name)
        return corpus.name
    except Exception:
        logger.warning("RAG corpus unavailable - running without RAG", exc_info=True)
        return None


class RagEngineHandler:
    """Provides a configured RAG corpus for document retrieval.

    Initialisation is lazy and best-effort: the first access to
    ``corpus_name`` or ``available`` triggers corpus provisioning.
    If the corpus cannot be created, ``corpus_name`` stays ``None``
    and the RAG agent is not available.
    """

    def __init__(self) -> None:
        self._corpus_name: str | None = None
        self._initialized = False
        self._lock = threading.Lock()

    def _ensure_initialized(self) -> None:
        """Lazy-init: provision the corpus on first access (thread-safe)."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:          # double-check after acquiring lock
                return
            try:
                self._corpus_name = _get_or_create_corpus()
            except Exception:
                logger.warning("RAG engine init failed", exc_info=True)
            self._initialized = True

    @property
    def corpus_name(self) -> str | None:
        """Full resource name of the RAG corpus, or ``None``."""
        self._ensure_initialized()
        return self._corpus_name

    @property
    def available(self) -> bool:
        self._ensure_initialized()
        return self._corpus_name is not None

    def _import_files_sync(self, gcs_uris: list[str]) -> dict:
        """Synchronous implementation of file import."""
        response = _rag().import_files(
            name=self._corpus_name,
            import_config=types.ImportRagFilesConfig(
                gcs_source=genai_types.GcsSource(uris=gcs_uris),
                rag_file_transformation_config=types.RagFileTransformationConfig(
                    rag_file_chunking_config=types.RagFileChunkingConfig(
                        fixed_length_chunking=types.RagFileChunkingConfigFixedLengthChunking(
                            chunk_size=1024,
                            chunk_overlap=200,
                        ),
                    ),
                ),
            ),
        )
        imported = response.imported_rag_files_count or 0
        logger.info(
            "Files imported into RAG corpus",
            corpus=self._corpus_name,
            imported=imported,
            failed=response.failed_rag_files_count or 0,
        )
        return {
            "status": "ok",
            "imported_count": imported,
        }

    async def import_files(self, gcs_uris: list[str]) -> dict:
        """Import files from GCS URIs into the corpus.

        Args:
            gcs_uris: List of ``gs://bucket/path`` URIs. The bucket must
                belong to ``GOOGLE_CLOUD_PROJECT``.

        Returns:
            A summary dict with status and imported count.
        """
        if not self.available:
            return {"status": "error", "message": "RAG corpus not available"}
        try:
            return await asyncio.to_thread(self._import_files_sync, gcs_uris)
        except Exception as e:
            logger.error("Failed to import files", error=str(e))
            return {"status": "error", "message": str(e)}

    def _list_files_sync(self) -> list[dict]:
        """Synchronous implementation of file listing (paginated)."""
        rag = _rag()
        files: list[dict] = []
        page_token = None
        while True:
            page = rag.list_files(
                name=self._corpus_name,
                config=types.ListRagFilesConfig(page_token=page_token),
            )
            files.extend(
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "size_bytes": f.size_bytes,
                }
                for f in page.rag_files or []
            )
            page_token = page.next_page_token
            if not page_token:
                return files

    async def list_files(self) -> list[dict]:
        """List files currently in the corpus."""
        if not self.available:
            return []
        try:
            return await asyncio.to_thread(self._list_files_sync)
        except Exception as e:
            logger.error("Failed to list RAG files", error=str(e))
            return []

    def _delete_file_sync(self, file_name: str) -> dict:
        """Synchronous implementation of file deletion."""
        _rag().delete_file(name=file_name)
        logger.info("Deleted RAG file", file_name=file_name)
        return {"status": "ok"}

    async def delete_file(self, file_name: str) -> dict:
        """Delete a file from the corpus by resource name."""
        if not self.available:
            return {"status": "error", "message": "RAG corpus not available"}
        try:
            return await asyncio.to_thread(self._delete_file_sync, file_name)
        except Exception as e:
            logger.error("Failed to delete RAG file", error=str(e))
            return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

rag_engine_handler = RagEngineHandler()
