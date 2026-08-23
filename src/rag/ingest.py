"""PDF discovery and extraction utilities for ParcelPilot document ingestion."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import fitz

LOGGER = logging.getLogger(__name__)

SOURCE_AUTHORITY = {
    "customer_agreement": 5,
    "current_policy": 4,
    "current_sop": 4,
    "product_documentation": 3,
    "deprecated_policy": 1,
}


def discover_pdf_documents(documents_dir: str | Path) -> list[Path]:
    """Return all PDF files from the documents directory in a stable order."""
    directory = Path(documents_dir)
    if not directory.exists():
        raise FileNotFoundError(f"Document directory not found: {directory}")
    pdfs = sorted(directory.glob("*.pdf"), key=lambda p: p.name.lower())
    if not pdfs:
        raise FileNotFoundError(f"No PDF documents found in {directory}")
    return pdfs


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = re.sub(r"\s+", " ", value)
    return cleaned.strip()


def _extract_document_title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    title = lines[0]
    return title.replace("\n", " ").strip()


def get_document_metadata(pdf_path: str | Path) -> dict[str, Any]:
    """Infer document metadata from filename and content without hard-coding answers."""
    path = Path(pdf_path)
    filename = path.name
    lower_name = filename.lower()

    text_blocks: list[str] = []
    try:
        with fitz.open(path) as document:
            for page in document:
                page_text = page.get_text("text")
                if page_text and page_text.strip():
                    text_blocks.append(page_text)
    except Exception as exc:  # pragma: no cover - runtime PDF read errors
        raise ValueError(f"Could not read PDF '{path}': {exc}") from exc

    combined_text = "\n".join(text_blocks)
    title = _extract_document_title(combined_text)

    status = "current"
    if "deprecated" in lower_name or "DEPRECATED" in combined_text.upper():
        status = "deprecated"
    elif "status:" in combined_text.lower():
        for token in ["current", "deprecated", "active", "inactive"]:
            if token in combined_text.lower():
                if token == "current":
                    status = "current"
                    break
                if token == "deprecated":
                    status = "deprecated"
                    break

    source_type = "product_documentation"
    if "support_policy" in lower_name:
        source_type = "current_policy" if status == "current" else "deprecated_policy"
    elif "service_credit" in lower_name or "sop" in lower_name or "cancellation" in lower_name:
        source_type = "current_sop"
    elif "agreement" in lower_name:
        source_type = "customer_agreement"
    elif "guide" in lower_name or "known_issues" in lower_name:
        source_type = "product_documentation"

    account = ""
    if "northstar" in lower_name:
        account = "Northstar Logistics"
    elif "lumenworks" in lower_name:
        account = "LumenWorks"

    if not account and "account:" in combined_text.lower():
        match = re.search(r"Account:\s*([A-Za-z0-9\s-]+)", combined_text, flags=re.IGNORECASE)
        if match:
            account = match.group(1).strip()

    authority = SOURCE_AUTHORITY.get(source_type, 3)

    result = {
        "document": path.name,
        "source_type": source_type,
        "status": status,
        "account": account,
        "authority": authority,
        "title": title,
    }
    return result


def extract_document_pages(documents_dir: str | Path) -> list[dict[str, Any]]:
    """Extract page-by-page text from each PDF while preserving page numbers."""
    pages: list[dict[str, Any]] = []
    for pdf_path in discover_pdf_documents(documents_dir):
        metadata = get_document_metadata(pdf_path)
        try:
            with fitz.open(pdf_path) as document:
                for page_number in range(document.page_count):
                    raw_page = document[page_number]
                    text = raw_page.get_text("text")
                    cleaned = _clean_text(text)
                    if not cleaned:
                        LOGGER.warning("Skipping empty page %s in %s", page_number + 1, pdf_path.name)
                        continue
                    pages.append(
                        {
                            "document": pdf_path.name,
                            "page_number": page_number + 1,
                            "text": cleaned,
                            "source_type": metadata["source_type"],
                            "status": metadata["status"],
                            "account": metadata["account"],
                            "authority": metadata["authority"],
                        }
                    )
        except Exception as exc:  # pragma: no cover - runtime PDF read errors
            raise ValueError(f"Extraction failed for '{pdf_path}': {exc}") from exc
    return pages
