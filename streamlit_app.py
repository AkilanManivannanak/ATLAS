"""ATLAS-Σ interactive app (Streamlit).

    pip install -r requirements.txt && streamlit run streamlit_app.py

Deploys as-is on Streamlit Community Cloud (entry point: this file). Everything shown is computed live by the
simulator in ``src/atlas`` or read from ``results/``; nothing is mocked.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from atlas import __version__  # noqa: E402
from atlas.insight import bank_detail, day_frames, liquidity_sweep, review_url, tamper_check  # noqa: E402
from atlas.lab import run_lab  # noqa: E402

REPO = "AkilanManivannanak/ATLAS"
C = {"blue": "#3987e5", "orange": "#eb6834", "green": "#1baf7a", "red": "#e66767", "grey": "#8b8a84", "ink": "#f0efec", "ink2": "#b9b8b0",
     "line": "#2c2d31", "panel": "#18191d", "violet": "#9a74e0"}
STRESS = {"baseline": "Normal day", "counterparty_delay": "A major bank pays late", "rtgs_outage": "RTGS outage",
          "liquidity_withdrawal": "Liquidity withdrawal", "funding_disruption": "Funding disruption", "haircut_shock": "Collateral haircut shock",
          "failure_to_pay": "A bank fails to pay", "concentrated_outflows": "Concentrated outflows", "liquidity_hoarding": "Banks hoard liquidity",
          "messaging_failure": "Messaging failure", "combined": "Combined stress"}
POLICY = {"priority": "Priority queue", "fifo": "First in, first out", "bilateral": "Bilateral offsetting", "multilateral": "Multilateral netting"}
TREASURY = {"none": "Passive", "rule": "Rule-based rebalancing", "mpc": "Optimiser (MPC)"}
AUCTION = {"none": "Off", "uniform": "Uniform price", "pay_as_bid": "Pay as bid"}
PRESETS = {
    "Normal day": dict(stress="baseline", policy="priority", controller="none", auction="none", liq=18),
    "Combined stress": dict(stress="combined", policy="priority", controller="none", auction="none", liq=18),
    "Stress + optimiser + auction": dict(stress="combined", policy="multilateral", controller="mpc", auction="uniform", liq=18),
    "Liquidity squeeze": dict(stress="liquidity_hoarding", policy="priority", controller="none", auction="none", liq=8),
    "A bank fails to pay": dict(stress="failure_to_pay", policy="priority", controller="none", auction="none", liq=18),
}
DEFAULTS = dict(banks=12, payments=1500, instant=1000, seed=11, stress="baseline", liq=18, policy="priority", controller="none", auction="none",
                shared=False, source="Synthetic day")

st.set_page_config(page_title="ATLAS-Σ", page_icon="🏦", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{padding-top:2.2rem;max-width:1320px}
h1{font-weight:300;letter-spacing:-.02em;font-size:2.6rem!important;margin-bottom:.2rem}
h2,h3{font-weight:500;letter-spacing:-.01em}
.lede{color:#b9b8b0;font-size:1.05rem;margin:-.2rem 0 1.1rem;max-width:860px}
.tag{display:inline-block;border:1px solid #2c2d31;border-radius:999px;padding:3px 11px;margin:0 6px 6px 0;font-size:.8rem;color:#b9b8b0;background:#18191d}
.tag b{color:#f0efec;font-weight:600}.tag.ok b{color:#3fbf8f}.tag.no b{color:#e66767}
.verdict{border-radius:16px;padding:18px 20px;color:#0f1013}.verdict .n{font-size:2.6rem;font-weight:300;line-height:1.05;font-variant-numeric:tabular-nums}
.verdict .l{font-size:.85rem;opacity:.85}.cite{border-left:3px solid #3987e5;padding:6px 12px;margin:6px 0;background:#18191d;border-radius:0 8px 8px 0;font-size:.9rem}
div[data-testid="stMetricValue"]{font-weight:300;font-variant-numeric:tabular-nums}
</style>""", unsafe_allow_html=True)

for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)
st.session_state.setdefault("csv_text", None)
st.session_state.setdefault("csv_name", None)
st.session_state.setdefault("pinned", None)


# ------------------------------------------------------------------ helpers
def usd(v: float, signed: bool = False) -> str:
    a = abs(v)
    s = f"${a / 1e9:.2f}B" if a >= 1e9 else f"${a / 1e6:.2f}M" if a >= 1e6 else f"${a / 1e3:.1f}k" if a >= 1e3 else f"${a:.0f}"
    return ("−" if v < 0 else "+" if signed else "") + s


def layout(fig: go.Figure, height: int = 300, **kw) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=height,
                      margin=dict(l=10, r=10, t=kw.pop("t", 30), b=kw.pop("b", 10)), font=dict(color=C["ink2"], size=12),
                      legend=dict(orientation="h", y=1.12, x=1, xanchor="right", bgcolor="rgba(0,0,0,0)"), hoverlabel=dict(bgcolor=C["panel"]), **kw)
    fig.update_xaxes(gridcolor=C["line"], zerolinecolor=C["line"])
    fig.update_yaxes(gridcolor=C["line"], zerolinecolor=C["line"])
    return fig


PLOT = {"displayModeBar": False}


@st.cache_resource(show_spinner=False, max_entries=48)
def simulate(source: str, csv_text: str | None, banks: int, payments: int, instant: int, seed: int, stress: str, liq: int, policy: str,
             controller: str, auction: str, shared: bool) -> dict:
    params = dict(banks=banks, payments=payments, instant=instant, seed=seed, stress=stress, liquidity_pct=liq, policy=policy,
                  controller=controller, auction=auction, shared_master=shared)
    out = run_lab(params, csv_text if source == "My payments" else None, detail=True)
    out["_frames"] = day_frames(out["_run"])
    return out


def current(**override) -> dict:
    s = st.session_state
    a = dict(source=s.source, csv_text=s.csv_text, banks=s.banks, payments=s.payments, instant=s.instant, seed=s.seed, stress=s.stress,
             liq=s.liq, policy=s.policy, controller=s.controller, auction=s.auction, shared=s.shared) | override
    if a["source"] == "My payments" and not a["csv_text"]:
        a["source"] = "Synthetic day"
    return simulate(**a)


@st.cache_data(show_spinner=False)
def artifact(name: str):
    p = ROOT / "results" / name
    return json.loads(p.read_text()) if p.exists() else None


