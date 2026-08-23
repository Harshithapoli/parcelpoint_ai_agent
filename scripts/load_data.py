"""Load the ParcelPilot Excel workbook into the SQLite database."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.data.database import DatabaseManager
from src.data.excel_loader import load_workbook

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load ParcelPilot assessment workbook into SQLite.")
    parser.add_argument(
        "--excel-path",
        type=Path,
        default=Path("data/ParcelPilot_Assessment_Data.xlsx"),
        help="Path to the ParcelPilot Excel workbook.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=settings.database_path,
        help="Destination SQLite database path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    workbook_path = args.excel_path.resolve()
    db_path = args.db_path.resolve()

    LOGGER.info("Loading workbook from %s", workbook_path)
    workbook = load_workbook(workbook_path)

    manager = DatabaseManager(db_path)
    tables = manager.load_workbook_data(workbook)

    print("Workbook sheet names:")
    print(sorted(workbook))
    print("\nDatabase tables:")
    print(tables)
    print(f"\nDatabase path: {db_path}")


if __name__ == "__main__":
    main()
