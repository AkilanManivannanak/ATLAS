"""ATLAS-Σ interactive app (Streamlit).

    pip install -r requirements.txt && streamlit run streamlit_app.py

Deploys as-is on Streamlit Community Cloud (entry point: this file). Every figure is computed live by the simulator in
``src/atlas``, read from the New York Fed and US Treasury public APIs, or read from ``results/``. Nothing is mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from atlas_app import pages as P  # noqa: E402
from atlas_app.state import AUCTION, POLICY, STRESS, TREASURY, init, log  # noqa: E402
from atlas_app.theme import THEMES, inject_css  # noqa: E402

st.set_page_config(page_title="ATLAS-Σ · settlement and liquidity", page_icon="🏛️", layout="wide", initial_sidebar_state="expanded")
init()
inject_css()


def _named() -> None:
    if st.session_state.user.strip():
        log("joined", {})


def sidebar() -> None:
    s = st.session_state
    with st.sidebar:
        st.markdown("<div style='font-weight:700;font-size:1.15rem;color:var(--p)'>ATLAS-Σ</div>"
                    "<div style='color:#8A93A8;font-size:.78rem;margin-bottom:.6rem'>Settlement and liquidity, on live markets</div>",
                    unsafe_allow_html=True)
        st.text_input("Your name", key="user", placeholder="so your team sees your work", on_change=_named)
        with st.expander("The day", expanded=False):
            st.radio("Data", ["Synthetic day", "My payments"], key="source", horizontal=True)
            if s.source == "Synthetic day":
                st.slider("Banks", 6, 24, key="banks")
                st.slider("Large-value payments", 300, 4000, step=100, key="payments")
                st.slider("Instant payments", 0, 3000, step=100, key="instant")
                st.number_input("Day (random seed)", 0, 99999, key="seed")
            elif not s.csv_text:
                st.caption("No file yet: add one on **Your payments**.")
            st.selectbox("What goes wrong", list(STRESS), format_func=STRESS.get, key="stress")
            st.slider("Opening liquidity, % of outflow", 4, 40, key="liq")
        with st.expander("The response", expanded=False):
            st.selectbox("Queue policy", list(POLICY), format_func=POLICY.get, key="policy")
            st.selectbox("Bank treasury", list(TREASURY), format_func=TREASURY.get, key="controller")
            st.selectbox("Liquidity auction", list(AUCTION), format_func=AUCTION.get, key="auction")
            st.toggle("FedNow shares the Fed master account", key="shared")
        st.selectbox("Colours", list(THEMES), key="theme")
        st.caption("Simulated banks · cannot move money")


pages = {
    "overview": st.Page(P.page_overview, title="Command center", icon="🏛️", default=True, url_path="overview"),
    "markets": st.Page(P.page_markets, title="Live market", icon="📈", url_path="market"),
    "stress": st.Page(P.page_stress, title="Stress lab", icon="🧪", url_path="stress"),
    "upload": st.Page(P.page_upload, title="Your payments", icon="📄", url_path="your-payments"),
    "alerts": st.Page(P.page_alerts, title="Alerts & cases", icon="🗂️", url_path="alerts"),
    "controls": st.Page(P.page_controls, title="Controls", icon="🛡️", url_path="controls"),
    "models": st.Page(P.page_models, title="Model risk", icon="⚖️", url_path="model-risk"),
    "agent": st.Page(P.page_agent, title="Agent", icon="🤖", url_path="agent"),
    "evidence": st.Page(P.page_evidence, title="Evidence", icon="📊", url_path="evidence"),
    "team": st.Page(P.page_team, title="Team", icon="👥", url_path="team"),
}
st.session_state["_pages"] = pages
nav = st.navigation({"Operate": [pages[k] for k in ("overview", "markets", "stress", "upload")],
                     "Risk": [pages[k] for k in ("alerts", "controls", "models")],
                     "Explain": [pages[k] for k in ("agent", "evidence", "team")]}, position="sidebar")
sidebar()
nav.run()
st.markdown("<div style='margin-top:2.5rem;color:#8A93A8;font-size:.8rem'>ATLAS-Σ · "
            "<a href='https://github.com/AkilanManivannanak/ATLAS' style='color:inherit'>code on GitHub</a> · market data: Federal Reserve Bank of New York, US Treasury</div>",
            unsafe_allow_html=True)
