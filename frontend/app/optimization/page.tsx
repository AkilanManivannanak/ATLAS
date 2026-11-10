"use client";

import { useMemo, useState } from "react";
import { HBarChart } from "@/components/charts";
import { ErrorBox, Header, Panel, SyntheticBadge, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { mins, pct, usd } from "@/lib/format";

type Comp = { stress: string; arm: string; metric: string; n: number; mean: number; reference_mean: number; mean_diff: number; ci95_diff: [number, number]; win_rate: number | null; significant: boolean; direction: string };
type Bench = { name: string; config: { seeds: number[]; reference_arm: string; stresses: string[] }; comparison: Comp[]; rows: { arm: string; stress: string; seed: number; liquidity_usage_minor: number }[]; manifest: Record<string, unknown> };

const METRICS: Record<string, { label: string; fmt: (v: number) => string }> = {
  total_cost_minor: { label: "Total modeled cost", fmt: (v) => usd(v, 2) },
  lv_settlement_rate_value: { label: "Large-value settled (value)", fmt: (v) => pct(v) },
  lv_value_weighted_delay_s: { label: "Value-weighted delay", fmt: (v) => mins(v) },
  instant_rejected: { label: "Instant payments rejected", fmt: (v) => v.toFixed(1) },
  liquidity_usage_minor: { label: "Liquidity used", fmt: (v) => usd(v) },
  peak_credit_minor: { label: "Peak intraday credit", fmt: (v) => usd(v) },
  runtime_s: { label: "Simulation runtime", fmt: (v) => `${v.toFixed(2)}s` },
  timed_deadline_misses: { label: "Timed-obligation deadline misses", fmt: (v) => v.toFixed(1) },
};

const ARM_NOTE: Record<string, string> = {
  fifo: "first-in first-out with bypass",
  fifo_strict: "strict FIFO, head-of-line blocking",
  priority: "priority, then deadline (reference)",
  bilateral: "priority + bilateral offsetting",
  multilateral: "priority + gridlock-resolution heuristic",
  multilateral_milp: "priority + exact 0-1 netting (HiGHS)",
  rule_rebalancer: "greedy cross-rail liquidity moves",
  mpc: "MPC: forecast + LP rebalancing (HiGHS)",
  mpc_queue_milp: "MPC + urgency-weighted queue MILP",
  auction_pay_as_bid: "priority + intraday liquidity auction, pay-as-bid",
  auction_uniform: "priority + intraday liquidity auction, uniform price",
  mpc_plus_auction: "MPC rebalancing + uniform-price auction",
};

type FundingPlan = { allocations_minor: Record<string, number>; objective_minor: number; expected_shortfall_minor: number; cvar_shortfall_cost_minor: number | null; status: string; runtime_ms: number; formulation: string };

export default function Optimization() {
  const list = useAsync(() => api<{ name: string }[]>("/benchmarks"), []);
  const [name, setName] = useState("standard");
  const bench = useAsync(() => api<Bench>(`/benchmarks/${name}`), [name]);
  const [stress, setStress] = useState("baseline");
  const [metric, setMetric] = useState("total_cost_minor");
  const rows = useMemo(() => {
    const b = bench.data;
    if (!b) return [];
    return b.comparison.filter((c) => c.stress === stress && c.metric === metric).sort((a, b2) => a.mean - b2.mean);
  }, [bench.data, stress, metric]);
  const ref = bench.data?.config.reference_arm;

  const [alpha, setAlpha] = useState(0.95);
  const [risk, setRisk] = useState(0.6);
  const [fund, setFund] = useState<{ cvar: FundingPlan; expected_value: FundingPlan } | null>(null);
  const [fundErr, setFundErr] = useState<unknown>(null);
  const solve = async () => {
    setFundErr(null);
    try {
      // Scenarios = the reference arm's realised liquidity need on every benchmarked (seed, stress) day.
      const scen = (bench.data?.rows ?? []).filter((r) => r.arm === bench.data?.config.reference_arm).map((r) => r.liquidity_usage_minor);
      if (!scen.length) throw new Error("benchmark has no reference-arm rows");
      const peak = Math.max(...scen);
      const r = await api<{ cvar: FundingPlan; expected_value: FundingPlan }>("/optimization/funding", {
        method: "POST",
        body: JSON.stringify({
          sources: [
            { name: "own reserves", capacity_minor: Math.round(peak * 0.4), cost_bp: 4 },
            { name: "secured facility", capacity_minor: Math.round(peak * 0.5), cost_bp: 18, collateral_bp: 10000 },
            { name: "unsecured line", capacity_minor: Math.round(peak * 0.3), cost_bp: 55 },
          ],
          scenarios: scen, shortfall_cost_bp: 450, alpha, risk_weight: risk, collateral_budget_minor: Math.round(peak * 0.4),
        }),
      });
      setFund(r);
    } catch (e) {
      setFundErr(e);
    }
  };
  const m = METRICS[metric];
  return (
    <>
      <Header
        title="Settlement Optimization"
        subtitle="NEXUS-PAY benchmark: every arm runs on identical generated days and shocks. Bars are means over seeds; whiskers are the 95% bootstrap CI of the paired difference against the reference arm, re-centred on the arm mean."
        right={<div className="ctl"><SyntheticBadge />
          <label>Benchmark<select value={name} onChange={(e) => setName(e.target.value)}>{(list.data ?? [{ name: "standard" }]).map((b) => <option key={b.name}>{b.name}</option>)}</select></label>
          <label>Stress<select value={stress} onChange={(e) => setStress(e.target.value)}>{bench.data?.config.stresses.map((s) => <option key={s}>{s}</option>)}</select></label>
          <label>Metric<select value={metric} onChange={(e) => setMetric(e.target.value)}>{Object.entries(METRICS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
        </div>}
      />
      <ErrorBox error={list.error || bench.error} />
      <div className="grid g21">
        <Panel title={m.label} tag={bench.data ? `${bench.data.config.seeds.length} paired seeds · reference: ${ref}` : ""}>
          <HBarChart zeroLine={false}
            rows={rows.map((c) => ({
              label: c.arm, value: c.mean, highlight: c.arm === ref || c.significant,
              lo: c.arm === ref ? undefined : c.reference_mean + c.ci95_diff[0] + (c.mean - c.reference_mean - c.mean_diff),
              hi: c.arm === ref ? undefined : c.reference_mean + c.ci95_diff[1] + (c.mean - c.reference_mean - c.mean_diff),
              color: c.arm === ref ? "var(--muted)" : c.significant ? ((c.direction === "lower_is_better") === c.mean_diff < 0 ? "var(--ok)" : "var(--bad)") : "var(--accent)",
            }))}
            format={m.fmt} />
          <div className="legend"><span><i style={{ background: "var(--ok)" }} />significantly better</span><span><i style={{ background: "var(--bad)" }} />significantly worse</span><span><i style={{ background: "var(--accent)" }} />CI includes zero</span></div>
        </Panel>
        <Panel title="Paired comparison table">
          <div style={{ overflowX: "auto" }}>
          <table className="t">
            <thead><tr><th>Arm</th><th>Δ vs ref</th><th>95% CI</th><th>Win</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.arm} title={ARM_NOTE[c.arm]}>
                  <td>{c.arm}</td>
                  <td className={c.significant ? ((c.direction === "lower_is_better") === c.mean_diff < 0 ? "ok" : "bad") : "muted"}>{c.arm === ref ? "ref" : metric === "lv_settlement_rate_value" ? `${(c.mean_diff * 100).toFixed(2)}pp` : m.fmt(c.mean_diff)}</td>
                  <td className="dim">{c.arm === ref ? "" : metric === "lv_settlement_rate_value" ? `[${(c.ci95_diff[0] * 100).toFixed(2)}, ${(c.ci95_diff[1] * 100).toFixed(2)}]` : `[${m.fmt(c.ci95_diff[0])}, ${m.fmt(c.ci95_diff[1])}]`}</td>
                  <td>{c.win_rate === null ? "—" : `${Math.round(c.win_rate * 100)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <p className="note">Hover an arm for its definition. Win = share of seeds where the arm beat the reference.</p>
        </Panel>
      </div>
      <div className="grid g2" style={{ marginTop: 14 }}>
        <Panel title="Stochastic funding pre-positioning" tag="CVaR LP (Rockafellar–Uryasev) · HiGHS">
          <div className="ctl">
            <label>CVaR α<input type="number" step={0.01} min={0.5} max={0.99} value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} style={{ width: 90, minWidth: 0 }} /></label>
            <label>Risk weight λ<input type="number" step={0.1} min={0} max={1} value={risk} onChange={(e) => setRisk(Number(e.target.value))} style={{ width: 90, minWidth: 0 }} /></label>
            <button className="btn" onClick={solve}>Solve</button>
          </div>
          <ErrorBox error={fundErr} />
          {fund && (
            <table className="t" style={{ marginTop: 12 }}>
              <thead><tr><th>Source</th><th>Expected-value plan</th><th>CVaR plan</th></tr></thead>
              <tbody>
                {Object.keys(fund.cvar.allocations_minor).map((k) => (
                  <tr key={k}><td>{k}</td><td>{usd(fund.expected_value.allocations_minor[k])}</td><td>{usd(fund.cvar.allocations_minor[k])}</td></tr>
                ))}
                <tr><td className="muted">Expected shortfall</td><td>{usd(fund.expected_value.expected_shortfall_minor)}</td><td>{usd(fund.cvar.expected_shortfall_minor)}</td></tr>
                <tr><td className="muted">Tail shortfall cost (CVaR)</td><td>—</td><td>{usd(fund.cvar.cvar_shortfall_cost_minor)}</td></tr>
                <tr><td className="muted">Solver status · time</td><td>{fund.expected_value.status} · {fund.expected_value.runtime_ms.toFixed(1)}ms</td><td>{fund.cvar.status} · {fund.cvar.runtime_ms.toFixed(1)}ms</td></tr>
              </tbody>
            </table>
          )}
          <p className="note">Scenarios are the reference arm&apos;s realised system liquidity need on each benchmarked seed and stress day; source capacities are set as shares of the worst day. Hard constraints (capacities, collateral budget) are never relaxed; an infeasible problem returns HTTP 409 with the solver status.</p>
        </Panel>
        <Panel title="Arm definitions">
          <dl className="kv">{Object.entries(ARM_NOTE).map(([k, v]) => [<dt key={k} className="mono">{k}</dt>, <dd key={k + "v"} style={{ textAlign: "left", fontFamily: "var(--sans)" }}>{v}</dd>])}</dl>
        </Panel>
      </div>
    </>
  );
}
