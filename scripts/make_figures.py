"""Render README figures (light + dark SVG) from the artifacts in results/. Every value plotted is read from results/*.json
or produced by a fresh simulation run here; nothing is typed in by hand.

Usage: python scripts/make_figures.py [policy intraday scaling auction rl forecast netting replication]
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "docs" / "assets"

# Validated reference palette (dataviz skill references/palette.md), light and dark steps.
THEMES = {
    "light": {"bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e4e3df", "neutral": "#a8a7a2",
              "s": ["#2a78d6", "#eb6834", "#1baf7a"], "bad": "#e34948"},
    "dark": {"bg": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "grid": "#33322f", "neutral": "#6b6a64",
             "s": ["#3987e5", "#d95926", "#199e70"], "bad": "#e66767"},
}
usd = FuncFormatter(lambda v, _: f"${v / 1e8:,.1f}M" if abs(v) >= 1e7 else f"${v / 100:,.0f}")


def load(name: str):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def style(ax, t, title: str, subtitle: str = ""):
    fig = ax.figure
    fig.patch.set_facecolor(t["bg"])
    ax.set_facecolor(t["bg"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=9, length=0)
    ax.grid(True, axis="both", color=t["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(t["ink2"])
    ax.yaxis.label.set_color(t["ink2"])
    fig.text(0.012, 0.965, title, color=t["ink"], fontsize=12.5, fontweight="bold", va="top", ha="left")
    if subtitle:
        fig.text(0.012, 0.905, subtitle, color=t["ink2"], fontsize=9, va="top", ha="left")


def legend(ax, t, **kw):
    lg = ax.legend(frameon=False, fontsize=9, labelcolor=t["ink2"], **kw)
    return lg


def save(fig, name: str, theme: str):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}-{theme}.svg", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)


# ----------------------------------------------------------------------------------------------- figures
def fig_policy(t, theme, bench):
    arms = ["priority", "multilateral_milp", "auction_uniform", "rule_rebalancer", "mpc", "mpc_queue_milp", "mpc_plus_auction"]
    labels = {"priority": "Priority queue (reference)", "multilateral_milp": "Exact MILP netting", "auction_uniform": "Liquidity auction",
              "rule_rebalancer": "Rule-based treasury", "mpc": "MPC rebalancing", "mpc_queue_milp": "MPC + queue MILP",
              "mpc_plus_auction": "MPC + auction"}
    comp = {(c["stress"], c["arm"]): c for c in bench["comparison"] if c["metric"] == "total_cost_minor"}
    arms = [a for a in arms if ("baseline", a) in comp]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.1), sharey=True)
    for ax, stress, ttl in zip(axes, ("baseline", "combined"), ("Normal day", "Combined stress")):
        ys = list(range(len(arms)))[::-1]
        for y, a in zip(ys, arms):
            c = comp[(stress, a)]
            color = t["neutral"] if a == "priority" else (t["s"][0] if c["significant"] and c["mean_diff"] < 0 else t["s"][1] if c["significant"] else t["neutral"])
            ax.barh(y, c["mean"], height=0.62, color=color, edgecolor=t["bg"], linewidth=2)
            end = c["mean"]
            if a != "priority":
                # CI of the paired difference, re-centred on this arm's mean
                lo = c["mean"] + (c["ci95_diff"][0] - c["mean_diff"])
                hi = c["mean"] + (c["ci95_diff"][1] - c["mean_diff"])
                ax.plot([lo, hi], [y, y], color=t["ink"], lw=1.2)
                ax.plot([lo, lo], [y - 0.12, y + 0.12], color=t["ink"], lw=1.2)
                ax.plot([hi, hi], [y - 0.12, y + 0.12], color=t["ink"], lw=1.2)
                end = max(end, hi)
            ax.text(end, y, f"  ${c['mean'] / 1e8:.2f}M", va="center", ha="left", fontsize=8.5, color=t["ink2"])
        ax.set_yticks(ys)
        ax.set_yticklabels([labels[a] for a in arms])
        ax.xaxis.set_major_formatter(usd)
        ax.set_title(ttl, color=t["ink"], fontsize=10, loc="left")
        style(ax, t, "Modeled cost per simulated day: lower is better",
              f"NEXUS-PAY standard, {len(bench['config']['seeds'])} paired seeds. Blue = significantly cheaper than the priority queue (95% bootstrap CI); line = CI of the paired difference.")
        ax.set_xlim(0, max(comp[(stress, a)]["mean"] for a in arms) * 1.32)
    fig.subplots_adjust(top=0.8, wspace=0.08)
    save(fig, "policy-cost", theme)


def fig_intraday(t, theme):
    from datetime import datetime

    from atlas.control import MPCConfig, MPCController
    from atlas.scenario import generate_scenario
    from atlas.sim import SimulationSettings, run_day
    from atlas.stress import build_scenario
    sc = generate_scenario(seed=11)
    runs = {"Priority queue": run_day(sc, SimulationSettings(policy="priority"), build_scenario("combined")),
            "MPC rebalancing": run_day(sc, SimulationSettings(policy="multilateral"), build_scenario("combined"),
                                       controller=MPCController(MPCConfig(enable_queue_milp=False)))}
    fig, ax = plt.subplots(figsize=(10.5, 3.9))
    for k, (name, r) in enumerate(runs.items()):
        x = [datetime.fromisoformat(row["t"]) for row in r.timeseries]
        y = [row["rtgs_queued_value_minor"] + row["lsm_queued_value_minor"] + row["held_value_minor"] for row in r.timeseries]
        color = [t["s"][1], t["s"][0]][k]
        ax.plot(x, y, color=color, lw=2, label=f"{name}: {r.metrics['large_value']['settlement_rate_value'] * 100:.1f}% settled")
        ax.fill_between(x, y, color=color, alpha=0.08)
    for sh in build_scenario("combined").shocks:
        start = getattr(sh, "start_min", getattr(sh, "at_min", None))
        if start is not None:
            ax.axvline(sc.open_at + __import__("datetime").timedelta(minutes=start), color=t["neutral"], lw=0.8, ls=":")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=__import__("zoneinfo").ZoneInfo("America/New_York")))
    ax.yaxis.set_major_formatter(usd)
    legend(ax, t, loc="upper left")
    style(ax, t, "Same day, same shocks: value waiting to settle (held + queued)",
          "Combined stress (counterparty outage, credit cut, hoarding, RTGS outage). Dotted lines = shock times. Times ET, simulated.")
    fig.subplots_adjust(top=0.8)
    save(fig, "intraday", theme)


def fig_scaling(t, theme, sc):
    rows = sc["rows"]
    fig, ax = plt.subplots(figsize=(7.2, 3.7))
    x = [r["payments"] for r in rows]
    ax.plot(x, [r["simulate_s"] for r in rows], color=t["s"][0], lw=2, marker="o", ms=6, label="Simulate one business day")
    ax.plot(x, [r["replay_s"] for r in rows], color=t["s"][2], lw=2, marker="o", ms=6, label="Replay + verify the ledger")
    ax.set_xscale("log")
    ax.set_yscale("log")
    for r in rows:
        ax.annotate(f"{r['institutions']} banks", (r["payments"], r["simulate_s"]), textcoords="offset points", xytext=(0, 8),
                    fontsize=8, color=t["ink2"], ha="center")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k"))
    ax.set_ylabel("seconds (one CPU core)")
    legend(ax, t, loc="upper left")
    big = rows[-1]
    style(ax, t, "Near-linear scaling to the blueprint's 100-bank, 500k+ payment day",
          f"Largest run: {big['payments']:,} payments, {big['events']:,} events, {big['simulate_s']:.0f}s, every run replay-verified.")
    fig.subplots_adjust(top=0.78)
    save(fig, "scaling", theme)


def fig_auction(t, theme, au):
    fig, ax = plt.subplots(figsize=(7.2, 3.7))
    for k, mech in enumerate(("pay_as_bid", "uniform")):
        rows = sorted((i for i in au["incentives"] if i["mechanism"] == mech and i["stress"] == "baseline"), key=lambda i: i["shade_bp"])
        x = [i["shade_bp"] / 100 for i in rows]
        ax.plot(x, [i["mean_gain_minor"] / 100 for i in rows], color=t["s"][k], lw=2, marker="o", ms=6,
                label={"pay_as_bid": "Pay-as-bid", "uniform": "Uniform price"}[mech])
        ax.fill_between(x, [i["ci95"][0] / 100 for i in rows], [i["ci95"][1] / 100 for i in rows], color=t["s"][k], alpha=0.12)
    ax.axhline(0, color=t["ink2"], lw=0.8)
    ax.set_xlabel("focal lender inflates its ask by (%)")
    ax.set_ylabel("change in its own profit ($)")
    legend(ax, t, loc="best")
    style(ax, t, "Does a lender gain by inflating its ask?", "Paired seeds, top-3 lenders, normal days. Band = 95% CI. Above zero = profitable manipulation.")
    fig.subplots_adjust(top=0.8)
    save(fig, "auction-incentives", theme)


def fig_rl(t, theme, rl):
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
    for k, (key, name) in enumerate((("constrained", "Constrained PPO (Lagrangian)"), ("unconstrained", "Plain PPO"))):
        log = rl["training"][key]
        axes[0].plot([x["iteration"] for x in log], [x["mean_rejections_per_step"] for x in log], color=t["s"][k], lw=2, label=name)
    axes[0].set_xlabel("training iteration")
    axes[0].set_ylabel("safety rejections per step")
    legend(axes[0], t, loc="upper right")
    order = ["none", "rule_rebalancer", "ppo_constrained", "ppo_unconstrained"]
    names = {"none": "No controller", "rule_rebalancer": "Rule-based", "ppo_constrained": "Constrained PPO", "ppo_unconstrained": "Plain PPO"}
    rows = {s["arm"]: s for s in rl["summary"] if s["stress"] == "combined"}
    ys = list(range(len(order)))[::-1]
    for y, a in zip(ys, order):
        s = rows[a]
        m, lo, hi = s["cost_diff_vs_mpc"]
        color = t["s"][1] if lo > 0 else t["s"][0] if hi < 0 else t["neutral"]
        axes[1].barh(y, m, height=0.6, color=color, edgecolor=t["bg"], linewidth=2)
        axes[1].plot([lo, hi], [y, y], color=t["ink"], lw=1.2)
        for xx in (lo, hi):
            axes[1].plot([xx, xx], [y - 0.12, y + 0.12], color=t["ink"], lw=1.2)
        axes[1].text(max(hi, m), y, f"  {'+' if m >= 0 else '−'}${abs(m) / 1e8:.2f}M · rejected {s['safety_rejection_rate'] * 100:.1f}%",
                     va="center", fontsize=8, color=t["ink2"])
    axes[1].axvline(0, color=t["ink2"], lw=1)
    axes[1].set_yticks(ys)
    axes[1].set_yticklabels([names[a] for a in order])
    axes[1].xaxis.set_major_formatter(usd)
    axes[1].set_xlim(min(r["cost_diff_vs_mpc"][1] for r in rows.values() if r["arm"] in order) * 1.6 - 1e7,
                     max(r["cost_diff_vs_mpc"][2] for r in rows.values() if r["arm"] in order) * 2.4)
    axes[1].set_title("Cost vs MPC on the same held-out days, never-seen 'combined' stress", color=t["ink"], fontsize=10, loc="left")
    for ax in axes:
        style(ax, t, "Safe RL vs MPC", "Left: proposals the safety controller had to block, during training. Right: paired cost difference vs MPC (0 = tie), 95% CI. Gray = not significant.")
    fig.subplots_adjust(top=0.78, wspace=0.45)
    save(fig, "safe-rl", theme)


def fig_forecast(t, theme, fc):
    rows = [r for r in fc["results"] if r["horizon"] == "1h"]
    models = ["historical_mean", "ridge", "graph_ridge", "gradient_boosting", "neural_window"]
    models = [m for m in models if any(r["model"] == m for r in rows)]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.7))
    import numpy as np
    xs = np.arange(len(models))
    for k, split in enumerate(("test_in_distribution", "test_out_of_distribution")):
        vals = [next(r["mase"] for r in rows if r["model"] == m and r["split"] == split) for m in models]
        axes[0].bar(xs + (k - 0.5) * 0.38, vals, 0.36, color=t["s"][k], edgecolor=t["bg"], linewidth=2,
                    label={"test_in_distribution": "In-distribution days", "test_out_of_distribution": "Shifted days (OOD)"}[split])
    axes[0].axhline(1, color=t["ink2"], lw=0.8, ls="--")
    axes[0].set_xticks(xs)
    axes[0].set_xticklabels([m.replace("_", "\n") for m in models], fontsize=8)
    axes[0].set_ylabel("MASE (below 1 beats naive)")
    axes[0].set_ylim(0, max(r["mase"] for r in rows if r["model"] in models) * 1.35)
    legend(axes[0], t, loc="upper left", ncol=2)
    ood = [r for r in rows if r["split"] == "test_out_of_distribution" and r["model"] in models]
    ind = [r for r in rows if r["split"] == "test_in_distribution" and r["model"] in models]
    cats = ["In-dist.\nstatic", "OOD\nstatic", "OOD\nadaptive"]
    vals = [np.mean([r["interval_coverage"] for r in ind]), np.mean([r["interval_coverage"] for r in ood]),
            np.mean([r["adaptive_interval_coverage"] for r in ood])]
    axes[1].bar(range(3), vals, 0.55, color=[t["s"][0], t["bad"], t["s"][2]], edgecolor=t["bg"], linewidth=2)
    for i, v in enumerate(vals):
        axes[1].text(i, v - 0.03, f"{v * 100:.0f}%", ha="center", fontsize=10, color="#ffffff", fontweight="bold")
    axes[1].axhline(0.9, color=t["ink2"], lw=0.8, ls="--")
    axes[1].set_xticks(range(3))
    axes[1].set_xticklabels(cats, fontsize=8.5)
    axes[1].set_ylim(0.5, 1.0)
    axes[1].set_ylabel("90% interval coverage")
    for ax in axes:
        style(ax, t, "Forecasting a bank's next-hour outflow, with honest uncertainty",
              "Whole-day splits. Dashed = target. Static conformal intervals break under shift; causal online tracking restores coverage.")
    fig.subplots_adjust(top=0.78, wspace=0.3)
    save(fig, "forecasting", theme)


def fig_netting(t, theme, nt):
    rows = nt["rows"]
    x = [r["obligations"] for r in rows]
    fig, ax = plt.subplots(figsize=(7.2, 3.7))
    for k, (key, name) in enumerate((("mean_gap", "Gridlock heuristic (<3 ms)"), ("lp_round_mean_gap", "LP rounding + local search"),
                                     ("milp_50ms_mean_gap", "MILP with a 50 ms budget"))):
        if key in rows[0]:
            ax.plot(x, [r[key] * 100 for r in rows], color=t["s"][k], lw=2, marker="o", ms=6, label=name)
    ax.set_xlabel("queued obligations")
    ax.set_ylabel("value left unsettled vs optimum (%)")
    legend(ax, t, loc="lower right")
    style(ax, t, "Netting algorithms vs the exact optimum on adversarial gridlock", "Random gridlocked queues, 20 instances per size. Exact MILP (HiGHS) = 0%.")
    fig.subplots_adjust(top=0.8)
    save(fig, "netting-gap", theme)


def fig_replication(t, theme, ext):
    """Heatmap: % change in modeled cost vs the priority queue, every stress x key arm, extended preset (10 fresh seeds)."""
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    arms = [("multilateral_milp", "Exact MILP netting"), ("rule_rebalancer", "Rule-based treasury"), ("mpc", "MPC rebalancing"),
            ("auction_uniform", "Liquidity auction"), ("mpc_plus_auction", "MPC + auction")]
    comp = {(c["stress"], c["arm"]): c for c in ext["comparison"] if c["metric"] == "total_cost_minor"}
    stresses = sorted({c["stress"] for c in ext["comparison"]}, key=lambda s: (s != "baseline", s))
    nice = {s: s.replace("_", " ").replace("rtgs", "RTGS").capitalize().replace("Rtgs", "RTGS") for s in stresses}
    nice["baseline"] = "Normal day"
    vals = np.array([[comp[(s, a)]["rel_diff"] * 100 for a, _ in arms] for s in stresses])
    sig = np.array([[comp[(s, a)]["significant"] for a, _ in arms] for s in stresses])
    # single-hue sequential ramp (light -> dark blue) for size of the saving
    ramp = ["#e8f1fc", "#b7d3f6", "#7cb0ee", "#3987e5", "#1f5fae", "#123f78"] if theme == "light" else \
           ["#20262e", "#1d3a5c", "#1f5590", "#2a78d6", "#5d9ce8", "#a9cbf4"]
    cmap = LinearSegmentedColormap.from_list("save", ramp)
    fig, ax = plt.subplots(figsize=(10.5, 0.42 * len(stresses) + 1.9))
    style(ax, t, "Replication: every stress, 10 seeds, 1,320 runs",
          "Change in modeled daily cost vs the priority queue. " + ("Darker" if theme == "light" else "Brighter") + " = bigger saving. n.s. = 95% paired CI includes zero.")
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    for i in range(len(stresses)):
        for j in range(len(arms)):
            v = vals[i, j]
            frac = min(max(-v / 70, 0), 1)
            color = cmap(frac) if sig[i, j] and v < 0 else (t["bad"] if sig[i, j] else t["bg"])
            ax.add_patch(plt.Rectangle((j + 0.03, i + 0.06), 0.94, 0.88, color=color, lw=0))
            lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in matplotlib.colors.to_rgb(color)]
            lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
            dark_cell = 1.05 / (lum + 0.05) > (lum + 0.05) / 0.05  # white text wins on contrast
            txt = f"{v:+.0f}%" if sig[i, j] else "n.s."
            ax.text(j + 0.5, i + 0.5, txt, ha="center", va="center", fontsize=9.5,
                    color=("#ffffff" if dark_cell else ("#0b0b0b" if sig[i, j] else t["ink2"])),
                    fontweight="bold" if arms[j][0] == "mpc_plus_auction" else "normal")
    ax.set_xlim(0, len(arms))
    ax.set_ylim(len(stresses), 0)
    ax.set_xticks([j + 0.5 for j in range(len(arms))])
    ax.set_xticklabels([n for _, n in arms], fontsize=9.5, color=t["ink"])
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(stresses))])
    ax.set_yticklabels([nice[s] for s in stresses], fontsize=9.5, color=t["ink"])
    fig.subplots_adjust(top=1 - 1.25 / (0.42 * len(stresses) + 1.9))
    save(fig, "replication", theme)


STATUS = {"light": {"pass": "#12855c", "warn": "#b7791f", "fail": "#d03b3a"}, "dark": {"pass": "#3fbf8f", "warn": "#e0a84a", "fail": "#e66767"}}

def _hiring():
    return json.loads((ROOT / "data" / "hiring_map.json").read_text())


def fig_hiring(t, theme):
    H = _hiring()
    rows = H["rows"]
    fig, ax = plt.subplots(figsize=(10.5, 0.36 * len(rows) + 1.7))
    style(ax, t, "What bank AI/ML roles ask for, and where this project shows it",
          f"{H['postings']} postings, five US banks ({', '.join(H['banks'])}). Filled = required, ring = preferred.")
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cols = [("Junior", "junior", 5.25), ("Senior", "senior", 6.05), ("Director+", "director", 6.85)]
    n = len(rows)
    for i, r in enumerate(rows):
        y = n - 1 - i
        if i % 2 == 0:
            ax.add_patch(plt.Rectangle((0, y - 0.5), 10.5, 1, color=t["grid"], alpha=0.35, lw=0))
        ax.text(0.12, y, r["skill"], va="center", ha="left", fontsize=9.3, color=t["ink"])
        for _, key, x in cols:
            v = r[key]
            if v == 2:
                ax.scatter([x], [y], s=95, color=t["s"][0], zorder=3)
            elif v == 1:
                ax.scatter([x], [y], s=85, facecolors="none", edgecolors=t["s"][0], linewidths=1.6, zorder=3)
            else:
                ax.plot([x - 0.07, x + 0.07], [y, y], color=t["neutral"], lw=1.2)
        where = r["where"]
        gap, partial = where.startswith("gap"), where.startswith("partial")
        mark = "✕  " if gap else "◐  " if partial else "✓  "
        ax.text(7.55, y, mark + where.replace("gap: ", "").replace("partial: ", ""), va="center", ha="left", fontsize=9,
                color=STATUS[theme]["fail"] if gap else STATUS[theme]["warn"] if partial else t["ink"], fontweight="bold" if gap or partial else "normal")
    for name, _, x in cols:
        ax.text(x, n - 0.25, name, ha="center", va="bottom", fontsize=9, color=t["ink2"], fontweight="bold")
    ax.text(7.55, n - 0.25, "In ATLAS-Σ", ha="left", va="bottom", fontsize=9, color=t["ink2"], fontweight="bold")
    ax.set_xlim(0, 10.5)
    ax.set_ylim(-0.6, n + 0.2)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.subplots_adjust(top=1 - 1.05 / (0.36 * n + 1.7), left=0.01, right=0.99, bottom=0.02)
    save(fig, "hiring-map", theme)


def fig_detect(t, theme, det):
    types = list(det["typologies"])
    nice = {"amount_spike": "Amount spike", "new_corridor": "New corridor", "off_hours_burst": "Off-hours burst", "structuring": "Just under the limit",
            "fan_in": "Many-to-one (mule)", "duplicate": "Duplicate"}
    series = [("Hand-written rule", "robust_z", t["neutral"], "s"), ("Isolation forest", "iforest", t["s"][1], "D"), ("Supervised model, pattern seen in training", "gbt", t["s"][0], "o")]
    fig, ax = plt.subplots(figsize=(10.5, 4.3))
    d = det["design"]
    style(ax, t, "Catching unusual payments: what each detector finds",
          f"Share of injected incidents caught when reviewing the top {d['alert_rate']:.0%} of payments. {d['test_days']} held-out days, {d['test_anomalies']} anomalies in {d['test_payments']:,} payments.")
    ys = list(range(len(types)))[::-1]
    for y, typ in zip(ys, types):
        vals = [det["detectors"][k]["by_typology"].get(typ, {}).get("recall_at_alert_rate", 0) for _, k, _, _ in series]
        unseen = det["leave_one_typology_out"][typ]["gbt_unseen_recall"]
        ax.plot([min(vals + [unseen]), max(vals + [unseen])], [y, y], color=t["grid"], lw=2, zorder=1)
        for off, ((_, _k, color, marker), v) in zip((0.16, 0.0, -0.16), zip(series, vals)):
            ax.scatter([v], [y + off], s=70, color=color, marker=marker, zorder=3, edgecolors=t["bg"], linewidths=1.2)
        ax.scatter([unseen], [y - 0.32], s=70, facecolors="none", edgecolors=t["s"][0], linewidths=1.8, zorder=3)
    for name, _k, color, marker in series:
        ax.scatter([], [], s=60, color=color, marker=marker, label=name)
    ax.scatter([], [], s=60, facecolors="none", edgecolors=t["s"][0], linewidths=1.8, label="Supervised model, pattern never seen")
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{nice[x]}  (n={det['leave_one_typology_out'][x]['n']})" for x in types], color=t["ink"])
    ax.set_ylim(-0.7, len(types) - 0.4)
    ax.set_xlim(-0.04, 1.04)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_xlabel("incidents caught")
    ax.grid(True, axis="x", color=t["grid"], linewidth=0.6)
    ax.grid(False, axis="y")
    legend(ax, t, loc="upper center", bbox_to_anchor=(0.45, -0.14), ncol=2)
    fig.subplots_adjust(top=0.82, left=0.2, bottom=0.26)
    save(fig, "anomaly-detection", theme)


def fig_mrm(t, theme, inv):
    models = inv["models"]
    sym = {"pass": "✓", "warn": "!", "fail": "✕"}
    width = max(len(m["checks"]) for m in models)
    fig, ax = plt.subplots(figsize=(10.5, 0.5 * len(models) + 1.9))
    c = inv["summary"]
    style(ax, t, "Every model is checked by code, and some fail",
          f"Model inventory in the structure of US guidance SR 26-2. {c['pass']} pass, {c['warn']} warn, {c['fail']} fail. Each mark is one automated validation check.")
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    n = len(models)
    for i, m in enumerate(models):
        y = n - 1 - i
        ax.text(0.1, y, m["name"], va="center", ha="left", fontsize=9.5, color=t["ink"])
        ax.text(5.0, y, m["materiality"]["tier"], va="center", ha="center", fontsize=9, color=t["ink2"])
        for j, chk in enumerate(m["checks"]):
            x = 5.9 + j * 0.52
            col = STATUS[theme][chk["status"]]
            ax.add_patch(plt.Rectangle((x - 0.21, y - 0.3), 0.42, 0.6, color=col, lw=0, alpha=0.95))
            ax.text(x, y, sym[chk["status"]], va="center", ha="center", fontsize=9.5, color="#ffffff" if theme == "light" else "#141413", fontweight="bold")
        ax.text(5.9 + width * 0.52 + 0.1, y, m["status"].upper(), va="center", ha="left", fontsize=9, fontweight="bold", color=STATUS[theme][m["status"]])
    ax.text(5.0, n - 0.35, "Tier", ha="center", va="bottom", fontsize=9, color=t["ink2"], fontweight="bold")
    ax.text(5.7, n - 0.35, "Validation checks", ha="left", va="bottom", fontsize=9, color=t["ink2"], fontweight="bold")
    ax.set_xlim(0, 10.5)
    ax.set_ylim(-0.6, n + 0.1)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.subplots_adjust(top=1 - 1.05 / (0.5 * n + 1.9), left=0.01, right=0.99, bottom=0.02)
    save(fig, "model-risk", theme)


def fig_calibration(t, theme, cal):
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6))
    groups = [("Large-value payment, mean size", cal["targets"]["fedwire_mean_usd"], cal["default"]["large_value_mean_usd"], cal["calibrated"]["large_value_mean_usd"], "Fedwire Funds 2025"),
              ("Instant payment, mean size", cal["targets"]["instant_blended_mean_usd"], cal["default"]["instant_mean_usd"], cal["calibrated"]["instant_mean_usd"], "FedNow + RTP blend")]
    fmt = lambda v: f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.1f}k"
    for ax, (ttl, real, default, calib, src) in zip(axes, groups):
        vals = [real, default, calib]
        names = [f"Published\n({src})", "Twin, default", "Twin, calibrated"]
        ax.bar(range(3), vals, width=0.58, color=[t["neutral"], t["s"][1], t["s"][0]], edgecolor=t["bg"], linewidth=2)
        for i, v in enumerate(vals):
            ax.text(i, v, fmt(v), ha="center", va="bottom", fontsize=9.5, color=t["ink"])
        ax.set_xticks(range(3))
        ax.set_xticklabels(names, color=t["ink2"], fontsize=9)
        ax.set_title(ttl, color=t["ink"], fontsize=10, loc="left")
        ax.set_ylim(0, max(vals) * 1.18)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v) if v else "0"))
        style(ax, t, "Payment sizes checked against published Federal Reserve statistics",
              f"Only the mean is published, so only the mean is fitted. One simulated payment stands for about {cal['scale']['one_twin_payment_represents']} real Fedwire transfers.")
        ax.grid(False, axis="x")
    fig.subplots_adjust(top=0.74, wspace=0.22)
    save(fig, "calibration", theme)


def fig_agent(t, theme, ev):
    agents = ev["agents"]
    cols = [("tools", "Right tools"), ("correct", "Right answer"), ("grounded", "No invented numbers"), ("safe", "Refuses to execute"), ("pass_rate", "Passes all checks")]
    fig, ax = plt.subplots(figsize=(10.5, 0.62 * len(agents) + 1.8))
    style(ax, t, "Agent evaluation: the harness has to be able to fail a bad agent",
          f"{agents[0]['tasks']} tasks. Two deliberately broken agents are included as controls: one misreports numbers, one claims to move money.")
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    n = len(agents)
    for i, a in enumerate(agents):
        y = n - 1 - i
        ax.text(0.1, y, a["agent"], va="center", ha="left", fontsize=9.5, color=t["ink"])
        for j, (key, _) in enumerate(cols):
            v = a[key]
            x = 4.6 + j * 1.2
            status = "pass" if v >= 0.999 else "fail"
            ax.add_patch(plt.Rectangle((x - 0.5, y - 0.32), 1.0, 0.64, color=STATUS[theme][status], alpha=0.95 if status == "fail" else 0.9, lw=0))
            ax.text(x, y, f"{'✓' if status == 'pass' else '✕'} {v:.0%}", va="center", ha="center", fontsize=9.5, fontweight="bold",
                    color="#ffffff" if theme == "light" else "#141413")
    for j, (_, name) in enumerate(cols):
        ax.text(4.6 + j * 1.2, n - 0.42, name.replace(" ", "\n", 1), ha="center", va="bottom", fontsize=8.5, color=t["ink2"], fontweight="bold")
    ax.set_xlim(0, 10.5)
    ax.set_ylim(-0.6, n + 0.45)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.subplots_adjust(top=1 - 1.05 / (0.62 * n + 1.8), left=0.01, right=0.99, bottom=0.02)
    save(fig, "agent-evals", theme)


def fig_deep(t, theme, dp):
    big = max(dp["train_sizes_days"])
    order = ["seasonal_naive", "ridge", "gradient_boosting", "transformer", "gru"]
    nice = {"seasonal_naive": "Seasonal naive", "ridge": "Ridge", "gradient_boosting": "Gradient boosting", "transformer": "Transformer", "gru": "GRU"}
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9), gridspec_kw={"width_ratios": [1.1, 1]})
    ax = axes[0]
    rows = {r["model"]: r for r in dp["results"] if r["train_days"] == big and r["horizon"] == "15m"}
    vals = [rows[m]["mase"] for m in order]
    ax.barh(range(len(order)), vals, height=0.6, color=[t["s"][0] if m in ("gru", "transformer") else t["neutral"] for m in order], edgecolor=t["bg"], linewidth=2)
    for i, v in enumerate(vals):
        ax.text(v, i, f"  {v:.3f}", va="center", fontsize=9, color=t["ink"])
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([nice[m] for m in order])
    ax.set_xlim(0, max(vals) * 1.15)
    ax.set_xlabel("forecast error (MASE, lower is better)")
    ax.set_title(f"15 minutes ahead, {big} training days", color=t["ink"], fontsize=10, loc="left")
    style(ax, t, "Deep-learning forecasters, trained and scored like everything else",
          f"A GRU and a small Transformer in PyTorch against ridge and gradient boosting, on {dp['test_days']} held-out days.")
    ax.grid(False, axis="y")
    ax2 = axes[1]
    for name, color in (("gru", t["s"][0]), ("transformer", t["s"][1])):
        h = dp["training_curves"].get(f"{name}|{big}|15m")
        if h:
            ax2.plot([e["epoch"] for e in h], [e["holdout_loss"] for e in h], color=color, lw=2, label=f"{nice[name]}, held-out")
            ax2.plot([e["epoch"] for e in h], [e["train_loss"] for e in h], color=color, lw=1.2, ls=":", label=f"{nice[name]}, training")
    ax2.set_xlabel("epoch")
    ax2.set_title("Loss during training (early stopping)", color=t["ink"], fontsize=10, loc="left")
    style(ax2, t, "", "")
    legend(ax2, t, loc="center right")
    fig.subplots_adjust(top=0.76, wspace=0.22, bottom=0.15)
    save(fig, "deep-forecasting", theme)


def fig_bcbs(t, theme):
    from atlas.regulatory import intraday_liquidity_report
    from atlas.scenario import generate_scenario
    from atlas.sim import SimulationSettings, run_day
    from atlas.stress import build_scenario
    sc = generate_scenario(seed=11)
    reps = {name: intraday_liquidity_report(run_day(sc, SimulationSettings(policy="priority"), build_scenario(st)).to_dict(include_payments=True))
            for name, st in (("Normal day", "baseline"), ("Combined stress", "combined"))}
    base = {r["institution_id"]: r for r in reps["Normal day"]["institutions"]}
    stress = {r["institution_id"]: r for r in reps["Combined stress"]["institutions"]}
    ids = sorted(base, key=lambda i: stress[i]["A_i_usage_share_of_available"] or 0)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6), gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    for y, i in enumerate(ids):
        a, b = (base[i]["A_i_usage_share_of_available"] or 0) * 100, (stress[i]["A_i_usage_share_of_available"] or 0) * 100
        ax.plot([a, b], [y, y], color=t["grid"], lw=2.2, zorder=1)
        ax.scatter([a], [y], s=52, color=t["neutral"], zorder=3, edgecolors=t["bg"], linewidths=1.2)
        ax.scatter([b], [y], s=52, color=t["s"][1], zorder=3, edgecolors=t["bg"], linewidths=1.2)
    ax.scatter([], [], s=45, color=t["neutral"], label="Normal day")
    ax.scatter([], [], s=45, color=t["s"][1], label="Combined stress")
    ax.set_yticks(range(len(ids)))
    ax.set_yticklabels(ids, fontsize=8.5)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlabel("largest net debit as share of liquidity at start of day")
    ax.set_title("Each bank's peak liquidity usage", color=t["ink"], fontsize=10, loc="left")
    style(ax, t, "Intraday liquidity, the way supervisors monitor it (BCBS 248)",
          "Computed for every bank from the settled payment record of one simulated day: tools A(i) and C(i).")
    ax.grid(False, axis="y")
    legend(ax, t, loc="lower right")
    ax2 = axes[1]
    for (name, rep), color, ls in zip(reps.items(), (t["neutral"], t["s"][1]), ("-", "-")):
        tot = sum(r["A_iii_submitted_minor"] for r in rep["institutions"])
        hours = len(rep["hour_labels"])
        share = [sum((r["C_i_throughput_by_hour"][h] or 0) * r["A_iii_submitted_minor"] for r in rep["institutions"]) / tot * 100 for h in range(hours)]
        ax2.plot(range(1, hours + 1), share, color=color, lw=2, ls=ls, marker="o", ms=4, label=name)
    ax2.set_title("Share of the day's payments sent, by hour", color=t["ink"], fontsize=10, loc="left")
    ax2.set_xlabel("hours after opening")
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax2.set_ylim(0, 102)
    style(ax2, t, "", "")
    fig.subplots_adjust(top=0.8, wspace=0.2, bottom=0.14)
    save(fig, "intraday-liquidity", theme)


def main() -> None:
    import sys

    only = sys.argv[1:]
    want = (lambda n: not only or n in only)
    ext = load("benchmarks/extended.json")
    bench, sc, au, rl, fc, nt = (load("benchmarks/standard.json"), load("scaling.json"), load("auction.json"), load("safe_rl.json"),
                                 load("forecasting.json"), load("netting_optimality.json"))
    for theme, t in THEMES.items():
        plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})
        if bench and want("policy"):
            fig_policy(t, theme, bench)
        if want("intraday"):
            fig_intraday(t, theme)
        if sc and want("scaling"):
            fig_scaling(t, theme, sc)
        if au and want("auction"):
            fig_auction(t, theme, au)
        if rl and want("rl"):
            fig_rl(t, theme, rl)
        if fc and want("forecast"):
            fig_forecast(t, theme, fc)
        if nt and want("netting"):
            fig_netting(t, theme, nt)
        if ext and want("replication"):
            fig_replication(t, theme, ext)
        if want("hiring"):
            fig_hiring(t, theme)
        for key, artifact, fn in (("detect", "anomaly_detection.json", fig_detect), ("mrm", "model_inventory.json", fig_mrm),
                                  ("calibration", "calibration.json", fig_calibration), ("agent", "agent_evals.json", fig_agent),
                                  ("deep", "deep_forecasting.json", fig_deep)):
            data = load(artifact)
            if data and want(key):
                fn(t, theme, data)
        if want("bcbs"):
            fig_bcbs(t, theme)
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
