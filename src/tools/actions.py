"""Mocked state-changing actions for ParcelPilot operations."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.data.database import DatabaseManager
from src.security.auth import User
from src.security.permissions import AuthorizationError, check_permission
from src.tools.schemas import Escalation

LOGGER = logging.getLogger(__name__)
VALID_PRIORITIES = {"low", "medium", "high", "p1", "p2", "p3"}


def _next_escalation_id(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT escalation_id FROM escalations "
        "WHERE escalation_id LIKE 'ESC-%' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "ESC-001"
    try:
        number = int(str(row[0]).split("-")[-1]) + 1
    except (TypeError, ValueError):
        number = connection.execute("SELECT COUNT(*) FROM escalations").fetchone()[0] + 1
    return f"ESC-{number:03d}"


def create_escalation(
    ticket_id: str,
    reason: str,
    priority: str,
    db_path: str | Path | None = None,
    created_by: str = "tool",
    user: User | None = None,
) -> Escalation | dict[str, str]:
    """Create a local escalation record; confirmation remains an agent responsibility."""
    try:
        acting_user = check_permission(user, "create_escalation", "create_escalation")
    except (AuthorizationError, ValueError) as exc:
        return {"error": str(exc)}
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        return {"error": "ticket_id must be a non-empty string."}
    if not isinstance(reason, str) or not reason.strip():
        return {"error": "Escalation reason must be a non-empty string."}
    if not isinstance(priority, str) or priority.strip().lower() not in VALID_PRIORITIES:
        return {"error": "Invalid priority. Use low, medium, high, p1, p2, or p3."}

    manager = DatabaseManager(db_path or settings.database_path)
    try:
        with manager._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS escalations ("
                "escalation_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, "
                "reason TEXT NOT NULL, priority TEXT NOT NULL, created_at TEXT NOT NULL, "
                "created_by TEXT NOT NULL, status TEXT NOT NULL)"
            )
            ticket = connection.execute(
                "SELECT 1 FROM tickets WHERE ticket_id = ? LIMIT 1", (ticket_id.strip(),)
            ).fetchone()
            if ticket is None:
                return {"error": f"No ticket found for ticket_id '{ticket_id.strip()}'."}

            escalation_id = _next_escalation_id(connection)
            created_at = datetime.now(timezone.utc).isoformat()
            created_by = acting_user.user_id
            status = "open"
            normalized_priority = priority.strip().lower()
            connection.execute(
                "INSERT INTO escalations "
                "(escalation_id, ticket_id, reason, priority, created_at, created_by, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    escalation_id,
                    ticket_id.strip(),
                    reason.strip(),
                    normalized_priority,
                    created_at,
                    created_by,
                    status,
                ),
            )

        return Escalation(
            escalation_id=escalation_id,
            ticket_id=ticket_id.strip(),
            reason=reason.strip(),
            priority=normalized_priority,
            created_at=created_at,
            created_by=created_by,
            status=status,
        )
    except sqlite3.Error as exc:
        LOGGER.exception("Escalation creation failed")
        return {"error": f"Could not create escalation: {exc}"}
