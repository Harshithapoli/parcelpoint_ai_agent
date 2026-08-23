from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.database import initialize_database
from src.data.excel_loader import load_workbook
from src.rag.retriever import ingest_documents
from src.security.auth import MOCK_USERS, User
from src.tools.actions import create_escalation
from src.tools.data_lookup import lookup_account, lookup_order, lookup_ticket
from src.tools.document_search import search_documents


WORKBOOK = ROOT / "data" / "ParcelPilot_Assessment_Data.xlsx"
DOCUMENTS = ROOT / "data" / "documents"


@pytest.fixture
def database_path(tmp_path):
    path = tmp_path / "permissions.db"
    initialize_database(path, load_workbook(WORKBOOK))
    return path


@pytest.fixture(autouse=True)
def vector_store():
    ingest_documents(DOCUMENTS)


def test_authorized_document_search():
    result = search_documents("Northstar cancellation", user=MOCK_USERS["support_agent"])
    assert isinstance(result, list)
    assert result


def test_unauthorized_document_search_does_not_call_chroma():
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    with patch("src.tools.document_search.rag_search_documents") as search:
        result = search_documents("cancellation", user=restricted)
    assert "Access denied" in result["error"]
    search.assert_not_called()


@pytest.mark.parametrize(
    "function, identifier, permission",
    [
        (lookup_account, "ACCT-001", "lookup_account"),
        (lookup_order, "ORD-1001", "lookup_order"),
        (lookup_ticket, "TKT-502", "lookup_ticket"),
    ],
)
def test_authorized_structured_lookups(function, identifier, permission, database_path):
    result = function(identifier, database_path, user=MOCK_USERS["support_agent"])
    assert "error" not in result if isinstance(result, dict) and permission != "lookup_order" else result


def test_unauthorized_lookups_do_not_query_sqlite(database_path):
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    with patch("src.tools.data_lookup.DatabaseManager.get_record_by_id") as lookup:
        account = lookup_account("ACCT-001", database_path, user=restricted)
        order = lookup_order("ORD-1001", database_path, user=restricted)
        ticket = lookup_ticket("TKT-502", database_path, user=restricted)
    assert all("Access denied" in item["error"] for item in (account, order, ticket))
    lookup.assert_not_called()


def test_authorized_escalation(database_path):
    result = create_escalation(
        "TKT-502", "Requires operational review", "high", database_path, user=MOCK_USERS["support_manager"]
    )
    assert result.escalation_id == "ESC-001"
    assert result.created_by == "support_manager"


def test_unauthorized_escalation_does_not_modify_database(database_path):
    restricted = MOCK_USERS["support_agent"]
    with patch("src.tools.actions.DatabaseManager._connect") as connect:
        result = create_escalation("TKT-502", "Requires review", "high", database_path, user=restricted)
    assert "Access denied" in result["error"]
    connect.assert_not_called()


def test_permission_audit_events_are_emitted(caplog):
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    with caplog.at_level("INFO", logger="parcelpilot.audit"):
        search_documents("cancellation", user=restricted)
    assert "user_id=reader" in caplog.text
    assert "allowed=False" in caplog.text
