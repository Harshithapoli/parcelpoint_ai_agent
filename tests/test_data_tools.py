from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from src.data.database import DatabaseManager
from src.data.excel_loader import load_workbook, validate_expected_sheets


WORKBOOK_PATH = Path("data/ParcelPilot_Assessment_Data.xlsx")


def test_workbook_loading():
    workbook = load_workbook(WORKBOOK_PATH)

    assert set(workbook.keys()) >= {"readme", "accounts", "orders", "tickets"}
    assert workbook["accounts"].shape[0] == 4
    assert workbook["orders"].shape[0] == 6
    assert workbook["tickets"].shape[0] == 7
    assert "account_id" in workbook["accounts"].columns
    assert "order_id" in workbook["orders"].columns
    assert "ticket_id" in workbook["tickets"].columns


def test_database_creation_and_table_creation(tmp_path):
    db_path = tmp_path / "parcelpilot.db"
    workbook = load_workbook(WORKBOOK_PATH)

    manager = DatabaseManager(db_path)
    manager.load_workbook_data(workbook)
    tables = manager.list_tables()

    assert {"accounts", "orders", "tickets", "readme"}.issubset(set(tables))
    assert manager.row_count("accounts") == 4
    assert manager.row_count("orders") == 6
    assert manager.row_count("tickets") == 7


def test_record_lookup_and_unknown_ids(tmp_path):
    db_path = tmp_path / "parcelpilot.db"
    workbook = load_workbook(WORKBOOK_PATH)

    manager = DatabaseManager(db_path)
    manager.load_workbook_data(workbook)

    account = manager.get_record_by_id("accounts", "account_id", "ACCT-001")
    order = manager.get_record_by_id("orders", "order_id", "ORD-1001")

    assert account is not None
    assert account["account_name"] == "Northstar Logistics"
    assert order is not None
    assert order["carrier"] == "SwiftShip"
    assert manager.get_record_by_id("accounts", "account_id", "ACCT-999") is None
    assert manager.get_record_by_id("orders", "order_id", "ORD-999") is None


def test_missing_and_invalid_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workbook(tmp_path / "missing.xlsx")

    with pytest.raises(ValueError):
        validate_expected_sheets(["accounts", "orders"], ["accounts", "tickets"])

    with pytest.raises(ValueError):
        DatabaseManager(tmp_path / "invalid.db").get_record_by_id("missing_table", "account_id", "ACCT-001")
