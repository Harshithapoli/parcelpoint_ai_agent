from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.database import initialize_database
from src.data.excel_loader import load_workbook
from src.rag.retriever import ingest_documents
from src.tools.actions import create_escalation
from src.tools.data_lookup import lookup_account, lookup_order, lookup_ticket
from src.tools.document_search import search_documents
from src.tools.schemas import Account, DocumentSearchResult, Escalation, Order, Ticket


WORKBOOK = ROOT / "data" / "ParcelPilot_Assessment_Data.xlsx"
DOCUMENTS = ROOT / "data" / "documents"


@pytest.fixture
def database_path(tmp_path):
    db_path = tmp_path / "tools.db"
    initialize_database(db_path, load_workbook(WORKBOOK))
    return db_path


@pytest.fixture(autouse=True)
def ensure_default_vector_store():
    ingest_documents(DOCUMENTS)


def test_document_search_returns_relevant_results_and_metadata():
    results = search_documents("Northstar cancellation", top_k=5)

    assert isinstance(results, list)
    assert results
    assert all(isinstance(result, DocumentSearchResult) for result in results)
    assert all(result.document and result.page >= 1 for result in results)
    assert all(result.source_type and result.status for result in results)
    assert all(result.authority >= 1 for result in results)


def test_northstar_search_returns_agreement_without_precedence_decision():
    results = search_documents("Northstar cancellation fee", top_k=5)
    documents = {result.document for result in results}

    assert "05_Northstar_Logistics_Enterprise_Agreement.pdf" in documents
    assert any(result.source_type == "current_sop" for result in results)


def test_document_search_validation_does_not_accept_arbitrary_filters():
    result = search_documents("cancellation", filters={"sql": "DROP TABLE tickets"})
    assert result["error"]


def test_structured_account_lookup_works(database_path):
    result = lookup_account("ACCT-001", database_path)
    assert isinstance(result, Account)
    assert result.account_name == "Northstar Logistics"


def test_structured_order_lookup_includes_related_account(database_path):
    result = lookup_order("ORD-1001", database_path)
    assert isinstance(result, dict)
    assert isinstance(result["order"], Order)
    assert isinstance(result["account"], Account)
    assert result["order"].account_id == result["account"].account_id


def test_structured_ticket_lookup_works(database_path):
    result = lookup_ticket("TKT-502", database_path)
    assert isinstance(result, Ticket)
    assert result.subject == "Bulk upload fails for 4,200-row CSV"


@pytest.mark.parametrize(
    "lookup, identifier",
    [(lookup_account, "ACCT-999"), (lookup_order, "ORD-999"), (lookup_ticket, "TKT-999")],
)
def test_unknown_records_are_controlled(lookup, identifier, database_path):
    result = lookup(identifier, database_path)
    assert isinstance(result, dict)
    assert "error" in result


def test_escalation_table_is_created_and_action_works(database_path):
    result = create_escalation(
        "TKT-502",
        "Bulk upload remains blocked after investigation.",
        "high",
        database_path,
    )

    assert isinstance(result, Escalation)
    assert result.escalation_id == "ESC-001"
    assert result.status == "open"
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'escalations'"
        ).fetchone()
    assert table == ("escalations",)


def test_invalid_priority_and_empty_reason_are_rejected(database_path):
    invalid_priority = create_escalation("TKT-502", "Needs review", "urgent", database_path)
    empty_reason = create_escalation("TKT-502", "   ", "high", database_path)

    assert invalid_priority["error"]
    assert empty_reason["error"]


def test_action_rejects_unknown_ticket(database_path):
    result = create_escalation("TKT-999", "Needs review", "high", database_path)
    assert result["error"]
