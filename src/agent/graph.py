"""Controlled LangGraph investigation workflow for ParcelPilot."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.confirmation import request_confirmation
from src.agent.state import AgentState, PendingAction
from src.config import get_llm
from src.security.auth import User, validate_user
from src.tools.actions import create_escalation
from src.tools.data_lookup import lookup_account, lookup_order, lookup_ticket
from src.tools.document_search import search_documents
from src.tools.monitoring import scan_operational_issues

LOGGER = logging.getLogger(__name__)
MAX_TOOL_ITERATIONS = 8

_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "search_documents": search_documents,
    "lookup_account": lookup_account,
    "lookup_order": lookup_order,
    "lookup_ticket": lookup_ticket,
    "create_escalation": create_escalation,
    "scan_operational_issues": scan_operational_issues,
}
_TOOL_SCHEMAS = [
    {
        "name": "search_documents",
        "description": "Retrieve relevant policy, agreement, SOP, and product-document evidence.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "filters": {"type": "object"}, "top_k": {"type": "integer"}}, "required": ["query"]},
    },
    {
        "name": "lookup_account",
        "description": "Look up one account by account ID.",
        "input_schema": {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]},
    },
    {
        "name": "lookup_order",
        "description": "Look up one order and its related account.",
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
    {
        "name": "lookup_ticket",
        "description": "Look up one ticket by ticket ID.",
        "input_schema": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]},
    },
    {
        "name": "create_escalation",
        "description": "Prepare an escalation request; this phase requires confirmation and does not execute it.",
        "input_schema": {"type": "object", "properties": {"ticket_id": {"type": "string"}, "reason": {"type": "string"}, "priority": {"type": "string"}}, "required": ["ticket_id", "reason", "priority"]},
    },
    {
        "name": "scan_operational_issues",
        "description": "Scan current operational records for deterministic issues; this is read-only.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _as_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _as_jsonable(item) for key, item in value.items()}
    return value


def normalize_response_text(content: Any) -> str:
    """Extract user-facing text from LangChain/Gemini content blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [normalize_response_text(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        if content.get("type") == "text" and content.get("text") is not None:
            return normalize_response_text(content["text"])
        return ""
    return str(content).strip() if content is not None else ""


def _tool_call_parts(call: Any) -> tuple[str, dict[str, Any], str]:
    if isinstance(call, dict):
        return call.get("name", ""), call.get("args", {}) or {}, str(call.get("id", "tool-call"))
    return getattr(call, "name", ""), getattr(call, "args", {}) or {}, str(getattr(call, "id", "tool-call"))


def _invoke_model(model: Any, messages: list[Any]) -> AIMessage:
    bound_model = model
    if hasattr(model, "bind_tools"):
        bound_model = model.bind_tools(_TOOL_SCHEMAS)
    response = bound_model.invoke(messages)
    if isinstance(response, AIMessage):
        response.content = normalize_response_text(response.content)
        return response
    return AIMessage(content=normalize_response_text(getattr(response, "content", response)))


def _agent_node(model: Any, state: AgentState, max_tool_iterations: int) -> dict[str, Any]:
    messages = state.get("messages", [])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
    response = _invoke_model(model, messages)
    iterations = state.get("tool_iterations", 0)
    if getattr(response, "tool_calls", None) and iterations >= max_tool_iterations:
        return {
            "messages": [AIMessage(content="Investigation could not be completed within the tool-call limit. The available evidence is partial.")],
            "final_answer": "Investigation could not be completed within the tool-call limit. The available evidence is partial.",
            "iteration_limit_reached": True,
        }
    if not getattr(response, "tool_calls", None):
        answer = normalize_response_text(response.content) or "No answer was produced."
        response.content = answer
        return {"messages": [response], "final_answer": answer}
    return {"messages": [response]}


def _tools_node(state: AgentState) -> dict[str, Any]:
    user = validate_user(state.get("user"))
    last_message = state.get("messages", [])[-1]
    tool_results = list(state.get("tool_results", []))
    sources = list(state.get("sources", []))
    tool_messages: list[ToolMessage] = []
    pending_action = state.get("pending_action")
    confirmation_required = state.get("confirmation_required", False)
    confirmation_id = state.get("confirmation_id")
    confirmation_status = state.get("confirmation_status", "")

    for raw_call in getattr(last_message, "tool_calls", []):
        name, arguments, call_id = _tool_call_parts(raw_call)
        if name == "create_escalation":
            pending_action = PendingAction(
                action="create_escalation",
                ticket_id=str(arguments.get("ticket_id", "")),
                reason=str(arguments.get("reason", "")),
                priority=str(arguments.get("priority", "")),
                requested_by=user.user_id,
                created_at=datetime.now(timezone.utc),
            )
            result = request_confirmation(pending_action, user)
            confirmation_required = result.get("confirmation_required", False)
            confirmation_id = result.get("confirmation_id")
            confirmation_status = result.get("confirmation_status", "pending")
        elif name in _TOOL_FUNCTIONS:
            try:
                result = _TOOL_FUNCTIONS[name](**arguments, user=user)
            except Exception as exc:  # pragma: no cover - defensive tool boundary
                result = {"error": f"Tool '{name}' failed: {exc}"}
        else:
            result = {"error": f"Unknown tool '{name}'."}

        json_result = _as_jsonable(result)
        record = {"tool": name, "result": json_result}
        tool_results.append(record)
        if isinstance(json_result, list):
            sources.extend(item for item in json_result if isinstance(item, dict) and "document" in item)
        tool_messages.append(ToolMessage(content=json.dumps(json_result, default=str), tool_call_id=call_id))

    return {
        "messages": tool_messages,
        "tool_results": tool_results,
        "sources": sources,
        "pending_action": pending_action,
        "confirmation_required": confirmation_required,
        "confirmation_status": confirmation_status if confirmation_required else state.get("confirmation_status", ""),
        "confirmation_id": confirmation_id if confirmation_required else state.get("confirmation_id"),
        "final_answer": (
            f"Confirmation required for escalation {confirmation_id}. "
            "Use the confirmation ID to approve or reject this action."
            if confirmation_required else state.get("final_answer", "")
        ),
        "tool_iterations": state.get("tool_iterations", 0) + 1,
    }


def _route_after_agent(state: AgentState) -> str:
    if state.get("iteration_limit_reached"):
        return END
    last_message = state.get("messages", [])[-1]
    if getattr(last_message, "tool_calls", None) and state.get("tool_iterations", 0) < state.get("max_tool_iterations", MAX_TOOL_ITERATIONS):
        return "tools"
    return END


def build_agent_graph(model: Any | None = None, max_tool_iterations: int = MAX_TOOL_ITERATIONS):
    """Compile the investigation graph; a model can be injected for deterministic tests."""
    if max_tool_iterations <= 0:
        raise ValueError("max_tool_iterations must be positive")
    resolved_model = model or get_llm()
    graph = StateGraph(AgentState)
    graph.add_node("agent", lambda state: _agent_node(resolved_model, state, max_tool_iterations))
    graph.add_node("tools", _tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", END: END})
    graph.add_conditional_edges(
        "tools",
        lambda state: END if state.get("confirmation_required") else "agent",
        {"agent": "agent", END: END},
    )
    return graph.compile()


def run_investigation(question: str, user: User, model: Any | None = None) -> AgentState:
    """Run one authenticated investigation with an explicit user context."""
    if not isinstance(user, User):
        raise ValueError("An explicit authenticated User is required.")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Investigation question must be non-empty.")
    graph = build_agent_graph(model=model)
    return graph.invoke({"messages": [HumanMessage(content=question.strip())], "user": user, "tool_results": [], "sources": [], "confirmation_required": False, "pending_action": None, "tool_iterations": 0, "max_tool_iterations": MAX_TOOL_ITERATIONS})
