"""SQLite data access layer for workbook-backed ParcelPilot operational data."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from .excel_loader import validate_expected_sheets

LOGGER = logging.getLogger(__name__)
ALLOWED_TABLES = {"readme", "accounts", "orders", "tickets"}


class _ManagedConnection(sqlite3.Connection):
    """SQLite connection that closes after a context-managed transaction."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class DatabaseManager:
    """Manage SQLite tables that mirror the Excel workbook data."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, factory=_ManagedConnection)
        connection.row_factory = sqlite3.Row
        return connection

    def _validate_table_name(self, table_name: str) -> str:
        if not table_name or not isinstance(table_name, str):
            raise ValueError("Table name must be a non-empty string.")
        normalized = re.sub(r"[^a-z0-9_]+", "", table_name.lower())
        if normalized not in ALLOWED_TABLES:
            raise ValueError(f"Unsupported table name '{table_name}'.")
        return normalized

    def _validate_id_column(self, id_column: str) -> str:
        if not id_column or not isinstance(id_column, str):
            raise ValueError("ID column must be a non-empty string.")
        cleaned = re.sub(r"[^a-z0-9_]+", "", id_column.lower())
        if not cleaned:
            raise ValueError("ID column must contain alphanumeric characters.")
        return cleaned

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def list_tables(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;"
            ).fetchall()
        return [row["name"] for row in rows]

    def row_count(self, table_name: str) -> int:
        normalized = self._validate_table_name(table_name)
        with self._connect() as connection:
            result = connection.execute(
                f"SELECT COUNT(*) AS total FROM {self._quote_identifier(normalized)};"
            ).fetchone()
        return int(result["total"])

    def list_records(self, table_name: str) -> list[dict[str, Any]]:
        """Return all records from an allowlisted workbook table for read-only services."""
        normalized = self._validate_table_name(table_name)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._quote_identifier(normalized)};"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_record_by_id(self, table_name: str, id_column: str, value: Any) -> dict[str, Any] | None:
        normalized_table = self._validate_table_name(table_name)
        normalized_id = self._validate_id_column(id_column)
        if value is None:
            raise ValueError("Lookup value cannot be None.")
        with self._connect() as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?;",
                (normalized_table,),
            ).fetchone()
            if table_exists is None:
                raise ValueError(f"Table '{normalized_table}' does not exist in the database.")

            query = (
                f"SELECT * FROM {self._quote_identifier(normalized_table)} "
                f"WHERE {self._quote_identifier(normalized_id)} = ? LIMIT 1;"
            )
            row = connection.execute(query, (value,)).fetchone()
        return dict(row) if row is not None else None

    def _create_table(self, table_name: str, df: pd.DataFrame) -> None:
        normalized = self._validate_table_name(table_name)
        if df is None or not isinstance(df, pd.DataFrame):
            raise TypeError("Workbook sheet data must be a pandas DataFrame.")

        cleaned = df.copy()
        cleaned.columns = [re.sub(r"[^a-z0-9_]+", "_", str(col).lower()).strip("_") or "unnamed" for col in cleaned.columns]
        cleaned = cleaned.where(pd.notna(cleaned), None)

        with self._connect() as connection:
            cleaned.to_sql(normalized, connection, if_exists="replace", index=False)

    def _create_indexes(self) -> None:
        index_specs = {
            "accounts": ["account_id"],
            "orders": ["order_id", "account_id"],
            "tickets": ["ticket_id", "account_id"],
        }

        with self._connect() as connection:
            for table_name, columns in index_specs.items():
                for column_name in columns:
                    index_name = f"idx_{table_name}_{column_name}"
                    query = (
                        f"CREATE INDEX IF NOT EXISTS {self._quote_identifier(index_name)} "
                        f"ON {self._quote_identifier(table_name)} ({self._quote_identifier(column_name)});"
                    )
                    connection.execute(query)

    def load_workbook_data(self, workbook: dict[str, pd.DataFrame]) -> list[str]:
        if not workbook:
            raise ValueError("Workbook data is empty. Nothing to load.")

        actual = sorted(workbook)
        validate_expected_sheets(actual, ALLOWED_TABLES)

        for table_name, df in workbook.items():
            self._create_table(table_name, df)

        self._create_indexes()
        return self.list_tables()


def initialize_database(db_path: str | Path, workbook: dict[str, pd.DataFrame]) -> DatabaseManager:
    """Convenience function to create and populate a SQLite database from workbook data."""
    manager = DatabaseManager(db_path)
    manager.load_workbook_data(workbook)
    return manager
