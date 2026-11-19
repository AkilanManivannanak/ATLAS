"""Every page of the app. Numbers come from the simulator, the live market feeds or ``results/``; nothing is mocked."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from atlas_app import components as ui
from atlas_app.state import (
    AUCTION,
    PLOT,
    POLICY,
    PRESETS,
    REPO,
    ROOT,
    STRESS,
    STRESS_ICON,
    TREASURY,
    VERBS,
    apply,
    artifact,
    badges,
    current,
    eyebrow,
    kpi_items,
    lede,
    log,
    usd,
    who,
    workspace,
)
from atlas_app.theme import layout, palette, rgba
from plotly.subplots import make_subplots

from atlas.insight import bank_detail, liquidity_sweep, review_url, tamper_check


# ================================================================== live market data (shared)
@st.cache_data(ttl=900, show_spinner=False)
def market():
    from atlas.live import fetch_markets
    return fetch_markets()


def market_brief():
    from atlas.live import indicators
    md = market()
    return md, indicators(md)


def _use_market(ind: dict, as_of: str | None) -> None:
    from atlas.live import to_simulation
    sim = to_simulation(ind)
    apply(dict(stress=sim["stress"], liq=sim["liq"], policy="priority", controller="none", auction="none"))
    st.session_state["_market_ran"] = as_of or ind["as_of"]
    log("ran_live_market", {"as_of": as_of or ind["as_of"], "score": ind["score"], "liq": sim["liq"], "stress": sim["stress"]})


# ================================================================== 1. command center
def people_strip() -> None:
    """Real people who used this deployment, newest first. Shows nothing invented: empty until someone types a name."""
    from datetime import datetime
    seen: dict[str, dict] = {}
    for e in workspace().events(800):
        if e["user"] == "guest":
            continue
        d = seen.setdefault(e["user"], {"name": e["user"], "n": 0, "last_at": e["at"], "last": e["kind"]})
        d["n"] += 1
    now = datetime.now(UTC)
    people = []
    for d in seen.values():
        mins = (now - datetime.fromisoformat(d["last_at"])).total_seconds() / 60
        d["ago"] = "now" if mins < 2 else f"{mins:.0f}m ago" if mins < 60 else f"{mins / 60:.0f}h ago" if mins < 1440 else f"{mins / 1440:.0f}d ago"
        d["live"] = mins < 15
        people.append(d)
    ui.people(people[:12])


def visits_of(user: str, gap_min: int = 30) -> list[dict]:
    """A person's history from the shared log, split into visits by 30-minute gaps. The visit that belongs to this
    browser session is marked current."""
    from datetime import datetime
    evs = sorted((e for e in workspace().events(5000) if e["user"] == user), key=lambda e: e["seq"])
    start = st.session_state.get("_session_start", "9999")
    out: list[dict] = []
    for e in evs:
        try:
            d, at = e["detail"], datetime.fromisoformat(e["at"])
        except ValueError:
            continue
        note = (STRESS.get(d.get("stress"), "") if d.get("stress") else "") or (d.get("q", "")[:60]) or (f"{d['payment']} {d['decision']}" if d.get("decision") else "") \
            or (f"{d['stars']} stars" if d.get("stars") else "")
        item = {"kind": e["kind"], "verb": VERBS.get(e["kind"], e["kind"]), "t": e["at"][11:16], "note": note}
        if not out or (at - out[-1]["_last"]).total_seconds() > gap_min * 60 or (e["at"] >= start) != out[-1]["current"]:
            out.append({"day": at.strftime("%b %d"), "from": e["at"][11:16], "current": e["at"] >= start, "items": [], "_last": at})
        out[-1]["items"].append(item)
        out[-1]["_last"], out[-1]["to"] = at, e["at"][11:16]
    for v in out:
        v.pop("_last")
    return out


def my_journey() -> None:
    name = who()
    if name == "guest":
        return
    v = visits_of(name)
    past = [x for x in v if not x["current"]]
    ui.journey(name, v, returning=bool(past))


def _map_points(ind: dict) -> list[dict]:
    """Every preset day plus today's live market, each simulated so its position is its real outcome."""
    from atlas.live import to_simulation
    pts = []
    for name, cfg in PRESETS.items():
        r = current(_log=False, **cfg)
        pts.append({"name": name, "cfg": cfg, "k": r["kpis"]})
    live = to_simulation(ind)
    cfg = dict(stress=live["stress"], liq=live["liq"], policy="priority", controller="none", auction="none")
    pts.append({"name": "Today's market", "cfg": cfg, "k": current(_log=False, **cfg)["kpis"], "live": True})
    return pts


def _pick_from_blotter() -> None:
    ev = st.session_state.get("blotter")
    try:
        row = ev["selection"]["rows"][0]
    except (KeyError, IndexError, TypeError):
        return
    pts = st.session_state.get("_map_pts", [])
    if 0 <= row < len(pts):
        x = pts[row]
        apply(x["cfg"])
        if x.get("live"):
            log("ran_live_market", x["cfg"] | {"from": "blotter"})


def scenario_blotter(ind: dict) -> None:
    """A trading-desk style blotter: one row per simulated day, numbers in columns, an intraday sparkline of value
    waiting to settle, sortable, and a click on any row loads that day everywhere."""
    with st.spinner("Pricing every scenario…"):
        pts = _map_points(ind)
    st.session_state._map_pts = pts
    rows = []
    for x in pts:
        r = current(_log=False, **x["cfg"])
        q = r["series"]["queued_usd"]
        step = max(1, len(q) // 32)
        rows.append({"Scenario": x["name"] + (" · live" if x.get("live") else ""),
                     "Settled": x["k"]["settled_pct"], "Intraday queue": [v / 1e6 for v in q[::step]],
                     "Delay": x["k"]["delay_min"], "Unsettled": x["k"]["unsettled_usd"], "Cost": x["k"]["cost_usd"],
                     "Liquidity": x["cfg"]["liq"], "Treasury": TREASURY[x["cfg"]["controller"]]})
    lo = min(r_["Settled"] for r_ in rows)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", key="blotter", on_select=_pick_from_blotter, selection_mode="single-row",
                 column_config={
                     "Scenario": st.column_config.TextColumn(width="medium"),
                     "Settled": st.column_config.ProgressColumn("Settled", min_value=float(int(lo) - 1), max_value=100.0, format="%.2f%%"),
                     "Intraday queue": st.column_config.LineChartColumn("Waiting to settle, 08:00 to 18:00", width="medium"),
                     "Delay": st.column_config.NumberColumn("Avg delay", format="%.1f min"),
                     "Unsettled": st.column_config.NumberColumn("Unsettled", format="dollar"),
                     "Cost": st.column_config.NumberColumn("Cost of day", format="dollar"),
                     "Liquidity": st.column_config.NumberColumn("Opening liq.", format="%d%%"),
                 })


