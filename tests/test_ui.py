from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.confirmation import reset_confirmation_registry
from src.agent.state import PendingAction
from src.security.auth import MOCK_USERS, User
from src.ui.integration import (
    available_users,
    confirm_pending,
    confirmation_details,
    get_user,
    reject_pending,
    scan_issues,
    start_investigation,
    user_changed,
    prepare_issue_escalation,
)
from src.agent.graph import normalize_response_text


def pending_state(status="pending"):
    return {
        "confirmation_required": status == "pending",
        "confirmation_status": status,
        "confirmation_id": "CONF-001",
        "pending_action": PendingAction(
            action="create_escalation",
            ticket_id="TKT-502",
            reason="Needs review",
            priority="high",
            requested_by="support_manager",
            created_at=datetime.now(timezone.utc),
        ),
    }


def test_user_selection_comes_from_mock_users_and_permissions_are_immutable():
    users = available_users()
    assert {user.user_id for user in users} == {"support_agent", "support_manager", "admin"}
    user = get_user("support_agent")
    assert user == MOCK_USERS["support_agent"]
    assert user.permissions == MOCK_USERS["support_agent"].permissions
    assert user.model_config.get("frozen") is True


def test_user_change_detection_supports_clearing_stale_state():
    assert user_changed("support_agent", "admin") is True
    assert user_changed("support_agent", "support_agent") is False


def test_pending_action_has_display_ready_details():
    details = confirmation_details(pending_state())
    assert details["action"] == "create_escalation"
    assert details["ticket_id"] == "TKT-502"
    assert details["confirmation_id"] == "CONF-001"
    assert confirmation_details(pending_state("used")) is None


def test_normal_text_response_extraction():
    assert normalize_response_text("  Direct support answer.  ") == "Direct support answer."


def test_langchain_content_block_response_extraction():
    content = [{"type": "text", "text": "Direct answer."}, {"type": "metadata", "value": "hidden"}]
    assert normalize_response_text(content) == "Direct answer."


def test_concise_final_response_and_evidence_remain_separate():
    answer = "Yes. The order is still BOOKED and has not been picked up."
    evidence = [{"document": "agreement.pdf", "page": 1, "text": "Detailed source text."}]
    with patch("src.ui.integration.run_investigation", return_value={
        "final_answer": answer,
        "sources": evidence,
        "tool_results": [],
        "confirmation_required": False,
        "confirmation_status": "",
        "pending_action": None,
    }):
        result = start_investigation("Can it be cancelled?", MOCK_USERS["support_agent"])
    assert result["final_answer"] == answer
    assert result["sources"] == evidence
    assert "Detailed source text" not in result["final_answer"]


def test_confirm_ui_helper_calls_confirmation_api():
    with patch("src.ui.integration.confirm_action", return_value={"confirmation_status": "used"}) as confirm:
        result = confirm_pending("CONF-001", MOCK_USERS["support_manager"], "db.sqlite")
    confirm.assert_called_once_with("CONF-001", MOCK_USERS["support_manager"], "db.sqlite")
    assert result["confirmation_status"] == "used"


def test_reject_ui_helper_calls_rejection_api():
    with patch("src.ui.integration.reject_action", return_value={"confirmation_status": "rejected"}) as reject:
        result = reject_pending("CONF-001", MOCK_USERS["support_manager"])
    reject.assert_called_once_with("CONF-001", MOCK_USERS["support_manager"])
    assert result["confirmation_status"] == "rejected"


def test_expired_and_permission_errors_are_returned_for_display():
    with patch("src.ui.integration.confirm_action", return_value={"error": "confirmation_expired", "message": "Expired."}):
        assert confirm_pending("CONF-001", MOCK_USERS["support_manager"])["error"] == "confirmation_expired"
    with patch("src.ui.integration.run_investigation", side_effect=RuntimeError("LLM is not configured")):
        result = start_investigation("Question", MOCK_USERS["support_agent"])
    assert "LLM is not configured" in result["error"]


def test_agent_receives_selected_user_and_read_only_result_has_no_confirmation():
    expected = {"final_answer": "Answer", "confirmation_required": False, "confirmation_status": "", "pending_action": None}
    with patch("src.ui.integration.run_investigation", return_value=expected) as run:
        result = start_investigation("What happened?", MOCK_USERS["support_agent"])
    run.assert_called_once_with("What happened?", MOCK_USERS["support_agent"], model=None)
    assert result["confirmation_required"] is False
    assert confirmation_details(result) is None


def test_scan_for_issues_routes_through_authorized_monitoring_tool():
    findings = [{"issue_id": "MISSED_PICKUP-ACCT-002-ORD-2002", "severity": "high"}]
    with patch("src.ui.integration.scan_operational_issues", return_value=findings) as scan:
        result = scan_issues(MOCK_USERS["support_agent"], "monitoring.db")
    scan.assert_called_once_with(user=MOCK_USERS["support_agent"], db_path="monitoring.db")
    assert result == findings


def test_issue_escalation_preparation_uses_confirmation_registry():
    issue = {
        "issue_id": "OPERATIONAL_FAILURE_TICKET-ACCT-002-TKT-502",
        "ticket_id": "TKT-502",
        "severity": "high",
        "description": "Open operational failure.",
        "recommended_action": "create_escalation",
    }
    with patch("src.ui.integration.request_confirmation", return_value={"confirmation_id": "CONF-001"}) as request:
        result = prepare_issue_escalation(issue, MOCK_USERS["support_manager"])
    request.assert_called_once()
    assert result["confirmation_id"] == "CONF-001"


def test_confirmation_registry_can_be_reset_between_ui_sessions():
    reset_confirmation_registry()
