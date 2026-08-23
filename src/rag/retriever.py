"""Persistent ChromaDB-backed document retrieval for ParcelPilot."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import chromadb

from src.config import settings
from src.rag.chunking import chunk_pages
from src.rag.embeddings import embed_texts, get_embedding_model_name, load_embedding_model
from src.rag.ingest import extract_document_pages

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOGGER = logging.getLogger(__name__)


def _get_persist_directory() -> Path:
    base = Path(settings.chroma_persist_directory)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_client(persist_directory: str | Path | None = None) -> chromadb.PersistentClient:
    directory = Path(persist_directory) if persist_directory else _get_persist_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(directory))


def _stable_chunk_id(chunk: dict[str, Any], index: int) -> str:
    payload = f"{chunk.get('document', 'unknown')}|{chunk.get('page_number', 0)}|{index}|{chunk.get('text', '')}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def ingest_chunks(
    chunks: list[dict[str, Any]],
    persist_directory: str | Path | None = None,
) -> Any:
    """Insert chunks into ChromaDB without uncontrolled duplicates."""
    client = _get_client(persist_directory)
    collection_name = "parcelpilot_documents"
    collection = client.get_or_create_collection(name=collection_name)

    if not chunks:
        return collection

    texts = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(texts, model=load_embedding_model(get_embedding_model_name()))

    ids = []
    existing_ids = set()
    for idx, chunk in enumerate(chunks):
        chunk_id = _stable_chunk_id(chunk, idx)
        ids.append(chunk_id)
        existing_ids.add(chunk_id)

    existing = collection.get(ids=list(existing_ids), include=[])
    missing_ids = [chunk_id for chunk_id in ids if chunk_id not in set(existing.get('ids', []))]
    if not missing_ids:
        return collection

    missing_indices = [idx for idx, chunk_id in enumerate(ids) if chunk_id in missing_ids]
    collection.add(
        ids=[ids[idx] for idx in missing_indices],
        embeddings=[embeddings[idx] for idx in missing_indices],
        documents=[texts[idx] for idx in missing_indices],
        metadatas=[
            {
                "document": chunks[idx].get("document"),
                "page": chunks[idx].get("page_number"),
                "source_type": chunks[idx].get("source_type"),
                "status": chunks[idx].get("status"),
                "account": chunks[idx].get("account"),
                "authority": chunks[idx].get("authority"),
            }
            for idx in missing_indices
        ],
    )
    return collection


def ingest_documents(documents_dir: str | Path, persist_directory: str | Path | None = None) -> Any:
    """Extract all PDFs and store their chunks in ChromaDB."""
    extracted_pages = extract_document_pages(documents_dir)
    chunks = chunk_pages(extracted_pages, chunk_size=500, overlap=120)
    return ingest_chunks(chunks, persist_directory=persist_directory)


def _ensure_collection_loaded(persist_directory: str | Path | None = None) -> Any:
    client = _get_client(persist_directory)
    collection = client.get_or_create_collection(name="parcelpilot_documents")
    if collection.count() == 0:
        default_docs = PROJECT_ROOT / "data" / "documents"
        if default_docs.exists():
            ingest_documents(default_docs, persist_directory=persist_directory)
            collection = client.get_or_create_collection(name="parcelpilot_documents")
    return collection


def search_documents(
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 5,
    persist_directory: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Search the vector store and return structured retrieval results."""
    if not query or not isinstance(query, str):
        return []

    client = _get_client(persist_directory)
    collection = _ensure_collection_loaded(persist_directory)
    if collection.count() == 0:
        return []

    where: dict[str, Any] | None = None
    if filters:
        cleaned_filters: dict[str, Any] = {}
        for key, value in filters.items():
            if key in {"account", "source_type", "status"} and value not in (None, ""):
                cleaned_filters[key] = str(value)
        where = cleaned_filters or None

    query_embedding = embed_texts([query], model=load_embedding_model(get_embedding_model_name()))[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
    )

    hits: list[dict[str, Any]] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for document_text, metadata, distance in zip(docs, metas, distances):
        hits.append(
            {
                "document": metadata.get("document"),
                "page": metadata.get("page"),
                "text": document_text,
                "source_type": metadata.get("source_type"),
                "status": metadata.get("status"),
                "account": metadata.get("account"),
                "authority": metadata.get("authority"),
                "distance": distance,
            }
        )
    return hits
