"""Session state, cached simulation runs, the shared workspace and small formatting helpers."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from atlas.insight import day_frames
from atlas.lab import run_lab
from atlas.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
REPO = "AkilanManivannanak/ATLAS"
PLOT = {"displayModeBar": False}
STRESS = {"baseline": "Normal day", "counterparty_delay": "A major bank pays late", "rtgs_outage": "RTGS outage",
          "liquidity_withdrawal": "Liquidity withdrawal", "funding_disruption": "Funding disruption", "haircut_shock": "Collateral haircut shock",
          "failure_to_pay": "A bank fails to pay", "concentrated_outflows": "Concentrated outflows", "liquidity_hoarding": "Banks hoard liquidity",
          "messaging_failure": "Messaging failure", "combined": "Combined stress"}
STRESS_ICON = {"baseline": ":material/check_circle:", "counterparty_delay": ":material/schedule:", "rtgs_outage": ":material/power_off:",
               "liquidity_withdrawal": ":material/water_drop:", "funding_disruption": ":material/trending_down:", "haircut_shock": ":material/content_cut:",
               "failure_to_pay": ":material/block:", "concentrated_outflows": ":material/call_split:", "liquidity_hoarding": ":material/lock:",
               "messaging_failure": ":material/wifi_off:", "combined": ":material/warning:"}
VERBS = {"joined": "joined", "ran_day": "ran a day", "ran_live_market": "ran a live-market day", "compared": "compared two responses", "uploaded": "uploaded payments",
         "asked": "asked the agent", "case_decision": "decided a case", "review": "left a review", "pinned": "pinned a baseline", "exported": "exported the workspace"}
POLICY = {"priority": "Priority queue", "fifo": "First in, first out", "bilateral": "Bilateral offsetting", "multilateral": "Multilateral netting"}
TREASURY = {"none": "Passive", "rule": "Rule-based rebalancing", "mpc": "Optimiser (MPC)"}
AUCTION = {"none": "Off", "uniform": "Uniform price", "pay_as_bid": "Pay as bid"}
PRESETS = {
    "Normal day": dict(stress="baseline", policy="priority", controller="none", auction="none", liq=18),
    "Combined stress": dict(stress="combined", policy="priority", controller="none", auction="none", liq=18),
    "Stress + optimiser": dict(stress="combined", policy="multilateral", controller="mpc", auction="uniform", liq=18),
    "Liquidity squeeze": dict(stress="liquidity_hoarding", policy="priority", controller="none", auction="none", liq=8),
    "A bank fails to pay": dict(stress="failure_to_pay", policy="priority", controller="none", auction="none", liq=18),
}
DEFAULTS = dict(banks=12, payments=1500, instant=1000, seed=11, stress="baseline", liq=18, policy="priority", controller="none", auction="none",
                shared=False, source="Synthetic day", theme="Navy & crimson", user="", csv_text=None, csv_name=None, pinned=None)


def init() -> None:
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)
    st.session_state.setdefault("_seen_runs", set())
    from datetime import UTC, datetime
    st.session_state.setdefault("_session_start", datetime.now(UTC).isoformat(timespec="seconds"))
    if not st.session_state.get("_name_from_link"):
        st.session_state._name_from_link = True
        try:
            name = (st.query_params.get("name") or "").strip()[:40]
        except Exception:  # noqa: BLE001 - older Streamlit
            name = ""
        if name and not st.session_state.user:
            st.session_state.user = name
            log("joined", {"via": "personal link"})


def usd(v: float, signed: bool = False) -> str:
    a = abs(v)
    s = (f"${a / 1e12:.2f}T" if a >= 1e12 else f"${a / 1e9:.2f}B" if a >= 1e9 else f"${a / 1e6:.2f}M" if a >= 1e6 else f"${a / 1e3:.1f}k" if a >= 1e3 else f"${a:.0f}")
    return ("−" if v < 0 else "+" if signed else "") + s


@st.cache_resource(show_spinner=False)
def _workspace(path: str, url: str) -> tuple[Workspace, str]:
    """No Streamlit calls in here: cached functions must not draw. Returns the workspace and, if the shared
    database could not be used, a reason with any credentials removed."""
    if url:
        try:
            return Workspace(url=url), ""
        except Exception as exc:  # noqa: BLE001 - a bad or unreachable database must not take the app down
            import re
            msg = re.sub(r"://[^@\s]*@", "://***@", f"{type(exc).__name__}: {exc}")
            msg = re.sub(r"password[^\s,;]*", "password=***", msg, flags=re.I)
            return Workspace(path, url=""), msg[:300]
    return Workspace(path, url=""), ""


def _db_url() -> str:
    import os
    try:
        return str(st.secrets.get("ATLAS_DB_URL", "")) or os.environ.get("ATLAS_DB_URL", "")
    except Exception:  # noqa: BLE001 - no secrets file
        return os.environ.get("ATLAS_DB_URL", "")


def workspace() -> Workspace:
    from atlas.workspace import default_path
    return _workspace(str(default_path()), _db_url())[0]


def workspace_status() -> tuple[str, str]:
    """(backend, problem) for showing on the Team page."""
    from atlas.workspace import default_path
    ws, problem = _workspace(str(default_path()), _db_url())
    return ws.backend, problem


def who() -> str:
    return (st.session_state.get("user") or "").strip() or "guest"


def log(kind: str, detail: dict | None = None) -> None:
    try:
        workspace().log(who(), kind, detail)
    except Exception:  # noqa: BLE001 - the activity log must never break the app
        pass


@st.cache_resource(show_spinner=False, max_entries=64)
def simulate(source: str, csv_text: str | None, banks: int, payments: int, instant: int, seed: int, stress: str, liq: int, policy: str,
             controller: str, auction: str, shared: bool) -> dict:
    params = dict(banks=banks, payments=payments, instant=instant, seed=seed, stress=stress, liquidity_pct=liq, policy=policy,
                  controller=controller, auction=auction, shared_master=shared)
    out = run_lab(params, csv_text if source == "My payments" else None, detail=True)
    out["_frames"] = day_frames(out["_run"])
    return out


def current(_log: bool = True, **override) -> dict:
    s = st.session_state
    a = dict(source=s.source, csv_text=s.csv_text, banks=s.banks, payments=s.payments, instant=s.instant, seed=s.seed, stress=s.stress,
             liq=s.liq, policy=s.policy, controller=s.controller, auction=s.auction, shared=s.shared) | override
    if a["source"] == "My payments" and not a["csv_text"]:
        a["source"] = "Synthetic day"
    r = simulate(**a)
    key = r["scenario"]["fingerprint"] + json.dumps(r["choices"], sort_keys=True)
    if _log and key not in s._seen_runs:
        s._seen_runs.add(key)
        log("ran_day", r["choices"] | {"liq": a["liq"], "source": a["source"], "settled_pct": r["kpis"]["settled_pct"]})
    return r


@st.cache_data(show_spinner=False)
def artifact(name: str):
    p = ROOT / "results" / name
    return json.loads(p.read_text()) if p.exists() else None


def apply(settings: dict) -> None:
    for k, v in settings.items():
        st.session_state[k] = v


def lede(text: str, tip: str | None = None) -> None:
    """One short line; detail lives in a hover tooltip, not on the page."""
    import html
    info = f' <span class="tip" title="{html.escape(tip)}">ⓘ</span>' if tip else ""
    st.markdown(f'<p class="lede">{text}{info}</p>', unsafe_allow_html=True)


def eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{text}</div>', unsafe_allow_html=True)


def badges(r: dict) -> None:
    """One compact row; the technical detail is in the hover title."""
    import html
    i, s = r["integrity"], r["scenario"]
    ss = st.session_state
    tip = html.escape(f"state hash {i['state_hash']} · {i['events']:,} ledger events in {i['runtime_s']}s · data {r['data_origin']}")
    ok = i["replay_verified"]
    st.markdown(
        f'<span class="tag {"ok" if ok else "no"}" title="{tip}"><b>{"✓ replay verified" if ok else "✗ replay failed"}</b></span>'
        f'<span class="tag">Scenario <b>{STRESS[ss.stress]}</b></span><span class="tag">Liquidity <b>{ss.liq}%</b></span>'
        f'<span class="tag"><b>{s["institutions"]}</b> banks · <b>{s["payments"]:,}</b> payments · <b>{usd(s["value_usd"])}</b></span>'
        + ('<span class="tag">Baseline <b>pinned</b></span>' if ss.pinned else ""), unsafe_allow_html=True)


def kpi_items(r: dict, base: dict | None) -> list[dict]:
    k, b = r["kpis"], (base or {}).get("kpis") or {}
    settled_edge = "good" if k["settled_pct"] >= 99 else "warn" if k["settled_pct"] >= 95 else "bad"
    return [dict(label="Large-value settled", value=k["settled_pct"], fmt="pct", edge=settled_edge, base=b.get("settled_pct")),
            dict(label="Average delay", value=k["delay_min"], fmt="min", edge="p", low=True, base=b.get("delay_min")),
            dict(label="Left unsettled", value=k["unsettled_usd"], fmt="usd", edge="bad" if k["unsettled_usd"] > 0 else "good", low=True, base=b.get("unsettled_usd")),
            dict(label="Instant payments rejected", value=k["instant_rejected"], fmt="int", edge="a", low=True, base=b.get("instant_rejected")),
            dict(label="Peak intraday credit", value=k["peak_credit_usd"], fmt="usd", edge="p", low=True, base=b.get("peak_credit_usd")),
            dict(label="Cost of the day", value=k["cost_usd"], fmt="usd", edge="a", low=True, base=b.get("cost_usd"))]
