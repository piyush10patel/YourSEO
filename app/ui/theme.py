"""Visual theme: CSS + small HTML component builders for the Streamlit UI.

Keeping the markup here keeps `streamlit_app.py` readable. All HTML is static
or fed from our own typed data (no user HTML), so `unsafe_allow_html=True` is
safe here.
"""

from __future__ import annotations

import html

# Brand palette
PRIMARY = "#6C5CE7"  # violet
PRIMARY_DARK = "#4834d4"
ACCENT = "#00CEC9"  # teal
INK = "#1e2235"
MUTED = "#8a90a6"
BG_CARD = "#ffffff"

CSS = f"""
<style>
/* ---- App shell ---- */
.stApp {{
    background: #f4f6fb;
}}
#MainMenu, footer {{ visibility: hidden; }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1200px; }}

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {PRIMARY_DARK} 0%, {PRIMARY} 100%);
}}
section[data-testid="stSidebar"] * {{ color: #ffffff !important; }}
.sidebar-brand {{
    font-size: 1.35rem; font-weight: 800; letter-spacing: -0.02em;
    display: flex; align-items: center; gap: .5rem; margin: .2rem 0 .2rem 0;
}}
.sidebar-brand .logo {{
    background: rgba(255,255,255,.18); border-radius: 10px;
    width: 34px; height: 34px; display: inline-flex; align-items: center;
    justify-content: center; font-size: 1.1rem;
}}
.sidebar-tag {{ font-size: .78rem; opacity: .8; margin-bottom: 1.2rem; }}
section[data-testid="stSidebar"] .stRadio label {{
    padding: .35rem 0; font-weight: 600;
}}

/* ---- Hero header ---- */
.hero {{
    background: linear-gradient(120deg, {PRIMARY} 0%, {PRIMARY_DARK} 55%, {ACCENT} 160%);
    border-radius: 18px; padding: 1.6rem 1.8rem; color: #fff;
    box-shadow: 0 12px 30px rgba(72,52,212,.25); margin-bottom: 1.6rem;
}}
.hero h1 {{ font-size: 1.7rem; font-weight: 800; margin: 0; letter-spacing: -.02em; }}
.hero p {{ margin: .35rem 0 0; opacity: .9; font-size: .95rem; }}

/* ---- Metric cards ---- */
.metric-card {{
    background: {BG_CARD}; border-radius: 16px; padding: 1.1rem 1.25rem;
    box-shadow: 0 6px 18px rgba(30,34,53,.06); border: 1px solid #eef1f7;
    height: 100%;
}}
.metric-card .label {{
    color: {MUTED}; font-size: .8rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .04em;
}}
.metric-card .value {{ color: {INK}; font-size: 2rem; font-weight: 800; line-height: 1.1; margin-top: .2rem; }}
.metric-card .sub {{ color: {MUTED}; font-size: .82rem; margin-top: .15rem; }}
.metric-card .value .unit {{ font-size: 1rem; color: {MUTED}; font-weight: 600; }}

/* ---- Score donut ---- */
.score-wrap {{ display: flex; align-items: center; gap: 1.4rem; }}
.score-donut {{
    width: 132px; height: 132px; border-radius: 50%; flex: 0 0 auto;
    display: flex; align-items: center; justify-content: center;
}}
.score-donut-inner {{
    width: 100px; height: 100px; border-radius: 50%; background: {BG_CARD};
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    box-shadow: inset 0 0 0 1px #eef1f7;
}}
.score-num {{ font-size: 2.1rem; font-weight: 800; color: {INK}; line-height: 1; }}
.score-grade {{ font-size: .8rem; font-weight: 700; color: {MUTED}; margin-top: .15rem; }}

/* ---- Section titles ---- */
.section-title {{
    font-size: 1.15rem; font-weight: 800; color: {INK}; margin: 1.6rem 0 .8rem;
    display: flex; align-items: center; gap: .5rem;
}}

/* ---- Generic card ---- */
.card {{
    background: {BG_CARD}; border-radius: 14px; padding: 1rem 1.15rem;
    box-shadow: 0 4px 14px rgba(30,34,53,.05); border: 1px solid #eef1f7;
    margin-bottom: .7rem;
}}
.card .card-title {{ font-weight: 700; color: {INK}; font-size: .98rem; }}
.card .card-body {{ color: #4a5066; font-size: .9rem; margin-top: .25rem; line-height: 1.45; }}

/* ---- Badges ---- */
.badge {{
    display: inline-block; padding: .18rem .6rem; border-radius: 999px;
    font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
}}
.badge-high {{ background: #ffe3e3; color: #c92a2a; }}
.badge-medium {{ background: #fff3bf; color: #b08900; }}
.badge-low {{ background: #d3f9d8; color: #2b8a3e; }}
.badge-keyword {{ background: #eae6ff; color: {PRIMARY_DARK}; }}

/* ---- Meta description box ---- */
.meta-box {{
    background: linear-gradient(180deg,#faf9ff,#f3f0ff); border: 1px dashed {PRIMARY};
    border-radius: 14px; padding: 1rem 1.15rem; color: {INK}; font-size: .95rem;
    line-height: 1.5;
}}
.meta-old {{ color: {MUTED}; text-decoration: line-through; font-size: .85rem; }}
</style>
"""


def _grade_color(score: int) -> str:
    if score >= 80:
        return "#2b8a3e"
    if score >= 60:
        return "#e8a700"
    return "#c92a2a"


def score_donut(score: int, grade: str) -> str:
    color = _grade_color(score)
    return f"""
    <div class="score-donut" style="background: conic-gradient({color} 0% {score}%, #e8ecf4 {score}% 100%);">
      <div class="score-donut-inner">
        <span class="score-num" style="color:{color}">{score}</span>
        <span class="score-grade">GRADE {html.escape(grade)}</span>
      </div>
    </div>
    """


def metric_card(label: str, value: str, sub: str = "", unit: str = "") -> str:
    unit_html = f' <span class="unit">{html.escape(unit)}</span>' if unit else ""
    sub_html = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
    return f"""
    <div class="metric-card">
      <div class="label">{html.escape(label)}</div>
      <div class="value">{html.escape(value)}{unit_html}</div>
      {sub_html}
    </div>
    """


def keyword_gap_card(keyword: str, rationale: str) -> str:
    return f"""
    <div class="card">
      <div class="card-title"><span class="badge badge-keyword">Opportunity</span>&nbsp; {html.escape(keyword)}</div>
      <div class="card-body">{html.escape(rationale)}</div>
    </div>
    """


def fix_card(issue: str, recommendation: str, severity: str) -> str:
    sev = (
        severity.lower() if severity.lower() in ("high", "medium", "low") else "medium"
    )
    return f"""
    <div class="card">
      <div class="card-title"><span class="badge badge-{sev}">{html.escape(severity)}</span>&nbsp; {html.escape(issue)}</div>
      <div class="card-body">{html.escape(recommendation)}</div>
    </div>
    """


def meta_box(old: str | None, new: str) -> str:
    old_html = f'<div class="meta-old">Before: {html.escape(old)}</div>' if old else ""
    return f"""
    <div class="meta-box">
      {old_html}
      <div style="margin-top:.35rem;"><b>{html.escape(new)}</b></div>
      <div style="color:{MUTED};font-size:.78rem;margin-top:.4rem;">{len(new)} characters</div>
    </div>
    """
