from pathlib import Path
import sqlite3
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.database import initialize_database
from src.data.excel_loader import load_workbook
from src.monitoring.detector import detect_issues
from src.monitoring.models import Issue
from src.tools.monitoring import scan_operational_issues
from src.security.auth import MOCK_USERS, User

WORKBOOK = ROOT / "data" / "ParcelPilot_Assessment_Data.xlsx"


@pytest.fixture
def database_path(tmp_path):
    path = tmp_path / "monitoring.db"
    initialize_database(path, load_workbook(WORKBOOK))
    return path


def test_cancellation_after_pickup_detection(database_path):
    issues = detect_issues(database_path)
    issue = next(item for item in issues if item.issue_type == "cancellation_after_pickup")
    assert issue.order_id == "ORD-1002"
    assert issue.severity == "high"
    assert issue.evidence["pickup_actual_at"]
    assert issue.evidence["cancellation_requested_at"]


def test_missing_pickup_delay_detection(database_path):
    issues = detect_issues(database_path)
    issue = next(item for item in issues if item.issue_type == "missed_pickup")
    assert issue.order_id == "ORD-2002"
    assert issue.evidence["carrier_fault"]
    assert issue.recommended_action == "create_escalation"


def test_operational_ticket_detection(database_path):
    issues = detect_issues(database_path)
    issue = next(item for item in issues if item.ticket_id == "TKT-501")
    assert issue.issue_type == "operational_failure_ticket"
    assert issue.severity == "critical"
    assert issue.evidence["subject"]


def test_multiple_issue_account_detection(database_path):
    issues = detect_issues(database_path)
    issue = next(item for item in issues if item.issue_type == "multiple_account_issues" and item.account_id == "ACCT-001")
    assert issue.severity == "high"
    assert issue.evidence["issue_count"] >= 2


def test_issue_ids_are_unique_and_evidence_is_preserved(database_path):
    issues = detect_issues(database_path)
    assert len({issue.issue_id for issue in issues}) == len(issues)
    assert all(isinstance(issue, Issue) and issue.evidence for issue in issues)


def test_scan_is_read_only_and_authorized(database_path):
    before = _table_counts(database_path)
    results = scan_operational_issues(user=MOCK_USERS["support_agent"], db_path=database_path)
    after = _table_counts(database_path)
    assert isinstance(results, list)
    assert results
    assert before == after


def test_unauthorized_scan_does_not_reach_detector(database_path):
    restricted = User(user_id="reader", role="reader", permissions=frozenset())
    from unittest.mock import patch
    with patch("src.tools.monitoring.detect_issues") as detector:
        result = scan_operational_issues(user=restricted, db_path=database_path)
    assert "Access denied" in result["error"]
    detector.assert_not_called()


def test_empty_healthy_dataset_returns_no_issues(tmp_path):
    workbook = load_workbook(WORKBOOK)
    empty = {name: frame.iloc[0:0].copy() for name, frame in workbook.items()}
    path = tmp_path / "empty.db"
    initialize_database(path, empty)
    assert detect_issues(path) == []


def test_malformed_optional_values_are_safe(database_path):
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE orders SET pickup_window_end = NULL, carrier_fault = NULL WHERE order_id = 'ORD-2002'")
    issues = detect_issues(database_path)
    assert all(issue.order_id != "ORD-2002" or issue.issue_type != "missed_pickup" for issue in issues)


def _table_counts(path):
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("accounts", "orders", "tickets")
        }
