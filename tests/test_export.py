"""Export tests: CSV is well-formed, PDF is a real PDF document."""

from __future__ import annotations

import csv
import io

from app.services.export import to_csv, to_pdf
from tests.test_api import _fake_audit_result


def test_to_csv_contains_sections() -> None:
    result = _fake_audit_result("https://example.com")
    raw = to_csv(result).decode("utf-8")

    rows = list(csv.reader(io.StringIO(raw)))
    assert rows[0] == ["section", "item", "detail"]
    sections = {r[0] for r in rows[1:]}
    assert {"summary", "score_breakdown", "keyword_gap", "technical_fix"} <= sections
    # The keyword gap from the fixture is present.
    assert any("kw" in r for r in rows)


def test_to_pdf_is_valid_pdf() -> None:
    result = _fake_audit_result("https://example.com")
    data = to_pdf(result)
    assert isinstance(data, bytes)
    assert data[:5] == b"%PDF-"  # PDF magic number
    assert len(data) > 800  # non-trivial document


def test_to_pdf_handles_non_latin1_text() -> None:
    # fpdf core fonts are Latin-1; non-encodable chars must not crash.
    result = _fake_audit_result("https://example.com")
    result.rewritten_meta_description = "Café — 日本語 — emoji 🚀 included"
    data = to_pdf(result)
    assert data[:5] == b"%PDF-"


def test_to_pdf_handles_long_wrapping_text() -> None:
    # Real demo data has long rationales/recommendations that must wrap without
    # raising "not enough horizontal space".
    from app.services.audit import demo_result

    data = to_pdf(demo_result("https://www.example.com"))
    assert data[:5] == b"%PDF-"
    assert len(data) > 1000
