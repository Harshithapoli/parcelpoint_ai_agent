"""Typed models for deterministic operational issue detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Issue(BaseModel):
    """One explainable operational issue found in structured data."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    issue_type: str
    severity: str
    account_id: str | None = None
    order_id: str | None = None
    ticket_id: str | None = None
    title: str
    description: str
    evidence: dict[str, Any]
    recommended_action: str | None = None
    detected_at: datetime
