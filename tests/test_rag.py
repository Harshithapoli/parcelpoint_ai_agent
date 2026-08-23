from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rag.chunking import chunk_pages
from src.rag.ingest import discover_pdf_documents, extract_document_pages, get_document_metadata
from src.rag.retriever import ingest_chunks, search_documents


DOCS_DIR = ROOT / "data" / "documents"


def test_all_six_pdfs_can_be_discovered():
    docs = discover_pdf_documents(DOCS_DIR)
    assert len(docs) == 6
    assert all(doc.suffix.lower() == ".pdf" for doc in docs)


def test_pdf_extraction_returns_text_and_page_metadata():
    extracted = extract_document_pages(DOCS_DIR)
    assert extracted
    assert all(page["text"] for page in extracted)
    assert all(page["page_number"] >= 1 for page in extracted)
    assert any(page["document"].startswith("01_") for page in extracted)


def test_document_metadata_is_detected():
    metadata = get_document_metadata(DOCS_DIR / "02_Support_Policy_v2_DEPRECATED.pdf")
    assert metadata["source_type"] == "deprecated_policy"
    assert metadata["status"] == "deprecated"
    assert metadata["authority"] == 1

    current_policy = get_document_metadata(DOCS_DIR / "01_Support_Policy_v3_CURRENT.pdf")
    assert current_policy["source_type"] == "current_policy"
    assert current_policy["status"] == "current"


def test_chunks_contain_document_metadata():
    extracted = extract_document_pages(DOCS_DIR)
    chunks = chunk_pages(extracted, chunk_size=500, overlap=120)
    assert chunks
    assert all("document" in chunk for chunk in chunks)
    assert all("page_number" in chunk for chunk in chunks)
    assert all("source_type" in chunk for chunk in chunks)
    assert all("account" in chunk for chunk in chunks)


def test_chromadb_ingestion_and_no_uncontrolled_duplicates(tmp_path):
    vector_dir = tmp_path / "vector_store"
    extracted = extract_document_pages(DOCS_DIR)
    chunks = chunk_pages(extracted, chunk_size=500, overlap=120)

    collection = ingest_chunks(chunks, persist_directory=vector_dir)
    first_count = collection.count()
    assert first_count > 0

    collection = ingest_chunks(chunks, persist_directory=vector_dir)
    second_count = collection.count()
    assert second_count == first_count


def test_search_documents_returns_results():
    results = search_documents("cancellation fee", top_k=3)
    assert results
    assert all("document" in result for result in results)
    assert all("page" in result for result in results)
    assert all("text" in result for result in results)


def test_search_filters_work():
    results = search_documents("Northstar cancellation", filters={"account": "Northstar Logistics"}, top_k=5)
    assert results
    assert all(result["account"] == "Northstar Logistics" for result in results)


def test_unknown_queries_are_handled_gracefully():
    results = search_documents("quantum lava lamp usage in handwritten shipping logs", top_k=5)
    assert results == [] or all(result["document"] for result in results)


def test_deprecated_documents_retains_deprecated_metadata():
    deprecated = get_document_metadata(DOCS_DIR / "02_Support_Policy_v2_DEPRECATED.pdf")
    assert deprecated["status"] == "deprecated"
    assert deprecated["source_type"] == "deprecated_policy"
