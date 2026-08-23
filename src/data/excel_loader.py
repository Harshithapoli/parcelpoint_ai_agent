"""Utilities for reading and validating the ParcelPilot Excel workbook."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

LOGGER = logging.getLogger(__name__)
REQUIRED_SHEETS = ("readme", "accounts", "orders", "tickets")


def normalize_sheet_name(value: str) -> str:
    """Normalize workbook sheet names to a stable lowercase identifier."""
    if value is None:
        raise ValueError("Sheet name cannot be None.")
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())
    return normalized.strip("_")


def clean_column_name(value: object) -> str:
    """Convert column labels into safe SQLite/Python-friendly names."""
    if value is None or pd.isna(value):
        return "unnamed"
    cleaned = str(value).strip()
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower() if cleaned else "unnamed"


def validate_expected_sheets(
    actual_sheets: Iterable[str], expected_sheets: Iterable[str] = REQUIRED_SHEETS
) -> list[str]:
    """Ensure the workbook contains all expected data sheets."""
    actual_names = {normalize_sheet_name(sheet) for sheet in actual_sheets}
    expected_names = {normalize_sheet_name(sheet) for sheet in expected_sheets}
    missing = sorted(expected_names - actual_names)
    if missing:
        raise ValueError(
            "Workbook is missing required sheets: "
            f"{missing}. Found: {sorted(actual_names)}"
        )
    return sorted(actual_names)


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize sheet names and columns while retaining the original values."""
    if df is None or not isinstance(df, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame for workbook sheet data.")

    normalized = df.copy()
    normalized.columns = [clean_column_name(column) for column in normalized.columns]
    normalized = normalized.where(pd.notna(normalized), None)
    return normalized


def load_workbook(path: str | Path) -> dict[str, pd.DataFrame]:
    """Load the ParcelPilot workbook and return dictionaries keyed by normalized sheet name."""
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook file not found: {workbook_path}")
    if workbook_path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError(
            f"Unsupported workbook format for '{workbook_path}'. "
            "Expected an Excel file (.xlsx, .xlsm, or .xls)."
        )

    try:
        excel_file = pd.ExcelFile(workbook_path)
    except Exception as exc:  # pragma: no cover - pandas exception path
        raise ValueError(f"Could not open workbook '{workbook_path}': {exc}") from exc

    actual_names = excel_file.sheet_names
    validate_expected_sheets(actual_names, REQUIRED_SHEETS)

    workbook_data: dict[str, pd.DataFrame] = {}
    for sheet_name in actual_names:
        normalized_name = normalize_sheet_name(sheet_name)
        try:
            df = pd.read_excel(workbook_path, sheet_name=sheet_name)
        except Exception as exc:  # pragma: no cover - pandas exception path
            raise ValueError(
                f"Failed to read sheet '{sheet_name}' from workbook '{workbook_path}': {exc}"
            ) from exc

        workbook_data[normalized_name] = _normalize_dataframe(df)

    LOGGER.info("Loaded workbook '%s' with sheets: %s", workbook_path, sorted(workbook_data))
    return workbook_data
