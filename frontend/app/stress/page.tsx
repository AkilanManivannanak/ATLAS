"use client";

import { useState } from "react";
import { HBarChart, LineChart } from "@/components/charts";
import { ErrorBox, Header, Panel, SyntheticBadge, useAsync } from "@/components/ui";
import { api, RunDetail, RunSummary } from "@/lib/api";
import { mins, num, pct, usd } from "@/lib/format";

type Meta = { policies: string[]; strategies: string[]; controllers: string[]; stress_scenarios: Record<string, { name: string; description: string; shocks: Record<string, unknown>[] }> };

export default function StressLab() {
  const meta = useAsync(() => api<Meta>("/meta"), []);
  const [form, setForm] = useState({ stress: "combined", policy: "multilateral", strategy: "early", controller: "none", seed: 7, opening_liquidity_bp: 600, credit_limit_bp: 300 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [pair, setPair] = useState<{ base: RunDetail; stressed: RunDetail } | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const common = { seed: form.seed, policy: form.policy, strategy: form.strategy, controller: form.controller, opening_liquidity_bp: form.opening_liquidity_bp, credit_limit_bp: form.credit_limit_bp };
      const base = await api<RunSummary>("/simulations", { method: "POST", body: JSON.stringify({ ...common, stress: "baseline", label: `Paired baseline · seed ${form.seed}` }) });
      const stressed = await api<RunSummary>("/simulations", { method: "POST", body: JSON.stringify({ ...common, stress: form.stress, label: `Stress lab · ${form.stress} · seed ${form.seed}` }) });
      const [b, s] = await Promise.all([api<RunDetail>(`/simulations/${encodeURIComponent(base.id)}`), api<RunDetail>(`/simulations/${encodeURIComponent(stressed.id)}`)]);
      setPair({ base: b, stressed: s });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const set = (k: string, v: string | number) => setForm((f) => ({ ...f, [k]: v }));
  const sc = meta.data?.stress_scenarios[form.stress];
  const series = (r: RunDetail | undefined, k: string) => (r?.timeseries ?? []).map((row) => ({ x: new Date(String(row.t)), y: Number(row[k] ?? 0) / 100 }));
  const delta = (f: (r: RunDetail) => number) => (pair ? f(pair.stressed) - f(pair.base) : 0);
  const instRows = pair
    ? pair.stressed.per_institution.map((i) => {
        const b = pair.base.per_institution.find((x) => x.institution_id === i.institution_id)!;
        return { label: i.institution_id, value: (i.settlement_rate_value - b.settlement_rate_value) * 100 };
      }).sort((a, b) => a.value - b.value).slice(0, 10).map((r) => ({ ...r, color: r.value < 0 ? "var(--bad)" : "var(--ok)" }))
    : [];
  return (
    <>
      <Header
        title="Stress & Agent Lab"
        subtitle="Inject a shock and compare against a paired baseline: same seed, same payment schedule, same agents. Every difference is attributable to the shock."
        right={<SyntheticBadge />}
      />
      <ErrorBox error={meta.error || err} />
      <Panel title="Experiment">
        <div className="ctl">
          <label>Stress scenario
            <select value={form.stress} onChange={(e) => set("stress", e.target.value)}>
              {Object.keys(meta.data?.stress_scenarios ?? {}).filter((k) => k !== "baseline").map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
          <label>Settlement policy
            <select value={form.policy} onChange={(e) => set("policy", e.target.value)}>{meta.data?.policies.map((p) => <option key={p}>{p}</option>)}</select>
          </label>
          <label>Bank strategy
            <select value={form.strategy} onChange={(e) => set("strategy", e.target.value)}>{meta.data?.strategies.map((p) => <option key={p}>{p}</option>)}</select>
          </label>
          <label>Controller
            <select value={form.controller} onChange={(e) => set("controller", e.target.value)}>{meta.data?.controllers.map((p) => <option key={p}>{p}</option>)}</select>
          </label>
          <label>Seed<input type="number" value={form.seed} onChange={(e) => set("seed", Number(e.target.value))} style={{ width: 90, minWidth: 0 }} /></label>
          <label>Opening liquidity (bp)<input type="number" value={form.opening_liquidity_bp} onChange={(e) => set("opening_liquidity_bp", Number(e.target.value))} style={{ width: 110, minWidth: 0 }} /></label>
          <label>Credit line (bp)<input type="number" value={form.credit_limit_bp} onChange={(e) => set("credit_limit_bp", Number(e.target.value))} style={{ width: 100, minWidth: 0 }} /></label>
          <button className="btn" onClick={run} disabled={busy}>{busy ? "Simulating paired days…" : "Run paired experiment"}</button>
        </div>
        {sc && <p className="note" style={{ marginBottom: 0 }}><b className="muted">{sc.name}:</b> {sc.description} <span className="mono dim">{JSON.stringify(sc.shocks)}</span></p>}
      </Panel>
      {pair && (
        <>
          <div className="grid g4" style={{ margin: "14px 0" }}>
            {[
              { l: "Δ LV value settled", v: `${(delta((r) => r.metrics.large_value.settlement_rate_value) * 100).toFixed(2)}pp`, bad: delta((r) => r.metrics.large_value.settlement_rate_value) < 0,
                s: `${pct(pair.base.metrics.large_value.settlement_rate_value)} → ${pct(pair.stressed.metrics.large_value.settlement_rate_value)}` },
              { l: "Δ value-weighted delay", v: mins(delta((r) => r.metrics.large_value.value_weighted_delay_s)), bad: delta((r) => r.metrics.large_value.value_weighted_delay_s) > 0,
                s: `${mins(pair.base.metrics.large_value.value_weighted_delay_s)} → ${mins(pair.stressed.metrics.large_value.value_weighted_delay_s)}` },
              { l: "Δ unsettled at close", v: usd(delta((r) => r.metrics.large_value.value_minor - r.metrics.large_value.settled_value_minor)), bad: delta((r) => r.metrics.large_value.value_minor - r.metrics.large_value.settled_value_minor) > 0,
                s: "value left in queues / held" },
              { l: "Δ total modeled cost", v: usd(delta((r) => r.metrics.costs_minor.total)), bad: delta((r) => r.metrics.costs_minor.total) > 0,
                s: `${usd(pair.base.metrics.costs_minor.total)} → ${usd(pair.stressed.metrics.costs_minor.total)}` },
            ].map((x) => (
              <Panel key={x.l}><div className="stat"><div className="l">{x.l}</div><div className={`v ${x.bad ? "bad" : "ok"}`}>{x.v}</div><div className="s">{x.s}</div></div></Panel>
            ))}
          </div>
          <div className="grid g2">
            <Panel title="RTGS queue: baseline vs stressed">
              <LineChart series={[
                { key: "b", label: "Baseline", color: "var(--muted)", values: series(pair.base, "rtgs_queued_value_minor"), dashed: true },
                { key: "s", label: `Stressed (${typeof pair.stressed.stress === "string" ? pair.stressed.stress : (pair.stressed.stress as { name: string }).name})`, color: "var(--bad)", values: series(pair.stressed, "rtgs_queued_value_minor") },
              ]} yFormat={(v) => usd(v * 100, 1)} />
            </Panel>
            <Panel title="Held by senders: baseline vs stressed">
              <LineChart series={[
                { key: "b", label: "Baseline", color: "var(--muted)", values: series(pair.base, "held_value_minor"), dashed: true },
                { key: "s", label: "Stressed", color: "var(--warn)", values: series(pair.stressed, "held_value_minor") },
              ]} yFormat={(v) => usd(v * 100, 1)} />
            </Panel>
            <Panel title="Most affected institutions" tag="Δ settled share of own sent value (pp)">
              <HBarChart rows={instRows} format={(v) => `${v.toFixed(1)}pp`} />
            </Panel>
            <Panel title="Run provenance">
              <dl className="kv">
                <dt>Scenario fingerprint</dt><dd>{pair.base.scenario.fingerprint.slice(0, 16)}… (both)</dd>
                <dt>Baseline state hash</dt><dd>{pair.base.final_state_hash.slice(0, 16)}…</dd>
                <dt>Stressed state hash</dt><dd>{pair.stressed.final_state_hash.slice(0, 16)}…</dd>
                <dt>Events (base / stressed)</dt><dd>{num(pair.base.metrics.events)} / {num(pair.stressed.metrics.events)}</dd>
                <dt>Rejected payments (base / stressed)</dt><dd>{num(pair.base.metrics.counters.rejected)} / {num(pair.stressed.metrics.counters.rejected)}</dd>
              </dl>
              <p className="note">Both runs are stored in the hash-chained event store and can be replayed from the Audit screen.</p>
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
