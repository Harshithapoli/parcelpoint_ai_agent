"""Human confirmation registry for state-changing agent actions."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from src.security.auth import User
from src.security.permissions import AuthorizationError, check_permission
from src.tools.actions import create_escalation
from src.agent.state import PendingAction

LOGGER = logging.getLogger("parcelpilot.audit")
CONFIRMATION_TTL_MINUTES = int(os.getenv("CONFIRMATION_TTL_MINUTES", "15"))

_RECORDS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_NEXT_ID = 1


def _audit(event: str, user: User, confirmation_id: str, result: str) -> None:
    LOGGER.info(
        "confirmation_event event=%s user_id=%s role=%s action=create_escalation confirmation_id=%s timestamp=%s result=%s",
        event,
        user.user_id,
        user.role,
        confirmation_id,
        datetime.now(timezone.utc).isoformat(),
        result,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(code: str, message: str) -> dict[str, str]:
    return {"error": code, "message": message}


def request_confirmation(
    pending_action: PendingAction | dict[str, Any],
    user: User | None = None,
) -> dict[str, Any]:
    """Register one pending action and return its explicit confirmation ID."""
    if not isinstance(pending_action, PendingAction):
        try:
            pending_action = PendingAction.model_validate(pending_action)
        except Exception as exc:
            return _error("invalid_pending_action", f"Invalid pending action: {exc}")
    if user is None:
        return _error("missing_user", "An explicit authenticated user is required.")
    if not isinstance(user, User):
        return _error("invalid_user", "A valid User is required.")
    if pending_action.requested_by != user.user_id:
        return _error("action_owner_mismatch", "Pending action does not belong to this user.")

    global _NEXT_ID
    with _LOCK:
        confirmation_id = f"CONF-{_NEXT_ID:03d}"
        _NEXT_ID += 1
        _RECORDS[confirmation_id] = {
            "pending_action": pending_action,
            "requested_by": user.user_id,
            "created_at": _now(),
            "status": "pending",
        }
    _audit("confirmation_requested", user, confirmation_id, "pending")
    return {
        "confirmation_id": confirmation_id,
        "pending_action": pending_action.model_dump(),
        "confirmation_required": True,
        "confirmation_status": "pending",
    }


def _get_record(confirmation_id: str) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(confirmation_id, str) or not confirmation_id.strip():
        return "malformed_confirmation_id", None
    normalized = confirmation_id.strip().upper()
    if not normalized.startswith("CONF-") or not normalized[5:].isdigit():
        return "malformed_confirmation_id", None
    with _LOCK:
        return normalized, _RECORDS.get(normalized)


def confirm_action(
    confirmation_id: str,
    user: User,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Authorize and execute one unexpired, owned confirmation exactly once."""
    resolved_id, record = _get_record(confirmation_id)
    if record is None:
        code = resolved_id if resolved_id == "malformed_confirmation_id" else "confirmation_not_found"
        return _error(code, "Confirmation ID is invalid or does not exist.")
    if not isinstance(user, User):
        return _error("invalid_user", "A valid User is required.")

    with _LOCK:
        status = record["status"]
        if status == "used":
            _audit("action_denied", user, resolved_id, "confirmation_already_used")
            return _error("confirmation_already_used", "This confirmation has already been used.")
        if status == "rejected":
            return _error("confirmation_rejected", "This confirmation was rejected.")
        if status == "expired":
            return _error("confirmation_expired", "This confirmation has expired.")
        if _now() - record["created_at"] > timedelta(minutes=CONFIRMATION_TTL_MINUTES):
            record["status"] = "expired"
            _audit("confirmation_expired", user, resolved_id, "confirmation_expired")
            return _error("confirmation_expired", "This confirmation has expired.")
        pending_action: PendingAction = record["pending_action"]
        if record["requested_by"] != user.user_id:
            _audit("action_denied", user, resolved_id, "action_owner_mismatch")
            return _error("action_owner_mismatch", "Only the user who requested this action may confirm it.")

    try:
        check_permission(user, "create_escalation", "confirm_action")
    except (AuthorizationError, ValueError) as exc:
        _audit("action_denied", user, resolved_id, "permission_denied")
        return _error("permission_denied", str(exc))

    result = create_escalation(
        pending_action.ticket_id,
        pending_action.reason,
        pending_action.priority,
        db_path,
        user=user,
    )
    if isinstance(result, dict) and "error" in result:
        _audit("action_denied", user, resolved_id, "action_failed")
        return result

    with _LOCK:
        record["status"] = "used"
    _audit("action_executed", user, resolved_id, "success")
    return {
        "confirmation_id": resolved_id,
        "confirmation_status": "used",
        "action_result": result.model_dump() if hasattr(result, "model_dump") else result,
    }


def reject_action(confirmation_id: str, user: User) -> dict[str, Any]:
    """Reject an owned pending action without touching the escalation database."""
    resolved_id, record = _get_record(confirmation_id)
    if record is None:
        code = resolved_id if resolved_id == "malformed_confirmation_id" else "confirmation_not_found"
        return _error(code, "Confirmation ID is invalid or does not exist.")
    if not isinstance(user, User):
        return _error("invalid_user", "A valid User is required.")

    with _LOCK:
        if record["status"] != "pending":
            return _error(f"confirmation_{record['status']}", "This confirmation is no longer pending.")
        if record["requested_by"] != user.user_id:
            _audit("confirmation_rejected", user, resolved_id, "action_owner_mismatch")
            return _error("action_owner_mismatch", "Only the requesting user may reject this action.")
        record["status"] = "rejected"
    _audit("confirmation_rejected", user, resolved_id, "rejected")
    return {"confirmation_id": resolved_id, "confirmation_status": "rejected", "action_executed": False}


def reset_confirmation_registry() -> None:
    """Clear in-memory confirmations for isolated tests and local sessions."""
    global _NEXT_ID
    with _LOCK:
        _RECORDS.clear()
        _NEXT_ID = 1
