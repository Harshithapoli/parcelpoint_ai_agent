"""Typed state passed through the ParcelPilot investigation graph."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel

from src.security.auth import User


class PendingAction(BaseModel):
    action: str
    ticket_id: str
    reason: str
    priority: str
    requested_by: str
    created_at: datetime


class AgentState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    user: User
    tool_results: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    pending_action: PendingAction | None
    confirmation_required: bool
    confirmation_status: str
    confirmation_id: str | None
    final_answer: str
    tool_iterations: int
    iteration_limit_reached: bool
    max_tool_iterations: int