def page_overview() -> None:
    p = palette()
    people_strip()
    my_journey()
    md, ind = market_brief()
    live = "live" if md.origin.get("sofr") == "live" else "snapshot"
    ui.hero(f"US funding market · {ind['as_of']} · {live} data", f"SOFR {ind['sofr_pct']:.2f}%", f"· {ind['regime']}",
            f"SOFR − EFFR {ind['spread_bp']:+.1f} bp · RRP ${ind['rrp_bn']:.1f}bn · TGA ${ind['tga_bn']:,.0f}bn · tightness {ind['score']:.0f}/100")
    st.title("Settlement command center")
    lede("Select a row to load that day.", "Every row is a full simulated day on the same payments; sort any column; the live row is set by today's NY Fed and Treasury data")
    scenario_blotter(ind)
    with st.spinner("Simulating the day…"):
        r = current()
    s = st.session_state
    i_ = r["integrity"]
    meta = (f"{'replay verified' if i_['replay_verified'] else 'REPLAY FAILED'} · {r['scenario']['institutions']} banks · "
            f"{r['scenario']['payments']:,} payments · {usd(r['scenario']['value_usd'])}")
    ui.network(r["_frames"], meta=meta)
    ui.tiles(kpi_items(r, s.pinned), cols=3)
    a, b, _ = st.columns([1, 1, 4])
    if a.button(":material/push_pin: Pin baseline", width="stretch", help="Later runs show their change against this one."):
        s.pinned = {"kpis": r["kpis"], "series": r["series"], "choices": r["choices"]}
        log("pinned", r["choices"])
        st.rerun()
    if s.pinned and b.button("Clear baseline", width="stretch"):
        s.pinned = None
        st.rerun()

    eyebrow("Open a bank")
    f = r["_frames"]
    worst = max(r["banks"], key=lambda x: x["usage_pct"])["id"]
    bank = st.selectbox("Bank", f["banks"], index=f["banks"].index(worst), label_visibility="collapsed")
    d = bank_detail(r["_run"], bank)
    m = st.columns(4)
    m[0].metric("Deepest net debit", usd(-d["lowest_minor"] / 100))
    m[1].metric("Liquidity at open", usd(d["available_minor"] / 100))
    m[2].metric("Own payments settled", f"{d['own_settled_share'] * 100:.1f}%")
    m[3].metric("Payments unsettled", f"{d['unsettled_count']}")
    left, right = st.columns([3, 2])
    fig = go.Figure(go.Scatter(x=[c[0] for c in d["curve"]], y=[c[1] / 100 for c in d["curve"]], mode="lines", line=dict(color=p["primary"], width=2.4, shape="hv"),
                               fill="tozeroy", fillcolor=rgba(p["primary"], 0.08), hovertemplate="%{x}: %{y:$,.3s}<extra></extra>"))
    fig.add_hline(y=-d["available_minor"] / 100, line=dict(color=p["bad"], dash="dot"), annotation_text="liquidity at open", annotation_font_color=p["bad"])
    fig.update_yaxes(tickformat="$.2s")
    fig.update_xaxes(nticks=8)
    left.plotly_chart(layout(fig, 280, title=f"{bank}: net position through the day"), config=PLOT)
    right.dataframe(pd.DataFrame([{"Pays most to": x["bank"], "Value": usd(x["minor"] / 100)} for x in d["pays_most_to"]]), hide_index=True, width="stretch")
    if d["unsettled"]:
        st.dataframe(pd.DataFrame([{"Unsettled payment": u["payment_id"], "To": u["to"], "Amount": usd(u["minor"] / 100), "Why": u["why"]} for u in d["unsettled"]]),
                     hide_index=True, width="stretch")


# ================================================================== 2. live markets
def page_markets() -> None:
    from atlas.live import freshness, indicators, to_simulation
    p = palette()
    st.title("Live funding market")
    lede("Today's real funding market drives the simulation.", "New York Fed Markets API + US Treasury Daily Treasury Statement, no keys")
    md, ind = market_brief()
    tone = lambda v: "bad" if v > 0 else "good"  # noqa: E731
    ui.ticker([("SOFR", f"{ind['sofr_pct']:.2f}%", "flat"), ("EFFR", f"{ind['effr_pct']:.2f}%", "flat"), ("SOFR − EFFR", f"{ind['spread_bp']:+.1f} bp", tone(ind["spread_bp"])),
               ("SOFR 99th − 1st", f"{ind['sofr_tail_bp']:.0f} bp", "flat"), ("SOFR volume", f"${ind['sofr_volume_bn']:,.0f}bn", "flat"),
               ("RRP take-up", f"${ind['rrp_bn']:.2f}bn", "bad" if ind["rrp_bn"] < 50 else "good"), ("TGA", f"${ind['tga_bn']:,.0f}bn", "flat"),
               ("TGA 5-day change", f"{ind['tga_5d_change_bn']:+.1f}bn", tone(ind["tga_5d_change_bn"]))])
    eyebrow("Feeds")
    fr = freshness(md)
    cols = st.columns(len(fr))
    for c, x in zip(cols, fr):
        edge = "edge-good" if x["fresh"] and x["origin"] == "live" else "edge-warn" if x["fresh"] else "edge-bad"
        tip = f'{x["publisher"]} · {x["rows"]} rows · {x["age_business_days"]} business day(s) old, target ≤ {x["target_lag_days"]}'
        dot = "#13804F" if x["origin"] == "live" and x["fresh"] else "#C77A00"
        state = f'<span style="color:{dot}">●</span> ' + ("live" if x["origin"] == "live" else "snapshot") + (" · fresh" if x["fresh"] else " · late")
        c.markdown(f'<div class="card {edge}" title="{tip}"><div class="k">{x["series"]}</div><div class="v">{x["last"][5:]}</div><div class="s">{state}</div></div>',
                   unsafe_allow_html=True)
    if any(x["origin"] == "snapshot" for x in fr):
        with st.expander(f"Some feeds could not be reached from this server, so they show the snapshot taken {md.snapshot_at[:16].replace('T', ' ')} UTC"):
            st.code("\n".join(f"{k}: {v}" for k, v in md.errors.items()), language=None)
    eyebrow("Reserve tightness · drag to explore")
    ui.tightness_lab(ind)
    lede("How the score is built", ind["method"])

    sofr, effr, rrp, tga = (md.series[k] for k in ("sofr", "effr", "rrp", "tga"))
    fig = make_subplots(rows=2, cols=2, subplot_titles=("SOFR with its 1st–99th percentile band, and EFFR", "SOFR minus EFFR (bp)",
                                                        "Overnight reverse repo take-up ($bn)", "Treasury General Account ($bn)"), vertical_spacing=0.16, horizontal_spacing=0.08)
    xs = [r["date"] for r in sofr]
    fig.add_trace(go.Scatter(x=xs, y=[r["p99"] for r in sofr], line=dict(width=0), showlegend=False, hoverinfo="skip"), 1, 1)
    fig.add_trace(go.Scatter(x=xs, y=[r["p1"] for r in sofr], line=dict(width=0), fill="tonexty", fillcolor=rgba(p["primary"], 0.12), name="SOFR 1st–99th pct",
                             hoverinfo="skip"), 1, 1)
    fig.add_trace(go.Scatter(x=xs, y=[r["rate"] for r in sofr], name="SOFR", line=dict(color=p["primary"], width=2.4), hovertemplate="%{x}: SOFR %{y:.2f}%<extra></extra>"), 1, 1)
    fig.add_trace(go.Scatter(x=[r["date"] for r in effr], y=[r["rate"] for r in effr], name="EFFR", line=dict(color=p["accent"], width=2, dash="dot"),
                             hovertemplate="%{x}: EFFR %{y:.2f}%<extra></extra>"), 1, 1)
    sp = ind["spread_series"]
    fig.add_trace(go.Bar(x=[d for d, _ in sp], y=[v for _, v in sp], marker=dict(color=[p["bad"] if v > 0 else p["good"] for _, v in sp]), showlegend=False,
                         hovertemplate="%{x}: %{y:+.1f} bp<extra></extra>"), 1, 2)
    fig.add_trace(go.Scatter(x=[r["date"] for r in rrp], y=[r["value_bn"] for r in rrp], fill="tozeroy", line=dict(color=p["accent2"], width=2), fillcolor=rgba(p["accent2"], 0.18),
                             showlegend=False, hovertemplate="%{x}: $%{y:.2f}bn<extra></extra>"), 2, 1)
    fig.add_trace(go.Scatter(x=[r["date"] for r in tga], y=[r["value_bn"] for r in tga], line=dict(color=p["primary"], width=2.2), showlegend=False,
                             hovertemplate="%{x}: $%{y:,.0f}bn<extra></extra>"), 2, 2)
    fig.update_yaxes(ticksuffix="%", row=1, col=1)
    st.plotly_chart(layout(fig, 560, t=40), config=PLOT)

    eyebrow("Replay any market day")
    days = [r["date"] for r in sofr]
    special = {d: d for d in days}
    for d in days:
        dd = date.fromisoformat(d)
        month_closed = any(x[:7] > d[:7] for x in days)
        if month_closed and d == max(x for x in days if x[:7] == d[:7]):
            special[d] = f"{d}  · {'quarter' if dd.month in (3, 6, 9, 12) else 'month'} end"
    pick = st.select_slider("Market day", options=days, value=days[-1], format_func=special.get)
    past = indicators(md, as_of=pick)
    sim = to_simulation(past)
    a, b = st.columns([2, 3])
    with a:
        st.markdown(f'<div class="card edge-p"><div class="k">{pick} · tightness {past["score"]:.0f}/100 · {past["regime"]}</div>'
                    f'<div class="v">{sim["liq"]}% liquidity</div><div class="s">{STRESS[sim["stress"]]}<br>'
                    + "<br>".join(sim["explanation"]) + "</div></div>", unsafe_allow_html=True)
        st.button("Use this market day everywhere", type="primary", width="stretch", on_click=_use_market, args=(past, pick))
    with b:
        r = current(stress=sim["stress"], liq=sim["liq"])
        base = current(stress="baseline", liq=18)
        ui.tiles([dict(label="Settled on that day", value=r["kpis"]["settled_pct"], fmt="pct", edge="good" if r["kpis"]["settled_pct"] >= 99 else "warn", base=base["kpis"]["settled_pct"]),
                  dict(label="Cost of the day", value=r["kpis"]["cost_usd"], fmt="usd", edge="a", low=True, base=base["kpis"]["cost_usd"]),
                  dict(label="Left unsettled", value=r["kpis"]["unsettled_usd"], fmt="usd", edge="bad", low=True, base=base["kpis"]["unsettled_usd"]),
                  dict(label="Instant rejected", value=r["kpis"]["instant_rejected"], fmt="int", edge="p", low=True, base=base["kpis"]["instant_rejected"])], cols=2)
    if st.session_state.get("_market_ran") == pick:
        st.page_link(st.session_state["_pages"]["overview"], label="Watch it settle on the network →", icon="▶️")


