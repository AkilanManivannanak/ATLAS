"""Light themes in the colour families of large US banks (no logos, names or marks), shared CSS and chart styling."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

BASE = {"bg": "#F5F7FB", "card": "#FFFFFF", "ink": "#0E1A33", "ink2": "#46526B", "muted": "#8A93A8", "line": "#E2E7F0",
        "good": "#13804F", "warn": "#C77A00", "bad": "#C8102E", "soft": "#EEF2F9"}
THEMES = {
    "Navy & crimson": {"primary": "#012169", "accent": "#E31837", "accent2": "#5B7FC4", "accent3": "#9AA9C7", "deep": "#00134A"},
    "Ocean & bronze": {"primary": "#0B4F8A", "accent": "#A8763E", "accent2": "#3C8DD8", "accent3": "#B9C7D8", "deep": "#06325A"},
    "Crimson & gold": {"primary": "#A6192E", "accent": "#E0A100", "accent2": "#D9636F", "accent3": "#D8C7A0", "deep": "#6E0F1F"},
}


def palette() -> dict:
    name = st.session_state.get("theme", "Navy & crimson")
    return BASE | THEMES.get(name, THEMES["Navy & crimson"])


def inject_css() -> None:
    p = palette()
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root{{--p:{p['primary']};--a:{p['accent']};--ink:{p['ink']};--ink2:{p['ink2']};--muted:{p['muted']};--line:{p['line']};--card:{p['card']};--soft:{p['soft']}}}
html,body,[class*="css"],.stMarkdown,.stButton button,input,textarea,select{{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}}
.stApp{{background:{p['bg']}}}
.block-container{{padding-top:2.0rem;max-width:1280px}}
section[data-testid="stSidebar"]{{background:#FFFFFF;border-right:1px solid var(--line)}}
h1{{color:var(--p)!important;font-weight:700!important;letter-spacing:-.025em;font-size:2.3rem!important;margin-bottom:.1rem!important}}
h2,h3,h4{{color:var(--ink)!important;font-weight:600!important;letter-spacing:-.01em}}
.lede{{color:var(--ink2);font-size:1.02rem;margin:-.1rem 0 1.0rem;max-width:880px}}
.eyebrow{{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:1.2rem 0 .4rem}}
.tag{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 11px;margin:0 6px 6px 0;font-size:.78rem;color:var(--ink2);background:#fff}}
.tag b{{color:var(--ink);font-weight:600}}.tag.ok{{border-color:#BFE3CF}}.tag.ok b{{color:{p['good']}}}.tag.no{{border-color:#F3C0C8}}.tag.no b{{color:{p['bad']}}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:10px}}
.card .k{{font-family:'JetBrains Mono',monospace;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
.card .v{{font-size:1.9rem;font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums;line-height:1.15}}
.card .s{{font-size:.82rem;color:var(--ink2)}}
.edge-good{{border-left:4px solid {p['good']}}}.edge-warn{{border-left:4px solid {p['warn']}}}.edge-bad{{border-left:4px solid {p['bad']}}}.edge-p{{border-left:4px solid var(--p)}}.edge-a{{border-left:4px solid var(--a)}}
.cite{{border-left:3px solid var(--p);padding:6px 12px;margin:6px 0;background:var(--soft);border-radius:0 8px 8px 0;font-size:.9rem;color:var(--ink)}}
.stButton>button,.stDownloadButton>button,.stLinkButton>a{{border-radius:999px!important;border:1px solid var(--line)!important;font-weight:500}}
.stButton>button[kind="primary"],.stLinkButton>a[kind="primary"]{{background:var(--p)!important;border-color:var(--p)!important;color:#fff!important}}
.stButton>button:hover{{border-color:var(--p)!important;color:var(--p)!important}}
.stButton>button[kind="primary"]:hover{{color:#fff!important;filter:brightness(1.15)}}
div[data-testid="stMetric"]{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--p);border-radius:12px;padding:10px 14px}}
div[data-testid="stMetricValue"]{{font-weight:600;font-variant-numeric:tabular-nums;color:var(--ink)}}
div[data-testid="stMetricLabel"] p{{font-family:'JetBrains Mono',monospace;font-size:.7rem!important;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)!important}}
.stTabs [data-baseweb="tab-list"]{{gap:4px}}
.stTabs [data-baseweb="tab"]{{border-radius:999px;padding:6px 14px;background:#fff;border:1px solid var(--line)}}
.stTabs [aria-selected="true"]{{background:var(--p)!important;color:#fff!important;border-color:var(--p)}}
.stTabs [aria-selected="true"] p{{color:#fff!important}}
div[data-testid="stExpander"]{{background:#fff;border-radius:12px}}
</style>""", unsafe_allow_html=True)


def layout(fig: go.Figure, height: int = 300, **kw) -> go.Figure:
    p = palette()
    title = kw.pop("title", None)
    if isinstance(title, str):
        title = dict(text=title, font=dict(size=14, color=p["ink"]), x=0, xanchor="left")
    fig.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=height, title=title,
                      margin=dict(l=8, r=8, t=kw.pop("t", 40 if title else 16), b=kw.pop("b", 8)), font=dict(family="Inter, system-ui, sans-serif", color=p["ink2"], size=12),
                      colorway=[p["primary"], p["accent"], p["accent2"], p["accent3"], p["good"]],
                      legend=dict(orientation="h", y=1.1, x=1, xanchor="right", bgcolor="rgba(0,0,0,0)"),
                      hoverlabel=dict(bgcolor="#fff", bordercolor=p["line"], font=dict(color=p["ink"])), **kw)
    fig.update_xaxes(gridcolor=p["line"], zerolinecolor=p["line"], linecolor=p["line"])
    fig.update_yaxes(gridcolor=p["line"], zerolinecolor=p["line"], linecolor=p["line"])
    return fig


def rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"
