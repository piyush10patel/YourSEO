"""Google Search Console CSV ingestion (manual upload, no API key).

Parses a GSC "Queries" / "Performance" export. Header names vary by locale and
export type, so matching is case-insensitive and tolerant of the common
variants (Query/Top queries, Clicks, Impressions, CTR, Position).
"""

from __future__ import annotations

import csv
import io
from typing import Any

_QUERY_KEYS = {"query", "queries", "top queries", "search query"}
_CLICK_KEYS = {"clicks"}
_IMPR_KEYS = {"impressions"}
_POS_KEYS = {"position", "avg. position", "average position"}


def _num(value: str) -> float:
    try:
        return float(value.replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def parse_gsc_csv(text: str) -> list[dict[str, Any]]:
    """Return rows: {query, clicks, impressions, position}."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    # Map normalized header -> actual column name.
    cols = {name.strip().lower(): name for name in reader.fieldnames}

    def find(keys: set[str]) -> str | None:
        for norm, actual in cols.items():
            if norm in keys:
                return actual
        return None

    q_col = find(_QUERY_KEYS)
    if q_col is None:
        return []
    c_col, i_col, p_col = find(_CLICK_KEYS), find(_IMPR_KEYS), find(_POS_KEYS)

    rows: list[dict[str, Any]] = []
    for row in reader:
        query = (row.get(q_col) or "").strip()
        if not query:
            continue
        rows.append(
            {
                "query": query,
                "clicks": int(_num(row.get(c_col, "0"))) if c_col else 0,
                "impressions": int(_num(row.get(i_col, "0"))) if i_col else 0,
                "position": round(_num(row.get(p_col, "0")), 1) if p_col else 0.0,
            }
        )
    return rows
