"""SEO Agent — Streamlit UI.

Run with:
    streamlit run app/ui/streamlit_app.py

Sidebar navigation (Dashboard / Run Audit / Settings). The Run Audit page
takes a URL, runs the agent (with a spinner), and renders a premium-styled
dashboard: overall SEO score, keyword gaps, and AI content improvements.

By default it runs in **Demo mode** (no backend needed). Turn Demo mode off in
Settings to run a live audit against a scraped URL + local Ollama model.
"""

from __future__ import annotations

import asyncio
import time
from typing import Iterator

import streamlit as st

import requests

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.services import audit as audit_service
from app.services import export
from app.ui import theme

PAGES = ["Dashboard", "Run Audit", "Settings"]

# Canned executive summary used for the typing effect in Demo mode (no LLM).
_DEMO_SUMMARY = (
    "Your page scored {score}/100 (grade {grade}) — a solid base with clear "
    "room to grow. The biggest wins are tightening your meta description and "
    "targeting the keyword gaps below, which together should lift click-through "
    "and rankings. Apply the high-severity fixes first, then re-audit in a few "
    "weeks to track progress."
)


def _summary_chunks(result, settings: Settings | None) -> Iterator[str]:
    """Yield executive-summary text chunks for st.write_stream (typing effect).

    Live mode streams real tokens from Ollama; Demo mode types out a canned
    summary so the effect works with no backend.
    """
    if result.generated_by == "demo":
        text = _DEMO_SUMMARY.format(score=result.overall_score, grade=result.grade)
        for word in text.split(" "):
            yield word + " "
            time.sleep(0.02)
        return

    # Live: bridge the async token generator into a sync generator.
    loop = asyncio.new_event_loop()
    agen = audit_service.stream_summary_async(result, settings)
    try:
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
    except AppError as exc:
        yield f"\n\n_(Summary unavailable: {exc.message})_"
    finally:
        try:
            loop.run_until_complete(agen.aclose())
        except Exception:
            pass
        loop.close()


