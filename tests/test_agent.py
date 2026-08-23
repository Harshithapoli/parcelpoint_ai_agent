from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.graph import build_agent_graph, run_investigation
from src.config import get_llm
from src.security.auth import MOCK_USERS, User


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


def tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_graph_construction():
    model = FakeModel([AIMessage(content="done")])
    graph = build_agent_graph(model)
    assert graph is not None


def test_basic_agent_invocation_and_explicit_user_context():
    model = FakeModel([AIMessage(content="Answer: The investigation is complete.")])
    state = run_investigation("What is happening?", MOCK_USERS["support_agent"], model)
    assert state["final_answer"].startswith("Answer:")
    assert state["user"].user_id == "support_agent"
    assert len(model.calls) == 1


def test_multistep_tool_invocation_and_source_preservation():
    model = FakeModel(
        [
            tool_call("lookup_order", {"order_id": "ORD-1001"}, "call-1"),
            tool_call("search_documents", {"query": "Northstar cancellation fee", "top_k": 5}, "call-2"),
            AIMessage(content="Answer: Evidence was retrieved.\nEvidence: See the order and agreement."),
        ]
    )
    state = run_investigation("Can Northstar cancel ORD-1001?", MOCK_USERS["support_manager"], model)
    assert len(state["tool_results"]) == 2
    assert state["tool_results"][0]["tool"] == "lookup_order"
    assert state["sources"]
    assert state["sources"][0]["document"]
    assert state["final_answer"].startswith("Answer:")


def test_unknown_order_error_reaches_agent():
    model = FakeModel(
        [
            tool_call("lookup_order", {"order_id": "ORD-999"}, "call-1"),
            AIMessage(content="Answer: The order was not found."),
        ]
    )
    state = run_investigation("Find ORD-999", MOCK_USERS["support_agent"], model)
    assert "No order found" in state["tool_results"][0]["result"]["error"]
    assert "not found" in state["final_answer"]


def test_permission_denial_propagates_through_tool_result():
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    model = FakeModel(
        [
            tool_call("lookup_order", {"order_id": "ORD-1001"}, "call-1"),
            AIMessage(content="Answer: Access was denied."),
        ]
    )
    state = run_investigation("Find ORD-1001", restricted, model)
    assert "Access denied" in state["tool_results"][0]["result"]["error"]


def test_monitoring_tool_invocation_preserves_issue_results():
    model = FakeModel(
        [
            tool_call("scan_operational_issues", {}, "call-monitoring"),
            AIMessage(content="Answer: Several operational issues require review."),
        ]
    )
    state = run_investigation("What issues should I know about today?", MOCK_USERS["support_agent"], model)
    result = state["tool_results"][0]["result"]
    assert state["tool_results"][0]["tool"] == "scan_operational_issues"
    assert isinstance(result, list)
    assert any(item["recommended_action"] == "create_escalation" for item in result)
    assert state["confirmation_required"] is False


def test_escalation_creates_pending_action_without_execution():
    model = FakeModel(
        [
            tool_call("create_escalation", {"ticket_id": "TKT-502", "reason": "Needs review", "priority": "high"}, "call-1"),
            AIMessage(content="Please confirm this escalation."),
        ]
    )
    with patch("src.agent.graph.create_escalation") as action:
        state = run_investigation("Escalate TKT-502", MOCK_USERS["support_manager"], model)
    action.assert_not_called()
    assert state["confirmation_required"] is True
    assert state["confirmation_status"] == "pending"
    assert state["confirmation_id"].startswith("CONF-")
    assert state["pending_action"].model_dump(exclude={"created_at"}) == {
        "action": "create_escalation",
        "ticket_id": "TKT-502",
        "reason": "Needs review",
        "priority": "high",
        "requested_by": "support_manager",
    }


def test_iteration_limit_stops_unbounded_tool_loop():
    model = FakeModel([tool_call("lookup_order", {"order_id": "ORD-1001"}, "call") for _ in range(5)])
    graph = build_agent_graph(model, max_tool_iterations=2)
    state = graph.invoke({"messages": [], "user": MOCK_USERS["support_agent"], "tool_results": [], "sources": [], "tool_iterations": 0})
    assert state["iteration_limit_reached"] is True
    assert "tool-call limit" in state["final_answer"]


def test_missing_llm_configuration_is_clear():
    import src.config as config

    original = config.settings
    config.settings = original.__class__(
        llm_provider="",
        llm_model="",
        llm_api_key="",
        database_path=original.database_path,
        chroma_persist_directory=original.chroma_persist_directory,
        log_level=original.log_level,
        llm_base_url=original.llm_base_url,
    )
    try:
        with pytest.raises(RuntimeError, match="LLM is not configured"):
            get_llm()
    finally:
        config.settings = original
