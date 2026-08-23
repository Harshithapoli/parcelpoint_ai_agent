"""Business-rule helpers kept separate from document retrieval."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


SOURCE_PRECEDENCE = {
    "customer_agreement": 4,
    "current_policy": 3,
    "product_documentation": 2,
    "current_sop": 2,
    "historical_ticket": 1,
}


def rank_sources_for_account(
    sources: Iterable[dict[str, Any]], account: str | None = None
) -> list[dict[str, Any]]:
    """Rank already-retrieved evidence by applicability and authority.

    Retrieval remains responsible for finding evidence; this helper only supports
    later business-rule comparison and does not discard conflicting sources.
    """
    applicable = [
        source
        for source in sources
        if not account or not source.get("account") or source.get("account") == account
    ]
    return sorted(
        applicable,
        key=lambda source: (
            SOURCE_PRECEDENCE.get(source.get("source_type", ""), 0),
            source.get("authority", 0),
            -(source.get("distance", float("inf")) or float("inf")),
        ),
        reverse=True,
    )