# ================================================================== 3. stress lab
def page_stress() -> None:
    p = palette()
    s = st.session_state
    st.title("Stress lab")
    lede("Break it. Fix it. Find the limit.")
    eyebrow("1 · Break it")
    keys = list(STRESS)
    for row in range(0, len(keys), 4):
        cols = st.columns(4)
        for c, k in zip(cols, keys[row:row + 4]):
            c.button(f"{STRESS_ICON[k]} {STRESS[k]}", key=f"st_{k}", width="stretch", type="primary" if s.stress == k else "secondary",
                     on_click=apply, args=({"stress": k},))

    eyebrow("2 · A vs B")
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
    ui.tiles([dict(label="A · cost of the day", value=ka["cost_usd"], fmt="usd", edge="p", sub=f"{ka['settled_pct']:.2f}% settled · {ka['delay_min']:.1f} min delay"),
              dict(label="B · cost of the day", value=kb["cost_usd"], fmt="usd", edge="a", sub=f"{kb['settled_pct']:.2f}% settled · {kb['delay_min']:.1f} min delay"),
              dict(label=f"B against A · {STRESS[s.stress].lower()}", value=f"{change:+.0f}%", edge="good" if change < 0 else "bad",
                   sub=f"{'cheaper' if change < 0 else 'more expensive'} · {usd(kb['unsettled_usd'] - ka['unsettled_usd'], True)} unsettled")], cols=3)
    fig = go.Figure()
    for name, R, col in (("A", A, p["primary"]), ("B", B, p["accent"])):
        fig.add_trace(go.Scatter(x=R["series"]["t"], y=R["series"]["queued_usd"], name=name, mode="lines", line=dict(color=col, width=3), hovertemplate="%{x}: %{y:$,.3s}<extra>" + name + "</extra>"))
    fig.update_yaxes(tickformat="$.2s", rangemode="tozero")
    fig.update_xaxes(nticks=8)
    st.plotly_chart(layout(fig, 300, title="Value waiting to settle"), config=PLOT)
    log_key = (pa, ta, aa, pb, tb, ab, s.stress)
    if s.get("_cmp_logged") != log_key:
        s._cmp_logged = log_key
        log("compared", {"a": [pa, ta, aa], "b": [pb, tb, ab], "stress": s.stress, "cost_change_pct": round(change, 1)})

    eyebrow("3 · Liquidity sweep")
    if st.button("Sweep opening liquidity from 6% to 30% for A and B"):
        with st.spinner("Twelve simulated days…"):
            s.sweep = {"A": liquidity_sweep(lambda pct: current(policy=pa, controller=ta, auction=aa, liq=pct)),
                       "B": liquidity_sweep(lambda pct: current(policy=pb, controller=tb, auction=ab, liq=pct)), "key": (*log_key, s.seed, s.source)}
    sw = s.get("sweep")
    if sw and sw["key"] == (*log_key, s.seed, s.source):
        fig = make_subplots(rows=1, cols=2, subplot_titles=("Large-value value settled", "Cost of the day"))
        for name, col in (("A", p["primary"]), ("B", p["accent"])):
            xs = [q["liquidity_pct"] for q in sw[name]]
            fig.add_trace(go.Scatter(x=xs, y=[q["settled_pct"] for q in sw[name]], name=name, mode="lines+markers", line=dict(color=col, width=3), marker=dict(size=9)), 1, 1)
            fig.add_trace(go.Scatter(x=xs, y=[q["cost_usd"] for q in sw[name]], name=name, mode="lines+markers", line=dict(color=col, width=3), marker=dict(size=9), showlegend=False), 1, 2)
        fig.update_xaxes(ticksuffix="%", title_text="opening liquidity")
        fig.update_yaxes(ticksuffix="%", row=1, col=1)
        fig.update_yaxes(tickformat="$.2s", row=1, col=2)
        st.plotly_chart(layout(fig, 330, t=40), config=PLOT)

    eyebrow("4 · Breaking point")
    lede("Least liquidity that still settles your target.", "Bisection over opening liquidity for response B")
    target = st.slider("Must settle at least (% of large-value value)", 90.0, 100.0, 99.0, 0.5)
    if st.button("Find the breaking point", type="primary"):
        lo, hi, tried = 2, 40, []
        top = current(policy=pb, controller=tb, auction=ab, liq=hi)
        tried.append((hi, top["kpis"]["settled_pct"]))
        if top["kpis"]["settled_pct"] < target:
            s.rev = {"found": None, "tried": tried, "target": target}
        else:
            while hi - lo > 1:
                mid = (lo + hi) // 2
                v = current(policy=pb, controller=tb, auction=ab, liq=mid)["kpis"]["settled_pct"]
                tried.append((mid, v))
                lo, hi = (lo, mid) if v >= target else (mid, hi)
            s.rev = {"found": hi, "tried": tried, "target": target}
    rv = s.get("rev")
    if rv:
        if rv["found"] is None:
            st.error(f"Even 40% opening liquidity does not settle {rv['target']}% under {STRESS[s.stress].lower()}. The problem is not liquidity alone.")
        else:
            st.success(f"Under **{STRESS[s.stress].lower()}**, response B needs at least **{rv['found']}%** opening liquidity to settle {rv['target']}%. "
                       f"Found in {len(rv['tried'])} simulated days by bisection.")
        t = sorted(rv["tried"])
        fig = go.Figure(go.Scatter(x=[a for a, _ in t], y=[b for _, b in t], mode="lines+markers", line=dict(color=p["primary"], width=3), marker=dict(size=10)))
        fig.add_hline(y=rv["target"], line=dict(color=p["bad"], dash="dot"), annotation_text="target")
        fig.update_xaxes(ticksuffix="%", title_text="opening liquidity")
        fig.update_yaxes(ticksuffix="%")
        st.plotly_chart(layout(fig, 260), config=PLOT)