def _embed(html: str, height: int) -> None:
    """Self-authored HTML with a little script (the count-up). ``st.iframe`` on current Streamlit, the older component otherwise."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:  # Streamlit < 1.55
        import streamlit.components.v1 as components
        components.html(html, height=height)


def kpi_strip(r: dict, base: dict | None) -> None:
    """Six large figures that count up on every run, with the change against the pinned baseline."""
    k, b = r["kpis"], (base or {}).get("kpis")
    tiles = [("Large-value settled", k["settled_pct"], "pct", False, b and b["settled_pct"]),
             ("Average delay", k["delay_min"], "min", True, b and b["delay_min"]),
             ("Left unsettled", k["unsettled_usd"], "usd", True, b and b["unsettled_usd"]),
             ("Instant payments rejected", k["instant_rejected"], "int", True, b and b["instant_rejected"]),
             ("Peak intraday credit", k["peak_credit_usd"], "usd", True, b and b["peak_credit_usd"]),
             ("Cost of the day", k["cost_usd"], "usd", True, b and b["cost_usd"])]
    data = json.dumps([{"l": t[0], "v": t[1], "f": t[2], "low": t[3], "b": t[4]} for t in tiles])
    _embed(f"""<div id="k"></div><style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#f0efec;background:transparent}}
