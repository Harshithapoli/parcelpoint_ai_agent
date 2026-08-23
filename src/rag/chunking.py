"""Deterministic chunking for ParcelPilot PDF text."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def chunk_pages(
    extracted_pages: list[dict[str, Any]],
    chunk_size: int = 500,
    overlap: int = 120,
) -> list[dict[str, Any]]:
    """Create page-aware chunks with overlap and stable metadata."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[dict[str, Any]] = []
    for page in extracted_pages:
        text = _normalize_text(page.get("text", ""))
        if not text:
            continue

        start = 0
        step = max(1, chunk_size - overlap)
        while start < len(text):
            end = min(start + chunk_size, len(text))
            window = text[start:end].strip()
            if len(window.split()) < 20:
                if start == 0 and end >= len(text):
                    pass
                else:
                    if chunks and not chunks[-1]["text"].endswith(window):
                        chunks[-1]["text"] = (chunks[-1]["text"] + " " + window).strip()
                    start = end
                    continue
            chunk = {
                "document": page.get("document"),
                "page_number": page.get("page_number"),
                "text": window,
                "source_type": page.get("source_type"),
                "status": page.get("status"),
                "account": page.get("account"),
                "authority": page.get("authority"),
            }
            chunks.append(chunk)
            if end >= len(text):
                break
            start += step

    LOGGER.info("Generated %s chunks from %s pages", len(chunks), len(extracted_pages))
    return chunks
