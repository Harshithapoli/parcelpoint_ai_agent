from datetime import timedelta
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.confirmation import (
    _RECORDS,
    confirm_action,
    reject_action,
    request_confirmation,
    reset_confirmation_registry,
)
from src.agent.graph import run_investigation
from src.agent.state import PendingAction
from src.data.database import initialize_database
from src.data.excel_loader import load_workbook
from src.security.auth import MOCK_USERS, User
from src.tools.schemas import Escalation
from langchain_core.messages import AIMessage


class FakeModel:
    def __init__(self, response):
        self.response = response

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self.response


@pytest.fixture(autouse=True)
def clean_registry():
    reset_confirmation_registry()
    yield
    reset_confirmation_registry()


@pytest.fixture
def database_path(tmp_path):
    path = tmp_path / "confirmation.db"
    initialize_database(path, load_workbook(WORKBOOK))
    return path


WORKBOOK = ROOT / "data" / "ParcelPilot_Assessment_Data.xlsx"


def make_pending(user_id="support_manager"):
    from datetime import datetime, timezone
    return PendingAction(
        action="create_escalation",
        ticket_id="TKT-502",
        reason="Bulk upload requires operational review",
        priority="high",
        requested_by=user_id,
        created_at=datetime.now(timezone.utc),
    )


def test_pending_action_gets_confirmation_id_and_required_status():
    result = request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    assert result["confirmation_id"] == "CONF-001"
    assert result["confirmation_required"] is True
    assert result["confirmation_status"] == "pending"
    assert result["pending_action"]["requested_by"] == "support_manager"


def test_agent_stops_with_pending_action_without_executing():
    response = AIMessage(
        content="",
        tool_calls=[{"name": "create_escalation", "args": {"ticket_id": "TKT-502", "reason": "Needs review", "priority": "high"}, "id": "call-1"}],
    )
    state = run_investigation("Escalate TKT-502", MOCK_USERS["support_manager"], FakeModel(response))
    assert state["confirmation_required"] is True
    assert state["confirmation_status"] == "pending"
    assert state["confirmation_id"]
    assert state["final_answer"]


def test_authorized_confirmation_executes_action(database_path):
    request = request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    result = confirm_action(request["confirmation_id"], MOCK_USERS["support_manager"], database_path)
    assert result["confirmation_status"] == "used"
    assert isinstance(result["action_result"], dict)
    assert result["action_result"]["escalation_id"] == "ESC-001"


def test_unauthorized_confirmation_does_not_modify_database(database_path):
    request = request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    restricted = User(user_id="other", role="reader", permissions=frozenset())
    result = confirm_action(request["confirmation_id"], restricted, database_path)
    assert result["error"] == "action_owner_mismatch"
    assert not database_path.exists() or "escalations" not in _table_names(database_path)


def test_rejection_does_not_create_escalation(database_path):
    request = request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    result = reject_action(request["confirmation_id"], MOCK_USERS["support_manager"])
    assert result["confirmation_status"] == "rejected"
    assert "escalations" not in _table_names(database_path)


def test_expired_confirmation_cannot_execute(database_path):
    request = request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    _RECORDS[request["confirmation_id"]]["created_at"] -= timedelta(minutes=16)
    result = confirm_action(request["confirmation_id"], MOCK_USERS["support_manager"], database_path)
    assert result["error"] == "confirmation_expired"
    assert "escalations" not in _table_names(database_path)


def test_confirmation_is_single_use(database_path):
    request = request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    confirmation_id = request["confirmation_id"]
    first = confirm_action(confirmation_id, MOCK_USERS["support_manager"], database_path)
    second = confirm_action(confirmation_id, MOCK_USERS["support_manager"], database_path)
    assert first["action_result"]["escalation_id"] == "ESC-001"
    assert second["error"] == "confirmation_already_used"
    assert _count(database_path, "escalations") == 1


def test_malformed_confirmation_id_is_controlled():
    result = confirm_action("not-a-confirmation", MOCK_USERS["support_manager"])
    assert result["error"] == "malformed_confirmation_id"


def test_audit_event_generated(caplog):
    with caplog.at_level("INFO", logger="parcelpilot.audit"):
        request_confirmation(make_pending(), MOCK_USERS["support_manager"])
    assert "confirmation_requested" in caplog.text
    assert "confirmation_id=CONF-001" in caplog.text


def test_normal_read_only_question_has_no_confirmation():
    state = run_investigation(
        "What happened to ORD-1001?",
        MOCK_USERS["support_agent"],
        FakeModel(AIMessage(content="Answer: Read-only investigation complete.")),
    )
    assert state.get("confirmation_required") is False
    assert state.get("pending_action") is None


def _table_names(path):
    import sqlite3
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _count(path, table):
    import sqlite3
    with sqlite3.connect(path) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
