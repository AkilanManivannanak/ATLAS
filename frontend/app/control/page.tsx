"use client";

import { useMemo, useState } from "react";
import { HBarChart, LineChart } from "@/components/charts";
import { ErrorBox, Header, Panel, RunPicker, Stat, SyntheticBadge, useRun } from "@/components/ui";
import { api } from "@/lib/api";
import { hhmm, pct, RAIL_COLOR, usd } from "@/lib/format";

type Diff = { base_id: string; counterfactual_id: string; changed_assumptions: Record<string, unknown>; same_scenario_fingerprint: boolean; diff: Record<string, { base: number; counterfactual: number; delta: number }> };

export default function Control() {
  const { runs, runId, select, detail } = useRun();
  const d = detail.data;
  const log = d?.controller_log ?? [];
  const [cf, setCf] = useState<Diff | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const counterfactual = async (controller: string) => {
    if (!runId) return;
    setBusy(true);
    setErr(null);
    try {
      setCf(await api<Diff>(`/simulations/${encodeURIComponent(runId)}/counterfactual`, { method: "POST", body: JSON.stringify({ controller }) }));
      runs.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const flows = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of log) if (e.kind === "transfer" && e.approved) m.set(`${e.from_rail} → ${e.to_rail}`, (m.get(`${e.from_rail} → ${e.to_rail}`) ?? 0) + e.amount_minor);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: RAIL_COLOR[label.split(" → ")[1]] }));
  }, [log]);
  const reasons = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of log) if (!e.approved) m.set(e.reason, (m.get(e.reason) ?? 0) + 1);
    return [...m.entries()];
  }, [log]);
  const proposals = d?.metrics.counters.controller_actions ?? 0;
  const rejected = d?.metrics.counters.controller_rejected ?? 0;
  const ts = d?.timeseries ?? [];
  const at = (k: string) => ts.map((r) => ({ x: new Date(String(r.t)), y: Number(r[k] ?? 0) / 100 }));
  return (
    <>
      <Header
        title="Adaptive Control"
        subtitle="The MPC controller forecasts each bank's per-rail liquidity need, solves a rebalancing LP and an urgency-weighted netting MILP, and proposes actions. Every proposal passes the safety controller before it can touch the ledger; rejections are logged, never repaired."
        right={<div className="ctl"><SyntheticBadge /><RunPicker runs={runs.data} runId={runId} onSelect={select} /></div>}
      />
      <ErrorBox error={runs.error || detail.error || err} />
      {!d?.controller && <Panel><div className="note">This run has no controller. Pick an "Adaptive · MPC" run, or launch a paired counterfactual below to add one to this exact day.</div></Panel>}
      <div className="grid g4" style={{ margin: "14px 0" }}>
        <Stat label="Controller" value={<span style={{ fontSize: 16 }}>{d?.controller ?? "none"}</span>} sub={`policy: ${d?.policy ?? "—"}`} />
        <Stat label="Proposals" value={proposals.toLocaleString()} sub={`${(proposals - rejected).toLocaleString()} approved · ${rejected} rejected by safety`} tone={rejected ? "warn" : "ok"} />
        <Stat label="Cross-rail liquidity moved" value={usd(d?.metrics.counters.transfers_minor)} sub="own-account transfers, conserved in ledger" />
        <Stat label="LV settled / instant rejected" value={pct(d?.metrics.large_value.settlement_rate_value)} sub={`${d?.metrics.counters.instant_rejected ?? "—"} instant rejections`} />
      </div>
      <div className="grid g2">
        <Panel title="Liquidity moved by corridor">
          {flows.length ? <HBarChart rows={flows} format={(v) => usd(v)} /> : <div className="note">No approved transfers in this run.</div>}
        </Panel>
        <Panel title="System cash by rail" tag="changes only via controller transfers or shocks">
          <LineChart series={(["rtgs", "lsm", "fednow", "rtp"] as const).map((r) => ({ key: r, label: r, color: RAIL_COLOR[r], values: at(`${r}_cash_minor`) }))} yFormat={(v) => usd(v * 100, 1)} />
        </Panel>
        <Panel title="Paired counterfactual on this exact day">
          <div className="ctl">
            <button className="btn" disabled={busy || !runId} onClick={() => counterfactual("mpc")}>Re-run with MPC</button>
            <button className="btn ghost" disabled={busy || !runId} onClick={() => counterfactual("rule")}>Re-run with greedy rebalancer</button>
            <button className="btn ghost" disabled={busy || !runId} onClick={() => counterfactual("none")}>Re-run without controller</button>
          </div>
          {busy && <div className="skeleton">simulating counterfactual…</div>}
          {cf && (
            <table className="t" style={{ marginTop: 12 }}>
              <thead><tr><th>Metric</th><th>This run</th><th>Counterfactual</th><th>Δ</th></tr></thead>
              <tbody>
                {Object.entries(cf.diff).map(([k, v]) => {
                  const rate = k.includes("rate");
                  const money = k.endsWith("_minor");
                  const f = (x: number) => (rate ? pct(x) : money ? usd(x) : k.endsWith("_s") ? `${(x / 60).toFixed(1)}m` : x.toFixed(0));
                  const good = rate ? v.delta > 0 : v.delta < 0;
                  return <tr key={k}><td>{k}</td><td>{f(v.base)}</td><td>{f(v.counterfactual)}</td><td className={v.delta === 0 ? "dim" : good ? "ok" : "bad"}>{rate ? `${(v.delta * 100).toFixed(2)}pp` : f(v.delta)}</td></tr>;
                })}
              </tbody>
            </table>
          )}
          {cf && <p className="note">Same scenario fingerprint: <span className={cf.same_scenario_fingerprint ? "ok" : "bad"}>{String(cf.same_scenario_fingerprint)}</span>. Changed: <span className="mono">{JSON.stringify(cf.changed_assumptions)}</span>.</p>}
        </Panel>
        <Panel title="Safety rejections" tag="atlas-safety-v1">
          {reasons.length ? (
            <table className="t"><tbody>{reasons.map(([r, n]) => <tr key={r}><td style={{ whiteSpace: "normal" }}>{r}</td><td style={{ textAlign: "right" }}>{n}</td></tr>)}</tbody></table>
          ) : <div className="note">No proposals were rejected in this run.</div>}
        </Panel>
      </div>
      <Panel title="Decision log" tag="latest 500 proposals" style={{ marginTop: 14 }}>
        <div className="scroll">
          <table className="t">
            <thead><tr><th>Time</th><th>Kind</th><th>Verdict</th><th>Institution</th><th>Corridor</th><th>Amount</th><th>Rationale / reason</th></tr></thead>
            <tbody>
              {[...log].reverse().slice(0, 300).map((e, i) => (
                <tr key={i}>
                  <td>{hhmm(e.at)}</td><td>{e.kind}</td>
                  <td><span className={`pill ${e.approved ? "ok" : "bad"}`}>{e.approved ? "approved" : "rejected"}</span></td>
                  <td>{e.institution || "system"}</td>
                  <td>{e.kind === "transfer" ? `${e.from_rail} → ${e.to_rail}` : `${e.payment_count} payments`}</td>
                  <td>{e.amount_minor ? usd(e.amount_minor) : "—"}</td>
                  <td className="muted" style={{ whiteSpace: "normal", maxWidth: 420 }}>{e.approved ? e.rationale : e.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
