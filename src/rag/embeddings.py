"""Sentence Transformer embedding utilities for ParcelPilot document search."""

from __future__ import annotations

import os
from typing import Any

from sentence_transformers import SentenceTransformer


def get_embedding_model_name() -> str:
    """Read the configured embedding model name from environment, defaulting to a lightweight local option."""
    return os.getenv("PARCELPILOT_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def load_embedding_model(model_name: str | None = None) -> SentenceTransformer:
    """Load a local SentenceTransformer model for embeddings."""
    resolved_name = model_name or get_embedding_model_name()
    return SentenceTransformer(resolved_name)


def embed_texts(texts: list[str], model: SentenceTransformer | None = None) -> list[list[float]]:
    """Embed a list of strings into vectors."""
    if not texts:
        return []
    embedding_model = model or load_embedding_model()
    embeddings = embedding_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings.tolist()