# ================================================================== 4. your payments
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
        log("uploaded", {"file": up.name, "bytes": up.size})


def page_upload() -> None:
    from atlas.ingest import export_scenario_csv, template_csv
    from atlas.scenario import generate_scenario
    st.title("Your payments")
    lede("Drop a CSV. Every page runs on it.", "Needs sender, receiver, amount, time. Kept in your session only, never stored.")
    c = st.columns(3)
    c[0].download_button("Download the template", template_csv(), "atlas_payments_template.csv", "text/csv", width="stretch")
    c[1].download_button("Download a sample day", export_scenario_csv(generate_scenario(seed=21)), "atlas_sample_day.csv", "text/csv", width="stretch")
    c[2].button("Use the sample day now", width="stretch", on_click=_use_sample, type="primary")
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
    ui.tiles([dict(label="Rows accepted", value=g["accepted"], fmt="int", edge="good"), dict(label="Rows rejected", value=g["rejected_count"], fmt="int", edge="bad" if g["rejected_count"] else "good"),
              dict(label="Banks found", value=g["totals"]["institutions"], fmt="int", edge="p"), dict(label="Value", value=g["totals"]["value_minor"] / 100, fmt="usd", edge="a")], cols=4)
    if g["assumptions"]:
        st.warning("**Assumed, because the file does not say:**\n\n" + "\n".join(f"- {a}" for a in g["assumptions"]))
    if g["rejected"]:
        st.error("**Rejected rows (never silently fixed):**")
        st.dataframe(pd.DataFrame(g["rejected"]), hide_index=True, width="stretch")
    badges(r)
    ui.tiles(kpi_items(r, None), cols=3)
    st.success(f"**{st.session_state.csv_name}** is loaded. Every page now runs on it.")
    st.download_button("Download this run (JSON)", json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, indent=1), "atlas_run.json", "application/json")


# ================================================================== 5. alerts and cases
def _narrative(a: dict, pays: list[dict]) -> str:
    sender_day = [x for x in pays if x["sender"] == a["sender"]]
    corridor = [x["amount_minor"] for x in pays if x["sender"] == a["sender"] and x["receiver"] == a["receiver"] and x["rail"] == a["rail"] and x["payment_id"] != a["payment_id"]]
    med = statistics.median(corridor) if corridor else None
    lines = [f"Payment {a['payment_id']} of {usd(a['amount_minor'] / 100)} from {a['sender']} to {a['receiver']} on {a['rail'].upper()} at {a['at'][11:19]} UTC "
             f"was flagged for: {a['reason']} (score {a['score']:.1f}).",
             f"{a['sender']} sent {len(sender_day)} payments today totalling {usd(sum(x['amount_minor'] for x in sender_day) / 100)}."]
    if med:
        lines.append(f"The other {len(corridor)} {a['rail'].upper()} payments in this corridor today have a median of {usd(med / 100)}; this one is {a['amount_minor'] / med:.1f}× that.")
    else:
        lines.append("No other payment used this corridor today, so there is no corridor baseline.")
    lines.append("Every figure above is computed from the day's ledger. Recommended next step: confirm with the sender's operations desk before any action.")
    return " ".join(lines)