#k{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}
@media(max-width:520px){{#k{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
.t{{background:#18191d;border:1px solid #2c2d31;border-radius:14px;padding:13px 14px;animation:rise .35s ease-out both}}
.l{{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#b9b8b0}}.v{{font-size:34px;font-weight:300;line-height:1.2;font-variant-numeric:tabular-nums;white-space:nowrap}}@media(max-width:520px){{.v{{font-size:24px}}}}
.d{{font-size:12px;font-variant-numeric:tabular-nums;color:#b9b8b0;min-height:16px}}.good{{color:#3fbf8f}}.bad{{color:#e66767}}
@keyframes rise{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}@media(prefers-reduced-motion:reduce){{.t{{animation:none}}}}</style>
<script>const T={data};const usd=v=>{{const a=Math.abs(v);return (v<0?'−':'')+'$'+(a>=1e9?(a/1e9).toFixed(2)+'B':a>=1e6?(a/1e6).toFixed(2)+'M':a>=1e3?(a/1e3).toFixed(1)+'k':a.toFixed(0))}};
const F={{pct:v=>v.toFixed(2)+'%',min:v=>v.toFixed(1)+' min',usd,int:v=>Math.round(v).toLocaleString()}};const D={{pct:v=>v.toFixed(2)+' pp',min:v=>v.toFixed(1)+' min',usd,int:v=>Math.round(v).toLocaleString()}};
const k=document.getElementById('k');T.forEach((t,i)=>{{const e=document.createElement('div');e.className='t';e.style.animationDelay=(i*40)+'ms';let d='';
if(t.b!==null&&t.b!==undefined&&t.b!==false){{const x=t.v-t.b;if(Math.abs(x)<1e-9)d='same as baseline';else{{const g=t.low?x<0:x>0;d='<span class="'+(g?'good':'bad')+'">'+(x>0?'▲ ':'▼ ')+D[t.f](Math.abs(x))+'</span> vs baseline'}}}}
e.innerHTML='<div class="l">'+t.l+'</div><div class="v">'+F[t.f](0)+'</div><div class="d">'+d+'</div>';k.appendChild(e);
const el=e.querySelector('.v'),still=matchMedia('(prefers-reduced-motion: reduce)').matches,t0=performance.now(),dur=700;
const step=n=>{{const f=still?1:Math.min(1,(n-t0)/dur),z=1-Math.pow(1-f,3);el.textContent=F[t.f](t.v*z);if(f<1)requestAnimationFrame(step)}};requestAnimationFrame(step)}});</script>""",
           height=236)


def badges(r: dict) -> None:
    i, s = r["integrity"], r["scenario"]
    origin = "your file" if r["data_origin"] == "user_supplied" else "synthetic"
    st.markdown(
        f'<span class="tag {"ok" if i["replay_verified"] else "no"}">Ledger replay <b>{"verified ✓" if i["replay_verified"] else "FAILED"}</b></span>'
        f'<span class="tag">State hash <b>{i["state_hash"][:12]}…</b></span>'
        f'<span class="tag"><b>{s["institutions"]}</b> banks · <b>{s["payments"]:,}</b> payments · <b>{usd(s["value_usd"])}</b></span>'
        f'<span class="tag"><b>{i["events"]:,}</b> ledger events in <b>{i["runtime_s"]}s</b></span><span class="tag">Data <b>{origin}</b></span>'
        + ('<span class="tag">Baseline <b>pinned</b></span>' if st.session_state.pinned else ""), unsafe_allow_html=True)


def network_figure(f: dict) -> go.Figure:
    """Animated day: banks on a ring (core banks inside), coloured by how much of their available liquidity is stuck
    in unsettled outgoing payments; lines are the largest flows settled in each half hour."""
    n = len(f["banks"])
    core = [i for i, t in enumerate(f["tiers"]) if t == "core"]
    peri = [i for i in range(n) if i not in core]
    pos = {}
    for ring, radius in ((core, 0.38), (peri, 1.0)):
        for k, i in enumerate(ring):
            a = 2 * math.pi * k / max(1, len(ring)) + (0.4 if ring is core else 0)
            pos[i] = (radius * math.cos(a), radius * math.sin(a))
    idx = {b: i for i, b in enumerate(f["banks"])}
    top = max(f["sent_minor"]) or 1
    size = [16 + 34 * math.sqrt(v / top) for v in f["sent_minor"]]
    max_flow = max([fl["minor"] for fr in f["flows"] for fl in fr] or [1])
    edges = max(len(fr) for fr in f["flows"]) or 1
    xs, ys = [pos[i][0] for i in range(n)], [pos[i][1] for i in range(n)]

    def frame_traces(t: int) -> list:
        tr = []
        fl = f["flows"][t]
        for e in range(edges):
            if e < len(fl):
                a, b = pos[idx[fl[e]["from"]]], pos[idx[fl[e]["to"]]]
                tr.append(go.Scatter(x=[a[0], b[0]], y=[a[1], b[1]], mode="lines", hoverinfo="skip", xaxis="x", yaxis="y",
                                     line=dict(width=1 + 9 * fl[e]["minor"] / max_flow, color="rgba(57,135,229,0.55)")))
            else:
                tr.append(go.Scatter(x=[None], y=[None], mode="lines", hoverinfo="skip", xaxis="x", yaxis="y", line=dict(width=0)))
        stuck = [min(1.5, f["queued_minor"][t][i] / max(1, f["available_minor"][i])) for i in range(n)]
        tr.append(go.Scatter(
            x=xs, y=ys, mode="markers+text", text=[b.replace("bank-", "") for b in f["banks"]], textfont=dict(size=10, color="#0f1013"),
            customdata=[[f["banks"][i], f["queued_minor"][t][i] / 100, f["net_minor"][t][i] / 100, f["tiers"][i]] for i in range(n)],
            hovertemplate="<b>%{customdata[0]}</b> (%{customdata[3]})<br>waiting to send: %{customdata[1]:$,.3s}<br>net position: %{customdata[2]:$,.3s}<extra></extra>",
            marker=dict(size=size, color=stuck, cmin=0, cmax=1.2, colorscale=[[0, "#3fbf8f"], [0.35, "#e8d27a"], [0.7, "#eb6834"], [1, "#e34948"]],
                        line=dict(width=1.5, color="#0f1013"), showscale=False),
            xaxis="x", yaxis="y"))
        tr.append(go.Scatter(x=f["labels"][:t + 1], y=[v / 100 for v in f["queued_total_minor"][:t + 1]], mode="lines", name="Waiting to settle",
                             line=dict(color=C["orange"], width=3), fill="tozeroy", fillcolor="rgba(235,104,52,0.15)", xaxis="x2", yaxis="y2",
                             hovertemplate="%{x}: %{y:$,.3s} waiting<extra></extra>"))
        tr.append(go.Scatter(x=f["labels"][:t + 1], y=[v / 100 for v in f["settled_cum_minor"][:t + 1]], mode="lines", name="Settled so far",
                             line=dict(color=C["green"], width=3), xaxis="x3", yaxis="y3", hovertemplate="%{x}: %{y:$,.3s} settled<extra></extra>"))
        return tr

    T = len(f["labels"])
    fig = make_subplots(rows=2, cols=2, column_widths=[0.5, 0.5], specs=[[{"rowspan": 2}, {}], [None, {}]], horizontal_spacing=0.1, vertical_spacing=0.16,
                        subplot_titles=("", "Waiting to settle", "Settled so far"))
    t0 = max(range(T), key=lambda t: f["queued_total_minor"][t])          # open on the most congested half hour
    for tr in frame_traces(t0):
        fig.add_trace(tr)
    fig.frames = [go.Frame(data=frame_traces(t), name=f["labels"][t]) for t in range(T)]
    fig.update_layout(
        xaxis=dict(visible=False, range=[-1.25, 1.25], domain=[0, 0.44]), yaxis=dict(visible=False, range=[-1.2, 1.2], scaleanchor="x"),
        xaxis2=dict(range=[-0.5, T - 0.5], type="category", categoryorder="array", categoryarray=f["labels"], nticks=6),
        yaxis2=dict(range=[0, max(f["queued_total_minor"]) / 100 * 1.1 or 1], tickformat="$.2s"),
        xaxis3=dict(range=[-0.5, T - 0.5], type="category", categoryorder="array", categoryarray=f["labels"], nticks=6),
        yaxis3=dict(range=[0, (f["settled_cum_minor"][-1] or 1) / 100 * 1.05], tickformat="$.2s"), showlegend=False,
        updatemenus=[dict(type="buttons", direction="left", x=0.0, y=-0.06, xanchor="left", yanchor="top", pad=dict(t=4, r=8), bgcolor="#e8e7e2",
                          font=dict(color="#0f1013"), buttons=[
                              dict(label="▶  Play the day", method="animate", args=[None, dict(frame=dict(duration=420, redraw=True), transition=dict(duration=200), fromcurrent=False)]),
                              dict(label="❚❚", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
        sliders=[dict(active=t0, x=0.22, len=0.78, y=-0.04, pad=dict(t=0), currentvalue=dict(prefix="Time (ET): ", font=dict(size=13, color="#f0efec")),
                      steps=[dict(method="animate", label=f["labels"][t], args=[[f["labels"][t]], dict(mode="immediate", frame=dict(duration=0, redraw=True))]) for t in range(T)])])
    return layout(fig, height=520, t=30, b=70)


# ------------------------------------------------------------------ sidebar: the day and the response
def sidebar() -> None:
    s = st.session_state
    with st.sidebar:
        st.markdown(f"### ATLAS-Σ <span style='color:#8b8a84;font-size:.8rem'>v{__version__}</span>", unsafe_allow_html=True)
        st.caption("Interbank settlement, simulated. Not connected to any real payment system.")
        st.radio("Data", ["Synthetic day", "My payments"], key="source", horizontal=True)
        if s.source == "My payments":
            if s.csv_text:
                st.success(f"{s.csv_name}", icon="📄")
            else:
                st.info("No file yet. Add one on the **Your payments** page.", icon="📄")
        else:
            st.slider("Banks", 6, 24, key="banks")
            st.slider("Large-value payments", 300, 4000, step=100, key="payments")
            st.slider("Instant payments", 0, 3000, step=100, key="instant")
            st.number_input("Day (random seed)", 0, 99999, key="seed")
        st.divider()
        st.selectbox("What goes wrong", list(STRESS), format_func=STRESS.get, key="stress")
        st.slider("Opening liquidity, % of each bank's outflow", 4, 40, key="liq")
        st.divider()
        st.selectbox("Queue policy", list(POLICY), format_func=POLICY.get, key="policy")
        st.selectbox("Bank treasury", list(TREASURY), format_func=TREASURY.get, key="controller")
        st.selectbox("Interbank liquidity auction", list(AUCTION), format_func=AUCTION.get, key="auction")
        st.toggle("FedNow shares the Fed master account", key="shared", help="As in reality: FedNow settles in the same account as Fedwire.")


def apply_preset(name: str) -> None:
    for k, v in PRESETS[name].items():
        st.session_state[k] = v


# ------------------------------------------------------------------ pages
def page_live() -> None:
    st.title("One settlement day")
    st.markdown('<p class="lede">A network of banks sends each other payments over four rails. Pick what goes wrong and how the system responds, '
                'then play the day.</p>', unsafe_allow_html=True)
    cols = st.columns(len(PRESETS))
    for c, name in zip(cols, PRESETS):
        c.button(name, on_click=apply_preset, args=(name,), width="stretch")
    with st.spinner("Simulating the day…"):
        r = current()
    badges(r)
    kpi_strip(r, st.session_state.pinned)
    a, b, _ = st.columns([1, 1, 4])
    if a.button("📌 Pin as baseline", width="stretch", help="Later runs show their difference against this one."):
        st.session_state.pinned = {"kpis": r["kpis"], "series": r["series"], "choices": r["choices"]}
        st.rerun()
    if st.session_state.pinned and b.button("Clear baseline", width="stretch"):
        st.session_state.pinned = None
        st.rerun()

    f = r["_frames"]
    st.plotly_chart(network_figure(f), config=PLOT, key="net")
    st.caption("Each circle is a bank (large banks in the centre, sized by payments sent). Green means its payments are flowing; red means "
               "more value is waiting to go out than it has liquidity. Lines are the biggest flows settled in that half hour. Drag the slider or press play.")

    st.subheader("Open a bank")
    worst = max(r["banks"], key=lambda x: x["usage_pct"])["id"]
    bank = st.selectbox("Bank", f["banks"], index=f["banks"].index(worst), label_visibility="collapsed")
    d = bank_detail(r["_run"], bank)
    m = st.columns(4)
    m[0].metric("Deepest net debit", usd(-d["lowest_minor"] / 100))
    m[1].metric("Liquidity at start", usd(d["available_minor"] / 100))
    m[2].metric("Own payments settled", f"{d['own_settled_share'] * 100:.1f}%")
    m[3].metric("Payments left unsettled", f"{d['unsettled_count']}")
    left, right = st.columns([3, 2])
    fig = go.Figure(go.Scatter(x=[c[0] for c in d["curve"]], y=[c[1] / 100 for c in d["curve"]], mode="lines", line=dict(color=C["blue"], width=2, shape="hv"),
                               fill="tozeroy", fillcolor="rgba(57,135,229,0.12)", hovertemplate="%{x}: %{y:$,.3s}<extra></extra>"))
    fig.add_hline(y=-d["available_minor"] / 100, line=dict(color=C["red"], dash="dot"), annotation_text="liquidity at start", annotation_font_color=C["red"])
    fig.update_yaxes(tickformat="$.2s")
    fig.update_xaxes(nticks=8)
    left.plotly_chart(layout(fig, 280, title=dict(text=f"{bank}: net position through the day", font=dict(size=14))), config=PLOT)
    pay = pd.DataFrame([{"Pays most to": x["bank"], "Value": usd(x["minor"] / 100)} for x in d["pays_most_to"]])
    right.dataframe(pay, hide_index=True, width="stretch")
    if d["unsettled"]:
        st.dataframe(pd.DataFrame([{"Unsettled payment": u["payment_id"], "To": u["to"], "Amount": usd(u["minor"] / 100), "Why": u["why"]} for u in d["unsettled"]]),
                     hide_index=True, width="stretch")


def page_whatif() -> None:
    st.title("What if")
    st.markdown('<p class="lede">Same banks, same payments, two responses. Then see how each holds up as liquidity gets scarcer.</p>', unsafe_allow_html=True)
    s = st.session_state
    ca, cb = st.columns(2)
    with ca:
        st.markdown("#### A")
        pa = st.selectbox("Queue policy", list(POLICY), format_func=POLICY.get, key="a_policy")
        ta = st.selectbox("Treasury", list(TREASURY), format_func=TREASURY.get, key="a_ctrl")
        aa = st.selectbox("Auction", list(AUCTION), format_func=AUCTION.get, key="a_auc")
    with cb:
        st.markdown("#### B")
        pb = st.selectbox("Queue policy", list(POLICY), format_func=POLICY.get, index=3, key="b_policy")
        tb = st.selectbox("Treasury", list(TREASURY), format_func=TREASURY.get, index=2, key="b_ctrl")
        ab = st.selectbox("Auction", list(AUCTION), format_func=AUCTION.get, index=1, key="b_auc")
    with st.spinner("Running both…"):
        A, B = current(policy=pa, controller=ta, auction=aa), current(policy=pb, controller=tb, auction=ab)
    ka, kb = A["kpis"], B["kpis"]
    change = (kb["cost_usd"] / ka["cost_usd"] - 1) * 100 if ka["cost_usd"] else 0
    better = change < 0
    v = st.columns(3)
    v[0].markdown(f'<div class="verdict" style="background:{C["grey"]}"><div class="l">A · cost of the day</div><div class="n">{usd(ka["cost_usd"])}</div>'
                  f'<div class="l">{ka["settled_pct"]:.2f}% settled · {ka["delay_min"]:.1f} min delay</div></div>', unsafe_allow_html=True)
    v[1].markdown(f'<div class="verdict" style="background:{C["blue"]}"><div class="l">B · cost of the day</div><div class="n">{usd(kb["cost_usd"])}</div>'
                  f'<div class="l">{kb["settled_pct"]:.2f}% settled · {kb["delay_min"]:.1f} min delay</div></div>', unsafe_allow_html=True)
    v[2].markdown(f'<div class="verdict" style="background:{C["green"] if better else C["red"]}"><div class="l">B against A, on {STRESS[s.stress].lower()}</div>'
                  f'<div class="n">{change:+.0f}%</div><div class="l">{"cheaper" if better else "more expensive"} · {usd(kb["unsettled_usd"] - ka["unsettled_usd"], True)} unsettled</div></div>',
                  unsafe_allow_html=True)
    st.caption("One paired day. The Evidence page has the same comparison over many days with confidence intervals.")
    fig = go.Figure()
    for name, R, col in (("A", A, C["grey"]), ("B", B, C["blue"])):
        fig.add_trace(go.Scatter(x=R["series"]["t"], y=R["series"]["queued_usd"], name=name, mode="lines", line=dict(color=col, width=3),
                                 hovertemplate="%{x}: %{y:$,.3s}<extra>" + name + "</extra>"))
    fig.update_yaxes(tickformat="$.2s", rangemode="tozero")
    fig.update_xaxes(nticks=8)
    st.plotly_chart(layout(fig, 300, title=dict(text="Value waiting to settle", font=dict(size=14))), config=PLOT)

    st.subheader("How little liquidity can the system run on?")
    if st.button("Sweep opening liquidity from 6% to 30% for A and B"):
        with st.spinner("Twelve simulated days…"):
            st.session_state.sweep = {"A": liquidity_sweep(lambda pct: current(policy=pa, controller=ta, auction=aa, liq=pct)),
                                      "B": liquidity_sweep(lambda pct: current(policy=pb, controller=tb, auction=ab, liq=pct)),
                                      "key": (pa, ta, aa, pb, tb, ab, s.stress, s.seed, s.source)}
    sw = st.session_state.get("sweep")
    if sw and sw["key"] == (pa, ta, aa, pb, tb, ab, s.stress, s.seed, s.source):
        fig = make_subplots(rows=1, cols=2, subplot_titles=("Large-value value settled", "Cost of the day"))
        for name, col in (("A", C["grey"]), ("B", C["blue"])):
            xs = [p["liquidity_pct"] for p in sw[name]]
            fig.add_trace(go.Scatter(x=xs, y=[p["settled_pct"] for p in sw[name]], name=name, mode="lines+markers", line=dict(color=col, width=3), marker=dict(size=9),
                                     hovertemplate="%{x}% liquidity: %{y:.2f}% settled<extra>" + name + "</extra>"), 1, 1)
            fig.add_trace(go.Scatter(x=xs, y=[p["cost_usd"] for p in sw[name]], name=name, mode="lines+markers", line=dict(color=col, width=3), marker=dict(size=9),
                                     showlegend=False, hovertemplate="%{x}% liquidity: %{y:$,.3s}<extra>" + name + "</extra>"), 1, 2)
        fig.update_xaxes(ticksuffix="%", title_text="opening liquidity")
        fig.update_yaxes(ticksuffix="%", row=1, col=1)
        fig.update_yaxes(tickformat="$.2s", row=1, col=2)
        st.plotly_chart(layout(fig, 340), config=PLOT)


def _use_sample() -> None:
    from atlas.ingest import export_scenario_csv
    from atlas.scenario import generate_scenario
    st.session_state.csv_text, st.session_state.csv_name = export_scenario_csv(generate_scenario(seed=21)), "atlas_sample_day.csv"
    st.session_state.source = "My payments"


def _take_upload() -> None:
    up = st.session_state.get("upload")
    if up is not None:
        st.session_state.csv_text, st.session_state.csv_name = up.getvalue().decode("utf-8", errors="replace"), up.name
        st.session_state.source = "My payments"


def page_upload() -> None:
    from atlas.ingest import export_scenario_csv, template_csv
    from atlas.scenario import generate_scenario
    st.title("Your payments")
    st.markdown('<p class="lede">Run the same simulator on a real day of payments. Four columns are enough: sender, receiver, amount, time. '
                'The file is processed in this session only and is not stored.</p>', unsafe_allow_html=True)
    c = st.columns(3)
    c[0].download_button("Download the template", template_csv(), "atlas_payments_template.csv", "text/csv", width="stretch")
    c[1].download_button("Download a sample day", export_scenario_csv(generate_scenario(seed=21)), "atlas_sample_day.csv", "text/csv", width="stretch")
    c[2].button("Use the sample day now", width="stretch", on_click=_use_sample)
    st.file_uploader("Payments CSV", type=["csv"], key="upload", on_change=_take_upload)
    if not st.session_state.csv_text:
        st.info("Optional columns: rail (fedwire, chips, fednow, rtp), due, priority, kind, payment_id. ISO 20022 pacs.008 / pacs.009 files work from the command line: `atlas run --payments folder/`.")
        return
    try:
        r = current(source="My payments")
    except Exception as exc:  # noqa: BLE001 - show the loader's own message
        st.error(f"Could not use that file: {exc}")
        return
    g = r["ingest"]
    m = st.columns(4)
    m[0].metric("Rows accepted", f"{g['accepted']:,}")
    m[1].metric("Rows rejected", f"{g['rejected_count']:,}")
    m[2].metric("Banks found", g["totals"]["institutions"])
    m[3].metric("Value", usd(g["totals"]["value_minor"] / 100))
    if g["assumptions"]:
        st.warning("**Assumed, because the file does not say:**\n\n" + "\n".join(f"- {a}" for a in g["assumptions"]))
    if g["rejected"]:
        st.error("**Rejected rows (never silently fixed):**")
        st.dataframe(pd.DataFrame(g["rejected"]), hide_index=True, width="stretch")
    badges(r)
    kpi_strip(r, None)
    st.success("Your day is loaded. Every page now runs on it: play it on **Live day**, compare responses on **What if**, read the supervisory view on **Risk & controls**.")
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    st.download_button("Download this run (JSON)", json.dumps(out, indent=1), "atlas_run.json", "application/json")


def page_risk() -> None:
    st.title("Risk and controls")
    r = current()
    t1, t2, t3, t4 = st.tabs(["Intraday liquidity (BCBS 248)", "Unusual payments", "Tamper with the ledger", "Model risk"])
    with t1:
        st.markdown('<p class="lede">What a supervisor monitors: each bank\'s largest net debit during the day against the liquidity it started with.</p>', unsafe_allow_html=True)
        banks = sorted(r["banks"], key=lambda x: -x["usage_pct"])
        fig = go.Figure(go.Bar(y=[b["id"] for b in banks][::-1], x=[b["usage_pct"] for b in banks][::-1], orientation="h",
                               marker=dict(color=[C["red"] if b["usage_pct"] > 100 else C["blue"] for b in banks][::-1]),
                               hovertemplate="%{y}: %{x:.0f}% of liquidity used<extra></extra>"))
        fig.add_vline(x=100, line=dict(color=C["red"], dash="dot"))
        fig.update_xaxes(ticksuffix="%")
        a, b = st.columns([3, 2])
        a.plotly_chart(layout(fig, max(280, 26 * len(banks)), title=dict(text="Peak usage of available liquidity", font=dict(size=14))), config=PLOT)
        T = r["throughput"]
        fig = go.Figure(go.Bar(x=T["hours"], y=[v * 100 for v in T["share"]], marker=dict(color=C["blue"]), hovertemplate="by %{x}: %{y:.0f}%<extra></extra>"))
        fig.update_yaxes(ticksuffix="%", range=[0, 100])
        b.plotly_chart(layout(fig, 300, title=dict(text="Share of the day's payments sent, by hour", font=dict(size=14))), config=PLOT)
        k = r["kpis"]
        b.metric("Timed obligations late / failed", f"{k['late_timed']} / {k['failed_timed']}")
        st.download_button("Download the full report (JSON)", json.dumps(r["_bcbs"], indent=1), "intraday_liquidity_bcbs248.json", "application/json")
    with t2:
        from atlas.detect import score_payments
        st.markdown('<p class="lede">Payments ranked by how unusual they look for their sender and corridor. A person reviews them; nothing is blocked.</p>', unsafe_allow_html=True)
        n = st.slider("Review budget (payments a person can check today)", 5, 100, 25, step=5)
        out = score_payments(r["_run"]["payments"], top=n)
        st.caption(f"{out['payments_scored']:,} payments scored · {out['mode']}")
        if out["alerts"]:
            df = pd.DataFrame([{"Score": a["score"], "Why flagged": a["reason"], "From": a["sender"], "To": a["receiver"], "Rail": a["rail"],
                                "Amount": a["amount_minor"] / 100, "Time (UTC)": a["at"][11:19], "Payment": a["payment_id"]} for a in out["alerts"]])
            st.dataframe(df, hide_index=True, width="stretch",
                         column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=float(df["Score"].max()), format="%.1f"),
                                        "Amount": st.column_config.NumberColumn(format="dollar")})
            mix = df["Why flagged"].value_counts()
            fig = go.Figure(go.Bar(x=mix.values, y=mix.index, orientation="h", marker=dict(color=C["orange"])))
            st.plotly_chart(layout(fig, 60 + 34 * len(mix), title=dict(text="Why they were flagged", font=dict(size=14))), config=PLOT)
        det = artifact("anomaly_detection.json")
        if det and det.get("explainability"):
            imp = det["explainability"]["gbt"][:7][::-1]
            fig = go.Figure(go.Bar(y=[x["feature"].replace("_", " ") for x in imp], x=[x["drop_in_pr_auc"] for x in imp], orientation="h", marker=dict(color=C["blue"]),
                                   hovertemplate="%{y}: PR-AUC falls by %{x:.2f} without it<extra></extra>"))
            rob = det["robustness"]["gbt"]
            a2, b2 = st.columns(2)
            a2.plotly_chart(layout(fig, 300, title=dict(text="What the trained model relies on (permutation importance)", font=dict(size=14))), config=PLOT)
            fig = go.Figure(go.Scatter(x=[x["feature_noise_sd"] * 100 for x in rob], y=[x["pr_auc"] for x in rob], mode="lines+markers", line=dict(color=C["orange"], width=3), marker=dict(size=9)))
            fig.update_xaxes(ticksuffix="%", title_text="noise added to every input")
            fig.update_yaxes(rangemode="tozero")
            b2.plotly_chart(layout(fig, 300, title=dict(text="How fast it degrades with noisy inputs (PR-AUC)", font=dict(size=14))), config=PLOT)
        if det:
            g = det["detectors"]["gbt"]
            worst = max(v["gbt_unseen_recall"] for v in det["leave_one_typology_out"].values())
            st.info(f"On held-out days with injected incidents, a trained model caught **{g['recall_at_alert_rate']:.0%}** of patterns it had seen and at most "
                    f"**{worst:.0%}** of patterns it had not. That is why the rule above stays in place next to it.")
    with t3:
        st.markdown('<p class="lede">Every event is chained by SHA-256 and the ledger can be rebuilt from the log. Change one payment by 1% and see who notices.</p>', unsafe_allow_html=True)
        res = r["_result"]
        n_settled = sum(1 for e in res.events if e.event_type == "PaymentSettled")
        which = st.slider("Which settled payment to alter", 1, n_settled, min(n_settled, 250))
        t = tamper_check(res, which - 1)
        a, b, c = st.columns(3)
        a.markdown(f'<div class="verdict" style="background:{C["grey"]}"><div class="l">Payment {t["payment"]}</div><div class="n">{usd(t["amount_before_minor"] / 100)}</div>'
                   f'<div class="l">quietly changed to {usd(t["amount_after_minor"] / 100)} (event {t["event_sequence"]:,} of {t["events"]:,})</div></div>', unsafe_allow_html=True)
        b.markdown(f'<div class="verdict" style="background:{C["green"] if t["chain_caught"] else C["red"]}"><div class="l">Hash chain</div>'
                   f'<div class="n">{"caught" if t["chain_caught"] else "missed"}</div><div class="l">{t["links_invalidated"]:,} later links no longer match</div></div>', unsafe_allow_html=True)
        c.markdown(f'<div class="verdict" style="background:{C["green"] if t["replay_caught"] else C["red"]}"><div class="l">Ledger replay</div>'
                   f'<div class="n">{"caught" if t["replay_caught"] else "missed"}</div><div class="l">untouched log replays: {"yes" if t["untouched_replay_ok"] else "no"}</div></div>', unsafe_allow_html=True)
        st.code(f"chain head, original : {t['chain_head_original']}\nchain head, tampered : {t['chain_head_tampered']}\nreplay says          : {t['replay_message']}", language=None)
        st.caption("The change is made on a copy. The real run is untouched.")
    with t4:
        from atlas.governance import build_inventory
        inv = build_inventory(ROOT / "results")
        st.markdown(f'<p class="lede">Every statistical model is in an inventory with a materiality tier and automated validation checks, in the structure of the 2026 US '
                    f'model-risk guidance (SR 26-2). Right now: {inv["summary"]["pass"]} pass, {inv["summary"]["warn"]} warn, {inv["summary"]["fail"]} fail.</p>', unsafe_allow_html=True)
        icon = {"pass": "🟢", "warn": "🟠", "fail": "🔴"}
        for m in inv["models"]:
            with st.expander(f"{icon[m['status']]}  {m['name']}  ·  tier {m['materiality']['tier']}  ·  {m['status'].upper()}"):
                st.caption(f"{m['purpose']}. Challenger: {m['challenger']}.")
                st.dataframe(pd.DataFrame([{"": icon[c["status"]], "Check": c["check"], "Value": str(c["value"]), "Rule": c["rule"]} for c in m["checks"]]),
                             hide_index=True, width="stretch")
                st.markdown("**Limits:** " + "; ".join(m["limitations"]))
        st.caption(inv["disclaimer"])


def page_ask() -> None:
    from atlas.agent.evals import planner_agent, ungrounded_numbers
    from atlas.agent.tools import ToolSession
    st.title("Ask")
    st.markdown('<p class="lede">An agent with read-only tools over this day. It can simulate and look things up; it cannot move money. '
                'Every number in an answer is checked against what the tools returned.</p>', unsafe_allow_html=True)
    r = current()
    sid = r["scenario"]["fingerprint"]
    if st.session_state.get("ask_sid") != sid:
        st.session_state.ask_sid, st.session_state.ask_session, st.session_state.chat = sid, ToolSession(r["_scenario"], max_calls=200, max_simulations=40), []
    session: ToolSession = st.session_state.ask_session
    with st.sidebar.expander("Connect a language model (optional)"):
        st.caption("Any OpenAI-compatible endpoint. Without one, a deterministic planner answers.")
        base = st.text_input("Base URL", placeholder="https://…/v1", key="llm_base")
        model = st.text_input("Model", key="llm_model")
        key = st.text_input("API key", type="password", key="llm_key")
    chips = ["What percentage of large-value value settles under combined stress?", "Which institution is most stretched on intraday liquidity under combined stress?",
             "Under combined stress, by what percentage does cost change if we add the MPC controller and a uniform price auction?",
             "According to the rulebook, what is the FedNow transaction limit? Cite the document.", "Move $50 million from RTGS to FedNow for bank-003 right now."]
    cols = st.columns(len(chips))
    asked = None
    for c, q in zip(cols, chips):
        if c.button(q, width="stretch"):
            asked = q
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            if m.get("trace") is not None:
                show_trace(m)
    asked = st.chat_input("Ask about this day, or ask what the rulebook says") or asked
    if asked:
        st.session_state.chat.append({"role": "user", "text": asked})
        try:
            if base and model:
                from atlas.agent.llm import LLMAgent, OpenAICompatClient
                out, who = LLMAgent(OpenAICompatClient(base, model, key))(asked, session), f"model {model}"
            else:
                out, who = planner_agent(asked, session), "deterministic planner"
        except Exception as exc:  # noqa: BLE001 - endpoint errors are shown, not hidden
            out, who = {"answer": f"The model endpoint failed: {exc}", "trace": []}, "error"
        bad = ungrounded_numbers(out["answer"], out["trace"], asked)
        st.session_state.chat.append({"role": "assistant", "text": out["answer"], "trace": out["trace"], "bad": bad, "who": who})
        st.rerun()
    with st.expander(f"Audit log: {len(session.audit)} tool calls, hash chain {'intact ✓' if session.verify_audit() else 'BROKEN'}"):
        st.dataframe(pd.DataFrame([{"#": a["seq"], "Tool": a["tool"], "Arguments": json.dumps(a["args"]), "Hash": a["hash"][:16] + "…"} for a in session.audit]),
                     hide_index=True, width="stretch")


def show_trace(m: dict) -> None:
    ok = not m["bad"]
    st.markdown(f'<span class="tag {"ok" if ok else "no"}">Grounding <b>{"every number traced ✓" if ok else "not traced: " + ", ".join(m["bad"])}</b></span>'
                f'<span class="tag">Answered by <b>{m["who"]}</b></span><span class="tag"><b>{len(m["trace"])}</b> tool calls</span>', unsafe_allow_html=True)
    for t in m["trace"]:
        with st.expander(f"🔧 {t['tool']}({', '.join(f'{k}={v}' for k, v in (t.get('args') or {}).items()) if isinstance(t.get('args'), dict) else ''})"):
            res = t.get("result", t.get("error"))
            if isinstance(res, dict) and "passages" in res:
                for p in res["passages"]:
                    st.markdown(f'<div class="cite"><b>{p["citation"]}</b><br>{p["text"][:420]}</div>', unsafe_allow_html=True)
            else:
                st.json(res, expanded=False)


def page_evidence() -> None:
    st.title("Evidence")
    st.markdown('<p class="lede">The same questions over many simulated days, with paired statistics. Every bar comes from a results file in the repository.</p>', unsafe_allow_html=True)
    t1, t2, t3, t4, t5 = st.tabs(["Which response wins", "Every bad day", "Deep-learning forecasts", "Retrieval and agents", "What banks hire for"])
    names = {"priority": "Priority queue", "fifo": "FIFO", "fifo_strict": "Strict FIFO", "bilateral": "Bilateral offset", "multilateral": "Multilateral heuristic",
             "multilateral_milp": "Exact MILP netting", "auction_pay_as_bid": "Auction: pay as bid", "auction_uniform": "Auction: uniform price",
             "rule_rebalancer": "Rule-based treasury", "mpc": "MPC rebalancing", "mpc_queue_milp": "MPC + queue MILP", "mpc_plus_auction": "MPC + auction"}
    with t1:
        b = artifact("benchmarks/extended.json") or artifact("benchmarks/standard.json")
        if b:
            c = st.columns(2)
            stress = c[0].selectbox("Stress", b["config"]["stresses"], format_func=lambda s: STRESS.get(s, s))
            metric = c[1].selectbox("Measure", ["total_cost_minor", "lv_settlement_rate_value", "lv_value_weighted_delay_s", "instant_rejected"],
                                    format_func={"total_cost_minor": "Cost of the day", "lv_settlement_rate_value": "Large-value value settled",
                                                 "lv_value_weighted_delay_s": "Delay", "instant_rejected": "Instant payments rejected"}.get)
            rows = [x for x in b["comparison"] if x["stress"] == stress and x["metric"] == metric]
            lower = metric != "lv_settlement_rate_value"
            rows.sort(key=lambda x: x["mean"], reverse=lower)
            k = {"total_cost_minor": 0.01, "lv_settlement_rate_value": 100, "lv_value_weighted_delay_s": 1 / 60, "instant_rejected": 1}[metric]
            col = [C["grey"] if not x["significant"] else (C["blue"] if (x["mean_diff"] < 0) == lower else C["orange"]) for x in rows]
            fig = go.Figure(go.Bar(y=[names.get(x["arm"], x["arm"]) for x in rows], x=[x["mean"] * k for x in rows], orientation="h", marker=dict(color=col),
                                   error_x=dict(type="data", symmetric=False, array=[(x["ci95_diff"][1] - x["mean_diff"]) * k for x in rows],
                                                arrayminus=[(x["mean_diff"] - x["ci95_diff"][0]) * k for x in rows], color=C["ink"], thickness=1.2),
                                   hovertemplate="%{y}: %{x:,.2f}<extra></extra>"))
            fig.update_xaxes(tickformat={"total_cost_minor": "$.3s", "lv_settlement_rate_value": ".2f", "lv_value_weighted_delay_s": ".1f", "instant_rejected": ".0f"}[metric])
            st.plotly_chart(layout(fig, 60 + 34 * len(rows)), config=PLOT)
            st.caption(f"{b['manifest']['runs']:,} runs, every ledger replayed. Blue = significantly better than the priority queue (95% paired bootstrap), orange = worse, grey = no clear difference.")
    with t2:
        b = artifact("benchmarks/extended.json")
        if b:
            arms = ["multilateral_milp", "rule_rebalancer", "mpc", "auction_uniform", "mpc_plus_auction"]
            comp = {(x["stress"], x["arm"]): x for x in b["comparison"] if x["metric"] == "total_cost_minor"}
            ss = b["config"]["stresses"]
            z = [[comp[(s, a)]["rel_diff"] * 100 if comp[(s, a)]["significant"] else None for a in arms] for s in ss]
            text = [[f"{v:+.0f}%" if v is not None else "n.s." for v in row] for row in z]
            fig = go.Figure(go.Heatmap(z=z, x=[names[a] for a in arms], y=[STRESS.get(s, s) for s in ss], text=text, texttemplate="%{text}", colorscale="Blues_r", zmin=-70, zmax=0,
                                       hovertemplate="%{y} · %{x}: %{text}<extra></extra>", colorbar=dict(ticksuffix="%", title="cost vs queue")))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(layout(fig, 460), config=PLOT)
            st.caption("Change in cost against the plain priority queue. n.s. = the 95% interval includes zero.")
    with t3:
        d = artifact("deep_forecasting.json")
        if d:
            st.markdown('<p class="lede">A GRU and a small Transformer trained in PyTorch, scored by the same code and splits as ridge and gradient boosting.</p>', unsafe_allow_html=True)
            c = st.columns(2)
            size = c[0].segmented_control("Training days", d["train_sizes_days"], default=d["train_sizes_days"][-1])
            hz = c[1].segmented_control("Horizon", ["15m", "1h"], default="15m")
            rows = sorted([x for x in d["results"] if x["train_days"] == size and x["horizon"] == hz], key=lambda x: x["mase"])
            fig = go.Figure(go.Bar(x=[x["model"].replace("_", " ") for x in rows], y=[x["mase"] for x in rows],
                                   marker=dict(color=[C["blue"] if x["model"] in ("gru", "transformer") else C["grey"] for x in rows]),
                                   text=[f"{x['mase']:.3f}" for x in rows], textposition="outside", hovertemplate="%{x}: MASE %{y:.3f}<extra></extra>"))
            a, b2 = st.columns(2)
            a.plotly_chart(layout(fig, 340, title=dict(text="Forecast error (MASE, lower is better)", font=dict(size=14))), config=PLOT)
            fig = go.Figure()
            for name, col in (("gru", C["blue"]), ("transformer", C["violet"])):
                h = d["training_curves"].get(f"{name}|{size}|{hz}")
                if h:
                    fig.add_trace(go.Scatter(x=[e["epoch"] for e in h], y=[e["holdout_loss"] for e in h], name=f"{name} held-out", line=dict(color=col, width=3)))
                    fig.add_trace(go.Scatter(x=[e["epoch"] for e in h], y=[e["train_loss"] for e in h], name=f"{name} train", line=dict(color=col, width=1.5, dash="dot")))
            fig.update_xaxes(title_text="epoch")
            b2.plotly_chart(layout(fig, 340, title=dict(text="Training curves (early stopping on held-out training days)", font=dict(size=14))), config=PLOT)
    with t4:
        k = artifact("retrieval_eval.json")
        e = artifact("agent_evals.json")
        a, b2 = st.columns(2)
        if k:
            m = k["methods"]["bm25"]
            a.metric("Rulebook retrieval: right document first", f"{m['hit_at_1']:.0%}", help=f"{k['questions']} labelled questions over {k['passages']} passages")
            a.metric("Right document in the top three", f"{m['hit_at_3']:.0%}")
            a.dataframe(pd.DataFrame([{"Question": x["question"], "Rank of a correct source": str(x["rank"] or "miss")} for x in k["rows"]]), hide_index=True, width="stretch", height=300)
        if e:
            b2.dataframe(pd.DataFrame([{"Agent": x["agent"], "Right tools": f"{x['tools']:.0%}", "Right answer": f"{x['correct']:.0%}", "No invented numbers": f"{x['grounded']:.0%}",
                                        "Refuses to execute": f"{x['safe']:.0%}", "Passes all": f"{x['pass_rate']:.0%}"} for x in e["agents"]]), hide_index=True, width="stretch")
            b2.caption("The two control agents are broken on purpose: an evaluation that cannot fail a bad agent proves nothing.")
    with t5:
        h = json.loads((ROOT / "data" / "hiring_map.json").read_text()) if (ROOT / "data" / "hiring_map.json").exists() else None
        if h:
            mark = {2: "●", 1: "○", 0: "–"}
            st.dataframe(pd.DataFrame([{"What postings ask for": x["skill"], "Junior": mark[x["junior"]], "Senior": mark[x["senior"]], "Director+": mark[x["director"]],
                                        "In ATLAS": x["where"]} for x in h["rows"]]), hide_index=True, width="stretch", height=36 * len(h["rows"]) + 40)
            st.caption(f"● required, ○ preferred. {h['postings']} postings at {', '.join(h['banks'])}. Sources: docs/25_industry_landscape.md.")


@st.cache_data(ttl=600, show_spinner=False)
def fetch_reviews() -> list[dict] | None:
    import urllib.request
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/issues?state=all&labels=review&per_page=50", headers={"Accept": "application/vnd.github+json", "User-Agent": "atlas-app"})
        with urllib.request.urlopen(req, timeout=6) as resp:  # noqa: S310 - fixed GitHub API URL
            return [{"title": i["title"], "by": i["user"]["login"], "url": i["html_url"], "at": i["created_at"][:10], "body": (i.get("body") or "")[:500]}
                    for i in json.loads(resp.read()) if "pull_request" not in i]
    except Exception:  # noqa: BLE001 - offline or rate-limited: say so, do not invent reviews
        return None


def page_review() -> None:
    st.title("Review this")
    st.markdown('<p class="lede">Tried it? Say what worked and what broke. Your answers open as a public GitHub issue under your own name, so every review here is from a real, '
                'identifiable person.</p>', unsafe_allow_html=True)
    a, b = st.columns([3, 2])
    with a:
        rating = st.feedback("stars")
        role = st.text_input("I am a", placeholder="payments engineer, treasury analyst, ML engineer, student…")
        tried = st.multiselect("What I tried", ["Live day", "What if", "My own CSV", "Risk & controls", "Ask", "Browser lab", "CLI", "MCP tools", "The code"])
        worked = st.text_area("What worked", height=90)
        broke = st.text_area("What broke or confused me", height=90)
        would = st.text_area("Would I use this on real data? Why or why not", height=80)
        url = review_url(REPO, rating=(rating + 1) if rating is not None else None, role=role, tried=tried, worked=worked, broke=broke, would_use=would)
        st.link_button("Post my review on GitHub →", url, type="primary", disabled=not (broke or worked))
        st.caption("You will see the pre-filled form on GitHub and press Submit there. Nothing is posted from this page.")
    with b:
        st.subheader("Published reviews")
        rs = fetch_reviews()
        if rs is None:
            st.caption("Could not reach GitHub just now.")
        elif not rs:
            st.info("No reviews yet. Be the first.")
        else:
            for x in rs:
                st.markdown(f"**[{x['title']}]({x['url']})**  \n@{x['by']} · {x['at']}")
        st.link_button("All reviews on GitHub", f"https://github.com/{REPO}/issues?q=label%3Areview")


sidebar()
pages = [st.Page(page_live, title="Live day", icon="▶️", default=True, url_path="live"), st.Page(page_whatif, title="What if", icon="🔀", url_path="what-if"),
         st.Page(page_upload, title="Your payments", icon="📄", url_path="your-payments"), st.Page(page_risk, title="Risk & controls", icon="🛡️", url_path="risk"),
         st.Page(page_ask, title="Ask", icon="💬", url_path="ask"), st.Page(page_evidence, title="Evidence", icon="📊", url_path="evidence"),
         st.Page(page_review, title="Review this", icon="⭐", url_path="review")]
st.navigation(pages, position="top").run()
