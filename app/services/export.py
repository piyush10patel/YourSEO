"""Export an `AuditResult` as a downloadable CSV or PDF deliverable.

Both functions are pure (input -> bytes), so they're trivially testable and
can be wired straight into a Streamlit ``st.download_button``.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle
    from app.services.audit import AuditResult


def to_csv(result: "AuditResult") -> bytes:
    """Flatten the audit into a single tidy CSV (section, item, detail)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "item", "detail"])

    writer.writerow(["summary", "URL", result.fetched_url])
    writer.writerow(["summary", "Overall score", f"{result.overall_score}/100"])
    writer.writerow(["summary", "Grade", result.grade])
    writer.writerow(["summary", "Word count", result.word_count])
    writer.writerow(
        ["summary", "Rewritten meta description", result.rewritten_meta_description]
    )

    b = result.breakdown
    for label, val in [
        ("Title", b.title),
        ("Meta description", b.meta_description),
        ("Content depth", b.content_depth),
        ("Keyword focus", b.keyword_focus),
    ]:
        writer.writerow(["score_breakdown", label, f"{val}/100"])

    for gap in result.keyword_gaps:
        writer.writerow(["keyword_gap", gap.keyword, gap.rationale])

    for fix in result.technical_fixes:
        writer.writerow(
            ["technical_fix", fix.issue, f"[{fix.severity}] {fix.recommendation}"]
        )

    return buf.getvalue().encode("utf-8")


def _latin1(text: str) -> str:
    """fpdf2's core fonts are Latin-1 only; drop characters they can't encode."""
    return text.encode("latin-1", "replace").decode("latin-1")


def to_pdf(result: "AuditResult") -> bytes:
    """Render a formatted one-page PDF report."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def _line(text: str, *, size: int, style: str = "", h: float = 6) -> None:
        # Always render from the left margin across the full content width;
        # multi_cell with w=0 can otherwise raise "not enough horizontal space"
        # when the cursor is left near the right edge by a prior cell.
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, h, _latin1(text))

    _line("SEO Audit Report", size=18, style="B", h=12)

    pdf.set_text_color(90, 90, 90)
    _line(result.fetched_url, size=11, h=7)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    _line(
        f"Overall score: {result.overall_score}/100  (Grade {result.grade})",
        size=14,
        style="B",
        h=10,
    )
    pdf.ln(1)

    _line("Keyword Gaps", size=13, style="B", h=9)
    if result.keyword_gaps:
        for gap in result.keyword_gaps:
            _line(f"- {gap.keyword}: {gap.rationale}", size=11)
    else:
        _line("None identified.", size=11)
    pdf.ln(1)

    _line("Technical Fixes", size=13, style="B", h=9)
    if result.technical_fixes:
        for fix in result.technical_fixes:
            _line(
                f"- [{fix.severity.upper()}] {fix.issue} -> {fix.recommendation}",
                size=11,
            )
    else:
        _line("None identified.", size=11)
    pdf.ln(1)

    _line("Rewritten Meta Description", size=13, style="B", h=9)
    _line(result.rewritten_meta_description, size=11)

    # fpdf2 returns a bytearray; normalise to bytes.
    return bytes(pdf.output())