def _available_models(base_url: str) -> list[str] | None:
    """Return installed Ollama model names, or None if the server is unreachable."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def _init_state() -> None:
    ss = st.session_state
    # Pull defaults from configured settings (env-aware): inside Docker,
    # SEO_OLLAMA_BASE_URL points at http://host.docker.internal:11434.
    settings = get_settings()
    ss.setdefault("result", None)  # last AuditResult
    ss.setdefault("error", None)  # last error message
    ss.setdefault("demo_mode", False)  # default to a real (live) audit
    ss.setdefault("ollama_base_url", settings.ollama_base_url)
    ss.setdefault("ollama_model", settings.ollama_model)
    ss.setdefault("render_js", True)  # auto-render JS-heavy pages when needed
    ss.setdefault("summary", None)  # streamed executive summary text
    ss.setdefault("summary_key", None)  # which result the summary belongs to
    ss.setdefault("stream_settings", None)  # Settings used for live streaming


# --------------------------------------------------------------------------- #
# Shared chrome
# --------------------------------------------------------------------------- #
def _sidebar() -> str:
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand"><span class="logo">🚀</span> SEO Agent</div>'
            '<div class="sidebar-tag">AI-powered on-page optimization</div>',
            unsafe_allow_html=True,
        )
        page = st.radio("Navigation", PAGES, label_visibility="collapsed", key="nav")
        st.markdown("<hr style='opacity:.25'>", unsafe_allow_html=True)
        mode = "🟢 Demo mode" if st.session_state.demo_mode else "🔴 Live mode"
        st.caption(f"Status: {mode}")
    return page


def _hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Dashboard rendering
# --------------------------------------------------------------------------- #
def _render_dashboard(result: audit_service.AuditResult) -> None:
    # Data-quality guardrails: surface what was actually audited + any caveats.
    st.caption(
        f"📄 Audited page: **{result.title or '(no title)'}** · "
        f"{result.word_count} words · confidence: "
        + ("🟢 high" if result.confidence == "high" else "🟠 low")
    )
    for warning in result.warnings:
        st.warning(warning)

    # Top row: score donut + headline metrics.
    score_col, metrics_col = st.columns([1, 2.2], gap="large")

    with score_col:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown(
            '<div class="label">Overall SEO Score</div>'
            '<div class="score-wrap" style="margin-top:.6rem;">'
            + theme.score_donut(result.overall_score, result.grade)
            + "</div></div>",
            unsafe_allow_html=True,
        )

    with metrics_col:
        c1, c2 = st.columns(2, gap="medium")
        b = result.breakdown
        c1.markdown(
            theme.metric_card(
                "Content Depth", str(result.word_count), "words on page", "wds"
            ),
            unsafe_allow_html=True,
        )
        c2.markdown(
            theme.metric_card(
                "Keyword Gaps", str(len(result.keyword_gaps)), "opportunities found"
            ),
            unsafe_allow_html=True,
        )
        c3, c4 = st.columns(2, gap="medium")
        c3.markdown(
            theme.metric_card(
                "Technical Fixes", str(len(result.technical_fixes)), "issues to resolve"
            ),
            unsafe_allow_html=True,
        )
        c4.markdown(
            theme.metric_card(
                "Meta Description", f"{b.meta_description}", "sub-score / 100"
            ),
            unsafe_allow_html=True,
        )

    # Score breakdown bars.
    st.markdown(
        '<div class="section-title">📊 Score Breakdown</div>', unsafe_allow_html=True
    )
    bd = result.breakdown
    cols = st.columns(4, gap="medium")
    for col, (label, val) in zip(
        cols,
        [
            ("Title", bd.title),
            ("Meta Desc.", bd.meta_description),
            ("Content Depth", bd.content_depth),
            ("Keyword Focus", bd.keyword_focus),
        ],
    ):
        with col:
            st.markdown(
                theme.metric_card(label, str(val), "/ 100"), unsafe_allow_html=True
            )
            st.progress(val / 100)

    # Keyword gaps.
    st.markdown(
        '<div class="section-title">🔑 Keyword Gaps</div>', unsafe_allow_html=True
    )
    if result.keyword_gaps:
        for gap in result.keyword_gaps:
            st.markdown(
                theme.keyword_gap_card(gap.keyword, gap.rationale),
                unsafe_allow_html=True,
            )
    else:
        st.info("No significant keyword gaps detected — nice work!")

    # Top keywords table (supporting evidence).
    if result.top_keywords:
        with st.expander("View current top keywords (on-page)"):
            st.dataframe(result.top_keywords, use_container_width=True, hide_index=True)

    # AI-generated content improvements.
    st.markdown(
        '<div class="section-title">✨ AI-Generated Content Improvements</div>',
        unsafe_allow_html=True,
    )
    st.markdown("**Rewritten meta description**")
    st.markdown(
        theme.meta_box(
            result.current_meta_description, result.rewritten_meta_description
        ),
        unsafe_allow_html=True,
    )
    st.markdown("<br>**Recommended technical fixes**", unsafe_allow_html=True)
    if result.technical_fixes:
        for fix in result.technical_fixes:
            st.markdown(
                theme.fix_card(fix.issue, fix.recommendation, fix.severity),
                unsafe_allow_html=True,
            )
    else:
        st.success("No technical issues found.")

    _render_downloads(result)


def _render_downloads(result: audit_service.AuditResult) -> None:
    """Export the report as a downloadable CSV or PDF deliverable."""
    st.markdown(
        '<div class="section-title">📥 Export Report</div>', unsafe_allow_html=True
    )
    slug = result.fetched_url.split("//")[-1].strip("/").replace("/", "_") or "report"
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ Download CSV",
        data=export.to_csv(result),
        file_name=f"seo_audit_{slug}.csv",
        mime="text/csv",
        use_container_width=True,
        key="dl_csv",
    )
    c2.download_button(
        "⬇️ Download PDF",
        data=export.to_pdf(result),
        file_name=f"seo_audit_{slug}.pdf",
        mime="application/pdf",
        use_container_width=True,
        key="dl_pdf",
    )


def _empty_state() -> None:
    st.markdown(
        '<div class="card" style="text-align:center;padding:2.5rem;">'
        '<div style="font-size:2.5rem;">📈</div>'
        '<div class="card-title" style="font-size:1.1rem;margin-top:.5rem;">No audit yet</div>'
        '<div class="card-body">Head to <b>Run Audit</b>, enter a URL, and run the SEO Agent '
        "to generate your dashboard.</div></div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_dashboard() -> None:
    _hero("Dashboard", "Your latest SEO audit at a glance.")
    result = st.session_state.result
    if result is None:
        _empty_state()
    else:
        st.caption(
            f"Showing results for **{result.fetched_url}** · generated via *{result.generated_by}* mode"
        )
        summary = st.session_state.get("summary")
        if summary:
            st.markdown(
                '<div class="section-title">✨ Executive Summary</div>',
                unsafe_allow_html=True,
            )
            st.info(summary)
        _render_dashboard(result)


def page_run_audit() -> None:
    _hero("Run SEO Audit", "Enter a page URL and let the agent analyze it.")

    # Mode control lives here (not buried in Settings) so it's obvious which
    # path will run. Outside the form so toggling updates the status instantly.
    st.toggle(
        "Demo mode (use sample data instead of a live scrape + Ollama)",
        key="demo_mode",
    )
    if st.session_state.demo_mode:
        st.caption(
            "🟢 **Demo mode** — returns fixed sample data and ignores the URL. Turn it off for a real audit."
        )
    else:
        st.caption(
            f"🔴 **Live mode** — will scrape the URL and analyze it with "
            f"**{st.session_state.ollama_model}** via Ollama."
        )
        st.toggle(
            "Render JavaScript pages (headless browser) — needed for SPAs; a bit slower",
            key="render_js",
        )

    with st.form("audit_form"):
        url = st.text_input(
            "Page URL",
            placeholder="https://www.example.com",
            help="The page you want to optimize.",
        )
        submitted = st.form_submit_button(
            "🚀 Run SEO Agent", type="primary", use_container_width=True
        )

    if submitted:
        if not url or not url.strip():
            st.warning("Please enter a URL to audit.")
            return

        st.session_state.error = None
        # In live mode, honour the Ollama settings configured in Settings.
        settings = None
        if not st.session_state.demo_mode:
            settings = Settings(
                ollama_base_url=st.session_state.ollama_base_url,
                ollama_model=st.session_state.ollama_model,
            )

        render_js = "auto" if st.session_state.render_js else False

        with st.spinner(
            "Running SEO agent — scraping, analyzing keywords, generating improvements…"
        ):
            try:
                result = audit_service.run_audit(
                    url.strip(),
                    settings,
                    demo=st.session_state.demo_mode,
                    render_js=render_js,
                )
                st.session_state.result = result
                # Reset the executive summary so it re-streams for this result.
                st.session_state.summary = None
                st.session_state.summary_key = None
                st.session_state.stream_settings = settings
            except AppError as exc:  # scraper / LLM / agent failures
                st.session_state.result = None
                st.session_state.error = f"{exc.error_code}: {exc.message}"
            except Exception as exc:  # pragma: no cover - unexpected
                st.session_state.result = None
                # Always include the type — some exceptions (e.g.
                # NotImplementedError) stringify to an empty message.
                st.session_state.error = (
                    f"Unexpected error: {type(exc).__name__}: {exc}".rstrip(": ")
                )

    if st.session_state.error:
        st.error(st.session_state.error)
        st.caption(
            "Tip: turn on **Demo mode** above to preview the dashboard without a backend."
        )
    elif st.session_state.result is not None:
        result = st.session_state.result
        cache_note = " · ⚡ served from cache" if result.from_cache else ""
        st.success(
            f"Audit complete ✅ (generated via **{result.generated_by}** mode{cache_note})"
        )

        # Executive summary with a ChatGPT-style typing effect (streamed once
        # per result, then cached in session state for subsequent reruns).
        st.markdown(
            '<div class="section-title">✨ Executive Summary</div>',
            unsafe_allow_html=True,
        )
        key = (result.fetched_url, result.generated_by, result.from_cache)
        if st.session_state.get("summary_key") != key:
            gen = _summary_chunks(result, st.session_state.get("stream_settings"))
            st.session_state.summary = st.write_stream(gen)
            st.session_state.summary_key = key
        else:
            st.info(st.session_state.summary)

        _render_dashboard(result)


def page_settings() -> None:
    _hero("Settings", "Configure the Ollama backend used for live audits.")

    st.markdown(
        '<div class="section-title">🤖 Ollama (Live mode)</div>', unsafe_allow_html=True
    )
    st.text_input("Ollama base URL", key="ollama_base_url")

    models = _available_models(st.session_state.ollama_base_url)
    if models is None:
        st.error(
            f"Could not reach Ollama at `{st.session_state.ollama_base_url}`. "
            "Start it with `ollama serve`, then reload this page."
        )
        st.text_input("Model", key="ollama_model")
    elif not models:
        st.warning(
            "Ollama is running but no models are installed. Pull one, e.g. `ollama pull llama3.2:3b`."
        )
        st.text_input("Model", key="ollama_model")
    else:
        st.success(
            f"Connected to Ollama · {len(models)} model(s) installed: {', '.join(models)}"
        )
        # Make sure the current selection is a valid option for the selectbox.
        current = st.session_state.ollama_model
        if current and current not in models:
            models = [current] + models
        st.selectbox("Model", options=models, key="ollama_model")

    st.caption("Mode (Demo vs Live) is chosen on the **Run Audit** page.")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(
        page_title="SEO Agent",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(theme.CSS, unsafe_allow_html=True)
    _init_state()

    page = _sidebar()
    if page == "Dashboard":
        page_dashboard()
    elif page == "Run Audit":
        page_run_audit()
    else:
        page_settings()


main()
