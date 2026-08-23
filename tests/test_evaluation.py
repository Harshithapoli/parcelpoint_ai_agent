from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.confirmation import confirm_action, request_confirmation, reset_confirmation_registry
from src.agent.graph import normalize_response_text, run_investigation
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.router import rank_sources_for_account
from src.agent.state import PendingAction
from src.data.database import initialize_database
from src.data.excel_loader import load_workbook
from src.security.auth import MOCK_USERS, User
from src.tools.data_lookup import lookup_order
from src.tools.monitoring import scan_operational_issues
from src.monitoring.detector import detect_issues
from src.rag.ingest import get_document_metadata


WORKBOOK = ROOT / "data" / "ParcelPilot_Assessment_Data.xlsx"


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self.responses.pop(0)


def call(name, args, identifier):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": identifier}])


def fresh_db(tmp_path):
    path = tmp_path / "evaluation.db"
    initialize_database(path, load_workbook(WORKBOOK))
    return path


def test_northstar_order_investigation_is_multi_step(tmp_path):
    model = FakeModel([
        call("lookup_order", {"order_id": "ORD-1001"}, "order"),
        call("search_documents", {"query": "Northstar cancellation fee"}, "agreement"),
        AIMessage(content="Northstar evidence was retrieved."),
    ])
    state = run_investigation("Can Northstar cancel ORD-1001 without a fee?", MOCK_USERS["support_manager"], model)
    assert [item["tool"] for item in state["tool_results"]] == ["lookup_order", "search_documents"]
    assert state["sources"]


def test_customer_agreement_precedes_general_sop_but_both_sources_remain():
    sources = [
        {"document": "sop.pdf", "source_type": "current_sop", "authority": 4, "account": ""},
        {"document": "agreement.pdf", "source_type": "customer_agreement", "authority": 5, "account": "Northstar Logistics"},
    ]
    ranked = rank_sources_for_account(sources, "Northstar Logistics")
    assert ranked[0]["document"] == "agreement.pdf"
    assert len(ranked) == 2


def test_current_policy_precedes_deprecated_policy():
    sources = [
        {"document": "deprecated.pdf", "source_type": "deprecated_policy", "authority": 1, "account": ""},
        {"document": "current.pdf", "source_type": "current_policy", "authority": 4, "account": ""},
    ]
    ranked = rank_sources_for_account(sources)
    assert ranked[0]["document"] == "current.pdf"
    assert get_document_metadata(ROOT / "data/documents/02_Support_Policy_v2_DEPRECATED.pdf")["status"] == "deprecated"


def test_historical_ticket_is_context_not_policy():
    assert "Historical ticket resolutions are context only" in SYSTEM_PROMPT
    assert "deprecated" in SYSTEM_PROMPT.lower()


def test_unauthorized_lookup_is_denied_before_sqlite(tmp_path):
    path = fresh_db(tmp_path)
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    with patch("src.tools.data_lookup.DatabaseManager.get_record_by_id") as query:
        result = lookup_order("ORD-1001", path, user=restricted)
    assert "Access denied" in result["error"]
    query.assert_not_called()


def test_unauthorized_escalation_is_denied_without_mutation(tmp_path):
    path = fresh_db(tmp_path)
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    from src.tools.actions import create_escalation
    with patch("src.tools.actions.DatabaseManager._connect") as connect:
        result = create_escalation("TKT-502", "Review required", "high", path, user=restricted)
    assert "Access denied" in result["error"]
    connect.assert_not_called()


def test_escalation_request_is_pending_and_not_executed():
    reset_confirmation_registry()
    model = FakeModel([call("create_escalation", {"ticket_id": "TKT-502", "reason": "Review", "priority": "high"}, "action")])
    with patch("src.agent.graph.create_escalation") as action:
        state = run_investigation("Escalate TKT-502", MOCK_USERS["support_manager"], model)
    action.assert_not_called()
    assert state["confirmation_required"] is True
    assert state["confirmation_id"].startswith("CONF-")


def test_confirmation_executes_exactly_once(tmp_path):
    reset_confirmation_registry()
    pending = PendingAction(action="create_escalation", ticket_id="TKT-502", reason="Review", priority="high", requested_by="support_manager", created_at=datetime.now(timezone.utc))
    request = request_confirmation(pending, MOCK_USERS["support_manager"])
    first = confirm_action(request["confirmation_id"], MOCK_USERS["support_manager"], fresh_db(tmp_path))
    second = confirm_action(request["confirmation_id"], MOCK_USERS["support_manager"], fresh_db(tmp_path))
    assert first["action_result"]["escalation_id"] == "ESC-001"
    assert second["error"] == "confirmation_already_used"


def test_monitoring_scan_is_read_only(tmp_path):
    path = fresh_db(tmp_path)
    before = detect_issues(path)
    result = scan_operational_issues(user=MOCK_USERS["support_agent"], db_path=path)
    after = detect_issues(path)
    assert result
    assert [item.issue_id for item in before] == [item["issue_id"] for item in result]
    assert [item.issue_id for item in after] == [item.issue_id for item in before]


def test_unsupported_question_is_handled_as_model_response():
    model = FakeModel([AIMessage(content="I do not have enough ParcelPilot data to answer that safely.")])
    state = run_investigation("What is the weather on Mars?", MOCK_USERS["support_agent"], model)
    assert "do not have enough" in state["final_answer"]
    assert state["confirmation_required"] is False


def test_gemini_content_blocks_render_as_clean_text():
    content = [{"type": "text", "text": "ParcelPilot answer."}, {"type": "metadata", "signature": "hidden"}]
    assert normalize_response_text(content) == "ParcelPilot answer."