def page_alerts() -> None:
    from atlas.detect import score_payments
    from atlas.workspace import DECISIONS
    p = palette()
    st.title("Alerts and cases")
    lede("Pick a case. Decide. Your team sees it.", "Nothing is blocked automatically; a person decides every alert")
    r = current()
    run_id = r["integrity"]["state_hash"]
    pays = r["_run"]["payments"]
    n = st.slider("Review budget (payments a person can check today)", 5, 60, 20, step=5)
    out = score_payments(pays, top=n)
    alerts = out["alerts"]
    dec = workspace().decisions(run_id)
    done = sum(1 for a in alerts if a["payment_id"] in dec)
    ui.tiles([dict(label="Payments scored", value=out["payments_scored"], fmt="int", edge="p"), dict(label="Alerts in queue", value=len(alerts), fmt="int", edge="a"),
              dict(label="Decided", value=done, fmt="int", edge="good", sub=f"{done}/{len(alerts)} cases · team-wide"),
              dict(label="Escalated or reported", value=sum(1 for a in alerts if dec.get(a["payment_id"], {}).get("decision") in ("escalate", "file_report")), fmt="int", edge="bad")], cols=4)
    if not alerts:
        st.info("Nothing unusual enough to flag on this day.")
        return
    icon = {"clear": "Cleared", "escalate": "Escalated", "file_report": "Reported"}
    df = pd.DataFrame([{"Status": icon.get(dec.get(a["payment_id"], {}).get("decision"), "Open"), "Score": a["score"], "Why flagged": a["reason"], "From": a["sender"], "To": a["receiver"],
                        "Rail": a["rail"], "Amount": a["amount_minor"] / 100, "Time (UTC)": a["at"][11:19], "Payment": a["payment_id"]} for a in alerts])
    left, right = st.columns([5, 4])
    with left:
        eyebrow("Queue")
        ev = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", height=420, key="alert_tbl",
                          column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=float(df["Score"].max()), format="%.1f"),
                                         "Amount": st.column_config.NumberColumn(format="dollar")})
        rows = ev.selection.rows if ev and getattr(ev, "selection", None) else []
    i = rows[0] if rows else next((k for k, a in enumerate(alerts) if a["payment_id"] not in dec), 0)
    a = alerts[i]
    with right:
        eyebrow(f"Case · {a['payment_id']}")
        st.markdown(f'<div class="card edge-a"><div class="k">{a["reason"]} · score {a["score"]:.1f}</div><div class="v">{usd(a["amount_minor"] / 100)}</div>'
                    f'<div class="s">{a["sender"]} → {a["receiver"]} · {a["rail"].upper()} · {a["at"][11:19]} UTC</div></div>', unsafe_allow_html=True)
        mine = [x for x in pays if x["sender"] == a["sender"]]
        fig = go.Figure(go.Scatter(x=[x["arrival"][11:16] for x in mine], y=[x["amount_minor"] / 100 for x in mine], mode="markers",
                                   marker=dict(size=7, color=rgba(p["primary"], 0.45)), name="sender's other payments", hovertemplate="%{x}: %{y:$,.3s}<extra></extra>"))
        hit = next((x for x in mine if x["payment_id"] == a["payment_id"]), None)
        if hit:
            fig.add_trace(go.Scatter(x=[hit["arrival"][11:16]], y=[hit["amount_minor"] / 100], mode="markers", name="this payment",
                                     marker=dict(size=16, color=p["accent"], line=dict(color="#fff", width=2))))
        fig.update_yaxes(type="log", tickformat="$.2s")
        fig.update_xaxes(type="category", categoryorder="category ascending", nticks=8)
        st.plotly_chart(layout(fig, 230, title=f"Everything {a['sender']} sent today"), config=PLOT)
        st.markdown(f'<div class="cite">{_narrative(a, pays)}</div>', unsafe_allow_html=True)
        prev = dec.get(a["payment_id"])
        if prev:
            st.caption(f"Decided by **{prev['user']}** at {prev['at'][:16].replace('T', ' ')} UTC: **{prev['decision']}**. {prev['note']}")
        note = st.text_input("Note for the file", key=f"note_{a['payment_id']}", placeholder="what you checked, who you called")
        b = st.columns(3)
        for c, d, label in zip(b, DECISIONS, (":material/check: Clear", ":material/priority_high: Escalate", ":material/description: File report")):
            if c.button(label, key=f"d_{d}_{a['payment_id']}", width="stretch", type="primary" if d == "escalate" else "secondary"):
                workspace().decide(who(), a["payment_id"], run_id, d, note)
                st.toast(f"{a['payment_id']}: {d} · saved for the team")
                st.rerun()
    det = artifact("anomaly_detection.json")
    if det and det.get("explainability"):
        eyebrow("Inside the model")
        imp = det["explainability"]["gbt"][:7][::-1]
        a2, b2 = st.columns(2)
        fig = go.Figure(go.Bar(y=[x["feature"].replace("_", " ") for x in imp], x=[x["drop_in_pr_auc"] for x in imp], orientation="h", marker=dict(color=p["primary"])))
        a2.plotly_chart(layout(fig, 280, title="Permutation importance (drop in PR-AUC)"), config=PLOT)
        rob = det["robustness"]["gbt"]
        fig = go.Figure(go.Scatter(x=[x["feature_noise_sd"] * 100 for x in rob], y=[x["pr_auc"] for x in rob], mode="lines+markers", line=dict(color=p["accent"], width=3), marker=dict(size=9)))
        fig.update_xaxes(ticksuffix="%", title_text="noise added to every input")
        b2.plotly_chart(layout(fig, 280, title="PR-AUC as inputs get noisier"), config=PLOT)


# ================================================================== 6. controls
def page_controls() -> None:
    p = palette()
    st.title("Controls")
    r = current()
    t1, t2 = st.tabs(["Intraday liquidity report (BCBS 248)", "Tamper with the ledger"])
    with t1:
        lede("Who ran out of liquidity, and when.", "BCBS 248 intraday liquidity monitoring")
        banks = sorted(r["banks"], key=lambda x: -x["usage_pct"])
        over = sum(1 for b in banks if b["usage_pct"] > 100)
        ui.tiles([dict(label="Banks over their liquidity", value=over, fmt="int", edge="bad" if over else "good"),
                  dict(label="Highest usage", value=banks[0]["usage_pct"], fmt="pct1", edge="warn", sub=banks[0]["id"]),
                  dict(label="Timed obligations late", value=r["kpis"]["late_timed"], fmt="int", edge="a"),
                  dict(label="Timed obligations failed", value=r["kpis"]["failed_timed"], fmt="int", edge="bad" if r["kpis"]["failed_timed"] else "good")], cols=4)
        a, b = st.columns([3, 2])
        fig = go.Figure(go.Bar(y=[x["id"] for x in banks][::-1], x=[x["usage_pct"] for x in banks][::-1], orientation="h",
                               marker=dict(color=[p["bad"] if x["usage_pct"] > 100 else p["primary"] for x in banks][::-1]), hovertemplate="%{y}: %{x:.0f}%<extra></extra>"))
        fig.add_vline(x=100, line=dict(color=p["bad"], dash="dot"))
        fig.update_xaxes(ticksuffix="%")
        a.plotly_chart(layout(fig, max(300, 26 * len(banks)), title="Peak usage of available liquidity"), config=PLOT)
        T = r["throughput"]
        fig = go.Figure(go.Bar(x=T["hours"], y=[v * 100 for v in T["share"]], marker=dict(color=p["accent2"])))
        fig.update_yaxes(ticksuffix="%", range=[0, 100])
        b.plotly_chart(layout(fig, 300, title="Share of the day's payments sent, by hour"), config=PLOT)
        st.download_button("Download the full report (JSON)", json.dumps(r["_bcbs"], indent=1), "intraday_liquidity_bcbs248.json", "application/json")
    with t2:
        lede("Change one payment by 1%. Watch it get caught.", "SHA-256 hash chain + full ledger replay")
        res = r["_result"]
        n_settled = sum(1 for e in res.events if e.event_type == "PaymentSettled")
        which = st.slider("Which settled payment to alter", 1, n_settled, min(n_settled, 250))
        t = tamper_check(res, which - 1)
        ui.tiles([dict(label=f"Payment {t['payment']}", value=t["amount_before_minor"] / 100, fmt="usd", edge="p", sub=f"quietly changed to {usd(t['amount_after_minor'] / 100)}"),
                  dict(label="Hash chain", value="caught" if t["chain_caught"] else "missed", edge="good" if t["chain_caught"] else "bad", sub=f"{t['links_invalidated']:,} later links broken"),
                  dict(label="Ledger replay", value="caught" if t["replay_caught"] else "missed", edge="good" if t["replay_caught"] else "bad",
                       sub=f"untouched log replays: {'yes' if t['untouched_replay_ok'] else 'no'}")], cols=3)
        st.code(f"chain head, original : {t['chain_head_original']}\nchain head, tampered : {t['chain_head_tampered']}\nreplay says          : {t['replay_message']}", language=None)


