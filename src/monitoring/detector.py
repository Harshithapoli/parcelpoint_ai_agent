"""Deterministic, read-only operational issue detection."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data.database import DatabaseManager
from src.monitoring.models import Issue

LOGGER = logging.getLogger(__name__)


def _snapshot_time(readme_rows: list[dict[str, Any]]) -> datetime:
    for row in readme_rows:
        values = list(row.values())
        if len(values) >= 2 and str(values[0]).strip().lower() == "dataset snapshot":
            value = str(values[1]).replace(" Asia/Kolkata", "")
            try:
                return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            except ValueError:
                break
    return datetime.now(timezone.utc)


def _issue_id(issue_type: str, *identifiers: str) -> str:
    normalized = "-".join(identifier.replace(" ", "-").upper() for identifier in identifiers if identifier)
    return f"{issue_type.upper()}-{normalized}"


def _past_snapshot(snapshot: datetime, value: Any) -> bool:
    try:
        return snapshot.replace(tzinfo=None) > datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False


def _issue(
    issue_type: str,
    severity: str,
    title: str,
    description: str,
    evidence: dict[str, Any],
    detected_at: datetime,
    account_id: str | None = None,
    order_id: str | None = None,
    ticket_id: str | None = None,
    recommended_action: str | None = "create_escalation",
) -> Issue:
    return Issue(
        issue_id=_issue_id(issue_type, account_id or "", order_id or ticket_id or ""),
        issue_type=issue_type,
        severity=severity,
        account_id=account_id,
        order_id=order_id,
        ticket_id=ticket_id,
        title=title,
        description=description,
        evidence=evidence,
        recommended_action=recommended_action,
        detected_at=detected_at,
    )


def detect_issues(db_path: str | Path) -> list[Issue]:
    """Scan current structured data without modifying any database table."""
    manager = DatabaseManager(db_path)
    orders = manager.list_records("orders")
    tickets = manager.list_records("tickets")
    readme = manager.list_records("readme")
    detected_at = _snapshot_time(readme)
    issues: list[Issue] = []

    for order in orders:
        account_id = order.get("account_id")
        order_id = order.get("order_id")
        if order.get("cancellation_requested_at") and order.get("pickup_actual_at"):
            issues.append(
                _issue(
                    "cancellation_after_pickup",
                    "high",
                    "Cancellation requested after pickup",
                    "A cancellation was requested after the order had a recorded pickup.",
                    {
                        "order_id": order_id,
                        "status": order.get("status"),
                        "pickup_actual_at": order.get("pickup_actual_at"),
                        "cancellation_requested_at": order.get("cancellation_requested_at"),
                        "account_id": account_id,
                    },
                    detected_at,
                    account_id,
                    order_id,
                )
            )

        if (
            str(order.get("status", "")).upper() in {"BOOKED", "DRAFT"}
            and not order.get("pickup_actual_at")
            and order.get("pickup_window_end")
            and order.get("carrier_fault")
	            and _past_snapshot(detected_at, order.get("pickup_window_end"))
        ):
            issues.append(
                _issue(
                    "missed_pickup",
                    "high",
                    "Carrier-at-fault pickup is still incomplete",
                    "The order is past its pickup window, has no pickup completion, and the carrier is marked at fault.",
                    {
                        "order_id": order_id,
                        "status": order.get("status"),
                        "pickup_window_end": order.get("pickup_window_end"),
                        "pickup_actual_at": order.get("pickup_actual_at"),
                        "carrier_fault": order.get("carrier_fault"),
                        "customer_fault": order.get("customer_fault"),
                        "account_id": account_id,
                    },
                    detected_at,
                    account_id,
                    order_id,
                )
            )

    for ticket in tickets:
        if str(ticket.get("status", "")).lower() != "open":
            continue
        subject = str(ticket.get("subject", ""))
        description = str(ticket.get("description", ""))
        text = f"{subject} {description}".lower()
        large_scale = any(token in text for token in ("every user", "all shipment", "http 500", "4,200-row", "large csv"))
        if large_scale:
            issues.append(
                _issue(
                    "operational_failure_ticket",
                    "critical" if "http 500" in text or "every user" in text else "high",
                    subject or "Open operational failure ticket",
                    "An open ticket describes a broad or high-impact operational failure.",
                    {
                        "ticket_id": ticket.get("ticket_id"),
                        "status": ticket.get("status"),
                        "subject": subject,
                        "description": description,
                        "account_id": ticket.get("account_id"),
                    },
                    detected_at,
                    ticket.get("account_id"),
                    ticket_id=ticket.get("ticket_id"),
                )
            )

    by_account: dict[str, list[Issue]] = {}
    for issue in issues:
        if issue.account_id:
            by_account.setdefault(issue.account_id, []).append(issue)
    for account_id, account_issues in sorted(by_account.items()):
        if len(account_issues) >= 2:
            issue_types = sorted({issue.issue_type for issue in account_issues})
            issues.append(
                _issue(
                    "multiple_account_issues",
                    "high",
                    "Multiple operational issues detected for account",
                    f"The account has {len(account_issues)} related detected issues.",
                    {
                        "account_id": account_id,
                        "issue_count": len(account_issues),
                        "issue_ids": [issue.issue_id for issue in account_issues],
                        "issue_types": issue_types,
                    },
                    detected_at,
                    account_id,
                )
            )

    unique: dict[str, Issue] = {issue.issue_id: issue for issue in issues}
    return list(unique.values())
