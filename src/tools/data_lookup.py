"""Controlled SQLite lookup tools for operational ParcelPilot data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.config import settings
from src.data.database import DatabaseManager
from src.data.schemas import Account, Order, Ticket
from src.security.auth import User
from src.security.permissions import AuthorizationError, check_permission

LOGGER = logging.getLogger(__name__)


def _manager(db_path: str | Path | None = None) -> DatabaseManager:
    return DatabaseManager(db_path or settings.database_path)


def _lookup(
    table: str,
    id_column: str,
    identifier: str,
    model: type[Account] | type[Order] | type[Ticket],
    db_path: str | Path | None = None,
    user: User | None = None,
) -> Any:
    permission = f"lookup_{table[:-1]}"
    try:
        check_permission(user, permission, permission)
    except (AuthorizationError, ValueError) as exc:
        return {"error": str(exc)}
    if not isinstance(identifier, str) or not identifier.strip():
        return {"error": f"{id_column} must be a non-empty string."}
    value = identifier.strip()
    if len(value) > 100 or any(char in value for char in "\x00\r\n"):
        return {"error": f"Invalid {id_column} format."}

    try:
        record = _manager(db_path).get_record_by_id(table, id_column, value)
        if record is None:
            return {"error": f"No {table[:-1]} found for {id_column} '{value}'."}
        return model.model_validate(record)
    except Exception as exc:  # pragma: no cover - backend-specific errors
        LOGGER.exception("%s lookup failed", table)
        return {"error": f"Could not look up {table[:-1]}: {exc}"}


def lookup_account(account_id: str, db_path: str | Path | None = None, user: User | None = None) -> Account | dict[str, str]:
    """Return an account by its controlled account ID."""
    return _lookup("accounts", "account_id", account_id, Account, db_path, user)


def lookup_order(order_id: str, db_path: str | Path | None = None, user: User | None = None) -> Order | dict[str, Any]:
    """Return an order and its related account record, without policy reasoning."""
    result = _lookup("orders", "order_id", order_id, Order, db_path, user)
    if not isinstance(result, Order):
        return result

    account = lookup_account(result.account_id, db_path, user)
    return {
        "order": result,
        "account": account,
    }


def lookup_ticket(ticket_id: str, db_path: str | Path | None = None, user: User | None = None) -> Ticket | dict[str, str]:
    """Return a ticket by its controlled ticket ID."""
    return _lookup("tickets", "ticket_id", ticket_id, Ticket, db_path, user)