# ================================================================== 7. model risk
def page_models() -> None:
    from atlas.governance import build_inventory
    st.title("Model risk")
    inv = build_inventory(ROOT / "results")
    lede("Every model, checked. Some fail.", "SR 26-2 structure: owner, materiality tier, challenger, automated checks")
    sm = inv["summary"]
    ui.tiles([dict(label="Models in inventory", value=len(inv["models"]), fmt="int", edge="p"), dict(label="Pass", value=sm["pass"], fmt="int", edge="good"),
              dict(label="Warn", value=sm["warn"], fmt="int", edge="warn"), dict(label="Fail", value=sm["fail"], fmt="int", edge="bad")], cols=4)
    icon = {"pass": ":material/check_circle:", "warn": ":material/error:", "fail": ":material/cancel:"}
    flt = st.segmented_control("Show", ["all", "fail", "warn", "pass"], default="all") or "all"
    for m in inv["models"]:
        if flt != "all" and m["status"] != flt:
            continue
        with st.expander(f"{m['name']}  ·  tier {m['materiality']['tier']}  ·  {m['status'].upper()}", icon=icon[m["status"]]):
            lede(m["purpose"], f"Challenger: {m['challenger']}")
            st.dataframe(pd.DataFrame([{"Status": c["status"].upper(), "Check": c["check"], "Value": str(c["value"]), "Rule": c["rule"]} for c in m["checks"]]), hide_index=True, width="stretch")
            st.markdown("**Limits:** " + "; ".join(m["limitations"]))
    lede("", inv["disclaimer"])


# ================================================================== 8. agent
@st.cache_resource(show_spinner=False)
def _router():
    path = ROOT / "results" / "models" / "tool_router.pt"
    try:
        from atlas.agent.router import NeuralRouter
        return NeuralRouter.load(path) if path.exists() else None
    except Exception:  # noqa: BLE001 - no torch on this host
        return None


EXAMPLES = ["What percentage of large-value value settles under combined stress?", "Which institution is most stretched on intraday liquidity under combined stress?",
            "Under combined stress, by what percentage does cost change if we add the MPC controller and a uniform price auction?",
            "According to the rulebook, what is the FedNow transaction limit? Cite the document.", "Move $50 million from RTGS to FedNow for bank-003 right now."]


def _answer(q: str, session) -> dict:
    from atlas.agent.evals import planner_agent, route_by_keywords, ungrounded_numbers
    s = st.session_state
    base, model, key = s.get("llm_base"), s.get("llm_model"), s.get("llm_key")
    route = route_by_keywords(q)
    try:
        if base and model:
            from atlas.agent.llm import LLMAgent, OpenAICompatClient
            out, by = LLMAgent(OpenAICompatClient(base, model, key))(q, session), f"model {model}"
        elif s.get("use_router") and _router() is not None:
            from atlas.agent.router import RouterAgent
            out = RouterAgent(_router(), min_confidence=0.6)(q, session)
            route, by = out["route"], f"trained router ({out['route']['decided_by']})"
        else:
            out, by = planner_agent(q, session), "keyword planner"
    except Exception as exc:  # noqa: BLE001 - endpoint errors are shown
        out, by = {"answer": f"The model endpoint failed: {exc}", "trace": []}, "error"
    bad = ungrounded_numbers(out["answer"], out["trace"], q)
    log("asked", {"q": q[:160], "by": by, "grounded": not bad})
    return {"q": q, "answer": out["answer"], "trace": out["trace"], "bad": bad, "by": by, "intent": route.get("intent", "?")}


def _steps(m: dict) -> list[dict]:
    tools = [t["tool"] for t in m["trace"]]
    cited = [p["citation"] for t in m["trace"] if isinstance(t.get("result"), dict) for p in t["result"].get("passages", [])][:1]
    return [{"k": "Asked", "v": f"{who()}"}, {"k": "Router chose", "v": m["intent"]},
            {"k": f"Read-only tools · {len(tools)}", "v": ", ".join(dict.fromkeys(tools)) or "none: refused to act", "ok": None},
            {"k": "Cited" if cited else "Checked", "v": cited[0] if cited else ("every number traced" if not m["bad"] else "untraced: " + ", ".join(m["bad"])), "ok": not m["bad"]},
            {"k": "Answered", "v": "with evidence" if m["trace"] else "refusal, no tool run", "ok": True}]


def _show(m: dict) -> None:
    ui.pipeline(_steps(m))
    st.markdown(m["answer"])
    st.markdown(f'<span class="tag {"ok" if not m["bad"] else "no"}">Grounding <b>{"every number traced ✓" if not m["bad"] else "not traced: " + ", ".join(m["bad"])}</b></span>'
                f'<span class="tag">Answered by <b>{m["by"]}</b></span><span class="tag"><b>{len(m["trace"])}</b> tool calls</span>', unsafe_allow_html=True)
    for t in m["trace"]:
        args = t.get("args")
        with st.expander(f":material/build: {t['tool']}({', '.join(f'{k}={v}' for k, v in args.items()) if isinstance(args, dict) else ''})"):
            res = t.get("result", t.get("error"))
            if isinstance(res, dict) and "passages" in res:
                for q in res["passages"]:
                    st.markdown(f'<div class="cite"><b>{q["citation"]}</b><br>{q["text"][:420]}</div>', unsafe_allow_html=True)
            else:
                st.json(res, expanded=False)


def page_agent() -> None:
    from atlas.agent.tools import ToolSession
    st.title("Agent")
    lede("Ask anything. It can look, never move money.", "9 read-only tools · every number checked against tool output · hash-chained audit")
    r = current()
    sid = r["scenario"]["fingerprint"]
    s = st.session_state
    if s.get("ask_sid") != sid:
        s.ask_sid, s.ask_session, s.chat = sid, ToolSession(r["_scenario"], max_calls=200, max_simulations=40), []
    session = s.ask_session
    with st.sidebar.expander("Connect a language model (optional)"):
        st.text_input("Base URL", placeholder="https://…/v1", key="llm_base")
        st.text_input("Model", key="llm_model")
        st.text_input("API key", type="password", key="llm_key")
    if _router() is not None:
        st.toggle("Understand questions with the Transformer trained in this repo", key="use_router")
    t1, t2, t3 = st.tabs(["Watch it work", "Ask", "Audit log"])
    with t1:
        short = dict(zip(["Settled share", "Most stretched bank", "Optimiser savings", "FedNow limit", "Move $50M (refused)"], EXAMPLES))
        pick = st.pills("Try", list(short), default="Settled share", key="demo_pill", label_visibility="collapsed") or "Settled share"
        q = short[pick]
        st.markdown(f"<div class='cite'>“{q}”</div>", unsafe_allow_html=True)
        if s.get("_demo_q") != q:
            s._demo_q, s._demo = q, _answer(q, session)
        _show(s._demo)
    with t2:
        for m in s.chat:
            with st.chat_message("user"):
                st.markdown(m["q"])
            with st.chat_message("assistant"):
                _show(m)
        asked = st.chat_input("Ask about this day, or what the rulebook says")
        if asked:
            s.chat.append(_answer(asked, session))
            st.rerun()
    with t3:
        ok = session.verify_audit()
        st.markdown(f'<span class="tag {"ok" if ok else "no"}">Audit chain <b>{"intact ✓" if ok else "BROKEN"}</b></span><span class="tag"><b>{len(session.audit)}</b> tool calls</span>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"#": a["seq"], "Tool": a["tool"], "Arguments": json.dumps(a["args"]), "ms": a.get("ms"), "Hash": a["hash"][:16] + "…"} for a in session.audit]),
                     hide_index=True, width="stretch")


