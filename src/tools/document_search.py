"""Controlled document-search tool backed by the existing RAG retriever."""

from __future__ import annotations

import logging
from typing import Any

from src.rag.retriever import search_documents as rag_search_documents
from src.security.auth import User
from src.security.permissions import AuthorizationError, check_permission
from src.tools.schemas import DocumentSearchResult

LOGGER = logging.getLogger(__name__)


def search_documents(
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 5,
    user: User | None = None,
) -> list[DocumentSearchResult] | dict[str, str]:
    """Retrieve document evidence without applying source precedence."""
    try:
        check_permission(user, "search_documents", "search_documents")
    except (AuthorizationError, ValueError) as exc:
        return {"error": str(exc)}
    if not isinstance(query, str) or not query.strip():
        return {"error": "Search query must be a non-empty string."}
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        return {"error": "top_k must be a positive integer."}
    if filters is not None and not isinstance(filters, dict):
        return {"error": "filters must be a dictionary when provided."}

    allowed_filters = {"account", "source_type", "status"}
    if filters and any(key not in allowed_filters for key in filters):
        return {"error": "Unsupported document filter. Use account, source_type, or status."}

    try:
        raw_results = rag_search_documents(query.strip(), filters=filters, top_k=top_k)
        return [DocumentSearchResult.model_validate(result) for result in raw_results]
    except Exception as exc:  # pragma: no cover - backend-specific errors
        LOGGER.exception("Document search failed")
        return {"error": f"Document search failed: {exc}"}
