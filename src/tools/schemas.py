"""Typed contracts for the controlled ParcelPilot tools."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.data.schemas import Account, Order, Ticket


class DocumentSearchResult(BaseModel):
    """One retrieved document chunk and its source metadata."""

    model_config = ConfigDict(extra="ignore")

    document: str
    page: int = Field(ge=1)
    text: str
    source_type: str
    status: str
    account: str
    authority: int
    distance: Optional[float] = None


class Escalation(BaseModel):
    """A mocked escalation record created by the action tool."""

    escalation_id: str
    ticket_id: str
    reason: str
    priority: str
    created_at: str
    created_by: str
    status: str


__all__ = ["Account", "Order", "Ticket", "DocumentSearchResult", "Escalation"]