# ================================================================== 9. evidence
NAMES = {"priority": "Priority queue", "fifo": "FIFO", "fifo_strict": "Strict FIFO", "bilateral": "Bilateral offset", "multilateral": "Multilateral heuristic",
         "multilateral_milp": "Exact MILP netting", "auction_pay_as_bid": "Auction: pay as bid", "auction_uniform": "Auction: uniform price",
         "rule_rebalancer": "Rule-based treasury", "mpc": "MPC rebalancing", "mpc_queue_milp": "MPC + queue MILP", "mpc_plus_auction": "MPC + auction"}


def page_evidence() -> None:
    p = palette()
    st.title("Evidence")
    lede("1,320 simulated days and real fraud data.", "Paired bootstrap statistics; every chart reads a results file in the repo")
    t1, t2, t3, t4, t5, t6 = st.tabs(["Which response wins", "Every bad day", "Real fraud data", "Deep learning", "Retrieval and agents", "What banks hire for"])
    with t1:
        b = artifact("benchmarks/extended.json") or artifact("benchmarks/standard.json")
        if b:
            c = st.columns(2)
            stress = c[0].selectbox("Stress", b["config"]["stresses"], format_func=lambda x: STRESS.get(x, x))
            metric = c[1].selectbox("Measure", ["total_cost_minor", "lv_settlement_rate_value", "lv_value_weighted_delay_s", "instant_rejected"],
                                    format_func={"total_cost_minor": "Cost of the day", "lv_settlement_rate_value": "Large-value value settled",
                                                 "lv_value_weighted_delay_s": "Delay", "instant_rejected": "Instant payments rejected"}.get)
            rows = [x for x in b["comparison"] if x["stress"] == stress and x["metric"] == metric]
            lower = metric != "lv_settlement_rate_value"
            rows.sort(key=lambda x: x["mean"], reverse=lower)
            k = {"total_cost_minor": 0.01, "lv_settlement_rate_value": 100, "lv_value_weighted_delay_s": 1 / 60, "instant_rejected": 1}[metric]
            col = [p["accent3"] if not x["significant"] else (p["primary"] if (x["mean_diff"] < 0) == lower else p["accent"]) for x in rows]
            fig = go.Figure(go.Bar(y=[NAMES.get(x["arm"], x["arm"]) for x in rows], x=[x["mean"] * k for x in rows], orientation="h", marker=dict(color=col),
                                   error_x=dict(type="data", symmetric=False, array=[(x["ci95_diff"][1] - x["mean_diff"]) * k for x in rows],
                                                arrayminus=[(x["mean_diff"] - x["ci95_diff"][0]) * k for x in rows], color=p["ink2"], thickness=1.2)))
            st.plotly_chart(layout(fig, 60 + 34 * len(rows)), config=PLOT)
            st.caption(f"{b['manifest']['runs']:,} runs, every ledger replayed. Navy = significantly better than the priority queue (95% paired bootstrap), accent = worse, grey = no clear difference.")
    with t2:
        b = artifact("benchmarks/extended.json")
        if b:
            arms = ["multilateral_milp", "rule_rebalancer", "mpc", "auction_uniform", "mpc_plus_auction"]
            comp = {(x["stress"], x["arm"]): x for x in b["comparison"] if x["metric"] == "total_cost_minor"}
            ss = b["config"]["stresses"]
            z = [[comp[(s_, a)]["rel_diff"] * 100 if comp[(s_, a)]["significant"] else None for a in arms] for s_ in ss]
            text = [[f"{v:+.0f}%" if v is not None else "n.s." for v in row] for row in z]
            fig = go.Figure(go.Heatmap(z=z, x=[NAMES[a] for a in arms], y=[STRESS.get(s_, s_) for s_ in ss], text=text, texttemplate="%{text}",
                                       colorscale=[[0, p["primary"]], [1, "#FFFFFF"]], zmin=-70, zmax=0, colorbar=dict(ticksuffix="%", title="cost vs queue")))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(layout(fig, 460), config=PLOT)
    with t3:
        f = artifact("real_fraud.json")
        if f:
            ds, de = f["dataset"], f["design"]
            lede(f"{ds['rows']:,} real card transactions, {ds['frauds']} real frauds.", f"{ds['name']}, {ds['period']}; trained on first 80% in time, tested on last 20%")
            nice = {"amount_only_rule": "Rule: largest amounts", "isolation_forest": "Isolation forest (no labels)", "logistic_regression": "Logistic regression", "gradient_boosting": "Gradient boosting"}
            fig = go.Figure(go.Bar(y=list(nice.values()), x=[f["models"][m]["frauds_caught"] for m in nice], orientation="h",
                                   marker=dict(color=[p["accent3"], p["accent"], p["accent2"], p["primary"]]), text=[f'{f["models"][m]["frauds_caught"]} of {de["test_frauds"]}' for m in nice], textposition="outside"))
            fig.update_xaxes(range=[0, de["test_frauds"] * 1.25])
            a, b2 = st.columns([3, 2])
            a.plotly_chart(layout(fig, 300, title=f"Real frauds caught reviewing {de['alert_rate']:.1%} of transactions"), config=PLOT)
            g, sh = f["models"]["gradient_boosting"], f["shuffled_split_gradient_boosting"]
            b2.metric("Tested on the future (honest)", f"PR-AUC {g['pr_auc']:.3f}")
            b2.metric("Shuffled split (flattering)", f"PR-AUC {sh['pr_auc']:.3f}", delta=f"+{f['split_optimism_pr_auc']:.3f} optimism", delta_color="off")
            b2.metric("Largest train-test drift", f"PSI {f['drift'][0]['psi_train_vs_test']:.2f}")
    with t4:
        d = artifact("deep_forecasting.json")
        if d:
            c = st.columns(2)
            size = c[0].segmented_control("Training days", d["train_sizes_days"], default=d["train_sizes_days"][-1]) or d["train_sizes_days"][-1]
            hz = c[1].segmented_control("Horizon", ["15m", "1h"], default="15m") or "15m"
            rows = sorted([x for x in d["results"] if x["train_days"] == size and x["horizon"] == hz], key=lambda x: x["mase"])
            fig = go.Figure(go.Bar(x=[x["model"].replace("_", " ") for x in rows], y=[x["mase"] for x in rows], text=[f"{x['mase']:.3f}" for x in rows], textposition="outside",
                                   marker=dict(color=[p["primary"] if x["model"] in ("gru", "transformer") else p["accent3"] for x in rows])))
            a, b2 = st.columns(2)
            a.plotly_chart(layout(fig, 330, title="Forecast error (MASE, lower is better)"), config=PLOT)
            fig = go.Figure()
            for name, colr in (("gru", p["primary"]), ("transformer", p["accent"])):
                h = d["training_curves"].get(f"{name}|{size}|{hz}")
                if h:
                    fig.add_trace(go.Scatter(x=[e["epoch"] for e in h], y=[e["holdout_loss"] for e in h], name=f"{name} held-out", line=dict(color=colr, width=3)))
                    fig.add_trace(go.Scatter(x=[e["epoch"] for e in h], y=[e["train_loss"] for e in h], name=f"{name} train", line=dict(color=colr, width=1.5, dash="dot")))
            b2.plotly_chart(layout(fig, 330, title="Training curves"), config=PLOT)
    with t5:
        tr = artifact("tool_router.json")
        if tr:
            nm = {"byte_transformer": f"Transformer ({tr['model']['parameters']:,} params)", "tfidf_logreg": "TF-IDF + logistic regression", "keyword_rules": "Keyword rules"}
            fig = go.Figure()
            for key, label, colr in (("unseen_templates", "Unseen templates", p["primary"]), ("handwritten", "Hand-written questions", p["accent"])):
                fig.add_trace(go.Bar(x=list(nm.values()), y=[tr["routing"][m][key]["exact_route_accuracy"] * 100 for m in nm], name=label, marker=dict(color=colr)))
            fig.update_yaxes(ticksuffix="%", range=[0, 105])
            st.plotly_chart(layout(fig, 320, barmode="group", title="Questions routed to exactly the right tool plan"), config=PLOT)
        k, e = artifact("retrieval_eval.json"), artifact("agent_evals.json")
        a, b2 = st.columns(2)
        if k:
            m = k["methods"]["bm25"]
            a.metric("Rulebook retrieval: right document first", f"{m['hit_at_1']:.0%}")
            a.metric("Right document in the top three", f"{m['hit_at_3']:.0%}")
        if e:
            b2.dataframe(pd.DataFrame([{"Agent": x["agent"], "Right tools": f"{x['tools']:.0%}", "Right answer": f"{x['correct']:.0%}", "No invented numbers": f"{x['grounded']:.0%}",
                                        "Refuses to execute": f"{x['safe']:.0%}", "Passes all": f"{x['pass_rate']:.0%}"} for x in e["agents"]]), hide_index=True, width="stretch")
            b2.caption("Two control agents are broken on purpose: an evaluation that cannot fail a bad agent proves nothing.")
    with t6:
        path = ROOT / "data" / "hiring_map.json"
        if path.exists():
            h = json.loads(path.read_text())
            mark = {2: "●", 1: "○", 0: "–"}
            st.dataframe(pd.DataFrame([{"What postings ask for": x["skill"], "Junior": mark[x["junior"]], "Senior": mark[x["senior"]], "Director+": mark[x["director"]],
                                        "Where in ATLAS": x["where"]} for x in h["rows"]]), hide_index=True, width="stretch", height=36 * len(h["rows"]) + 40)
            st.caption(f"● required, ○ preferred. {h['postings']} public postings at {', '.join(h['banks'])}. Sources: docs/25_industry_landscape.md.")


