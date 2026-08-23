"""Authorized read-only operational monitoring tool."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.config import settings
from src.monitoring.detector import detect_issues
from src.security.auth import User
from src.security.permissions import AuthorizationError, check_permission

LOGGER = logging.getLogger(__name__)


def scan_operational_issues(
    user: User | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]] | dict[str, str]:
    """Return deterministic issue findings without executing recommendations."""
    try:
        check_permission(user, "scan_operational_issues", "scan_operational_issues")
    except (AuthorizationError, ValueError) as exc:
        return {"error": str(exc)}
    try:
        return [issue.model_dump(mode="json") for issue in detect_issues(db_path or settings.database_path)]
    except Exception as exc:  # pragma: no cover - backend-specific errors
        LOGGER.exception("Operational issue scan failed")
        return {"error": f"Operational issue scan failed: {exc}"}