# ================================================================== 10. team
@st.cache_data(ttl=600, show_spinner=False)
def github_reviews() -> list[dict] | None:
    import urllib.request
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/issues?state=all&labels=review&per_page=50", headers={"Accept": "application/vnd.github+json", "User-Agent": "atlas-app"})
        with urllib.request.urlopen(req, timeout=6) as resp:  # noqa: S310 - fixed GitHub API URL
            return [{"title": i["title"], "by": i["user"]["login"], "url": i["html_url"], "at": i["created_at"][:10]} for i in json.loads(resp.read()) if "pull_request" not in i]
    except Exception:  # noqa: BLE001 - offline: say so, never invent reviews
        return None


def page_team() -> None:
    ws = workspace()
    from atlas_app.state import workspace_status
    backend, problem = workspace_status()
    st.title("Team")
    if problem:
        st.warning(f"Shared database not connected, so history resets on redeploy. Reason: {problem}")
    lede("Who used it, what they did, what they said.", "Shared workspace, hash-chained so edits show")
    people, events, reviews = ws.people(), ws.events(300), ws.reviews()
    ok = ws.verify()
    ui.tiles([dict(label="People", value=len([x for x in people if x["user"] != "guest"]), fmt="int", edge="p", sub="named users of this deployment"),
              dict(label="Actions logged", value=sum(x["n"] for x in people), fmt="int", edge="a"),
              dict(label="Reviews here", value=len(reviews), fmt="int", edge="good", sub=(f"average {sum(x['stars'] for x in reviews) / len(reviews):.1f} ★" if reviews else "none yet")),
              dict(label="Activity chain", value="intact" if ok else "broken", edge="good" if ok else "bad",
                   sub="permanent database" if backend == "postgres" else "temporary storage")], cols=4)
    t1, t2, t3 = st.tabs(["Activity", "Reviews", "People"])
    with t1:
        nice = VERBS
        if not events:
            st.info("Nothing yet. Put your name in the sidebar and run a day.")
        for e in events[:60]:
            d = e["detail"]
            extra = (f" · {STRESS.get(d.get('stress'), d.get('stress'))}" if d.get("stress") else "") + (f" · “{d['q'][:80]}”" if d.get("q") else "") + \
                    (f" · {d['payment']} → {d['decision']}" if d.get("decision") else "") + (f" · {d['stars']}★" if d.get("stars") else "")
            st.markdown(f"<span class='tag'><b>{e['user']}</b></span> {nice.get(e['kind'], e['kind'])}{extra} <span style='color:#8A93A8;font-size:.8rem'>· {e['at'][:16].replace('T', ' ')} UTC · #{e['seq']}</span>",
                        unsafe_allow_html=True)
        st.download_button("Export the workspace (JSON)", json.dumps(ws.export(), indent=1, default=str), "atlas_workspace.json", "application/json", on_click=lambda: log("exported"))
    with t2:
        a, b = st.columns([3, 2])
        with a:
            stars = st.feedback("stars", key="rev_stars")
            role = st.text_input("I am a", placeholder="payments engineer, treasury analyst, ML engineer, student…")
            worked = st.text_area("What worked", height=90)
            broke = st.text_area("What broke or confused me", height=90)
            c1, c2 = st.columns(2)
            if c1.button("Save my review here", type="primary", disabled=stars is None or not (worked or broke), width="stretch"):
                ws.review(who(), role, stars + 1, worked, broke)
                st.toast("Saved. Thank you!")
                st.rerun()
            c2.link_button("Or post it on GitHub →", review_url(REPO, rating=(stars + 1) if stars is not None else None, role=role, tried=[], worked=worked, broke=broke, would_use=""),
                           width="stretch")
        with b:
            for x in reviews[:20]:
                st.markdown(f'<div class="card edge-a"><div class="k">{x["user"]} · {x["role"] or "—"} · {x["at"][:10]}</div><div class="v">{"★" * x["stars"]}{"☆" * (5 - x["stars"])}</div>'
                            f'<div class="s">{(x["worked"] or "")[:200]}<br><i>{(x["broke"] or "")[:200]}</i></div></div>', unsafe_allow_html=True)
            gh = github_reviews()
            if gh:
                eyebrow("On GitHub")
                for x in gh:
                    st.markdown(f"**[{x['title']}]({x['url']})** · @{x['by']} · {x['at']}")
    with t3:
        names = [x["user"] for x in people if x["user"] != "guest"]
        if not names:
            st.info("No named users yet.")
        else:
            pick = st.pills("Person", names, default=names[0], key="team_pick", label_visibility="collapsed") or names[0]
            ui.journey(pick, visits_of(pick), returning=True, viewer=False)