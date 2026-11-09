"use client";

import { LineChart } from "@/components/charts";
import { ErrorBox, Header, Panel, RunPicker, SyntheticBadge, useRun } from "@/components/ui";
import { mins, num, pct, RAIL_COLOR, RAIL_LABEL, usd } from "@/lib/format";

const RAILS = ["rtgs", "lsm", "fednow", "rtp"] as const;
const DESC: Record<string, string> = {
  rtgs: "Gross settlement, immediate finality, priority queue, optional collateralised intraday credit.",
  lsm: "Queued obligations settled in periodic partial multilateral netting cycles (cash only).",
  fednow: "Continuous instant settlement with configurable accounting-day rollover; rejects if prefunded cash is short.",
  rtp: "Independent private instant rail with its own participant set and limits.",
};

export default function Rails() {
  const { runs, runId, select, detail } = useRun();
  const d = detail.data;
  const ts = d?.timeseries ?? [];
  const at = (k: string) => ts.map((r) => ({ x: new Date(String(r.t)), y: Number(r[k] ?? 0) / 100 }));
  const outages = (d?.stress as unknown as { shocks?: { kind: string; rail?: string; start_min?: number; end_min?: number }[] })?.shocks ?? [];
  return (
    <>
      <Header
        title="Payment Infrastructure"
        subtitle="Four independent rail archetypes, each with its own operating rules, queue and liquidity pool. Liquidity is not transferable between rails unless an own-account transfer is executed."
        right={<div className="ctl"><SyntheticBadge /><RunPicker runs={runs.data} runId={runId} onSelect={select} /></div>}
      />
      <ErrorBox error={runs.error || detail.error} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        {RAILS.map((r) => {
          const m = d?.metrics.by_rail[r];
          const down = outages.filter((s) => s.kind === "rail_outage" && s.rail === r);
          const rate = m?.settlement_rate_value ?? 0;
          return (
            <Panel key={r} title={RAIL_LABEL[r]} tag={<span className={`pill ${down.length ? "bad" : "ok"}`}><span className="dot" />{down.length ? `outage ${down[0].start_min}–${down[0].end_min}m` : "operational"}</span>}>
              <div className="stat">
                <div className={`v ${rate < 0.9 ? "bad" : rate < 0.98 ? "warn" : "ok"}`} style={{ color: rate >= 0.98 ? undefined : undefined }}>{pct(m?.settlement_rate_value)}</div>
                <div className="s">value settled · {num(m?.settled_count)}/{num(m?.count)} payments</div>
              </div>
              <dl className="kv" style={{ marginTop: 10 }}>
                <dt>Gross value</dt><dd>{usd(m?.value_minor)}</dd>
                <dt>Value-weighted delay</dt><dd>{mins(m?.value_weighted_delay_s)}</dd>
                <dt>p95 delay</dt><dd>{mins(m?.p95_delay_s)}</dd>
                <dt>Deadline misses</dt><dd className={m && m.deadline_miss_count ? "warn" : ""}>{num(m?.deadline_miss_count)} · {usd(m?.deadline_miss_value_minor)}</dd>
              </dl>
              <p className="note" style={{ marginBottom: 0 }}>{DESC[r]}</p>
            </Panel>
          );
        })}
      </div>
      <div className="grid g2">
        <Panel title="Central-queue value" tag="unsettled, released instructions">
          <LineChart area series={[
            { key: "rq", label: "RTGS queue", color: RAIL_COLOR.rtgs, values: at("rtgs_queued_value_minor") },
            { key: "lq", label: "LSM queue", color: RAIL_COLOR.lsm, values: at("lsm_queued_value_minor") },
            { key: "held", label: "Held by senders", color: "var(--muted)", values: at("held_value_minor"), dashed: true },
          ]} yFormat={(v) => usd(v * 100, 1)} />
        </Panel>
        <Panel title="Settlement-account cash by rail">
          <LineChart series={RAILS.map((r) => ({ key: r, label: RAIL_LABEL[r], color: RAIL_COLOR[r], values: at(`${r}_cash_minor`) }))} yFormat={(v) => usd(v * 100, 1)} />
        </Panel>
        <Panel title="Cumulative settled value">
          <LineChart area series={[{ key: "s", label: "Settled (all rails)", color: "var(--ok)", values: at("settled_value_minor") }]} yFormat={(v) => usd(v * 100, 1)} />
        </Panel>
        <Panel title="Intraday credit in use" tag="RTGS daylight credit">
          <LineChart area series={[{ key: "c", label: "Credit used", color: "var(--warn)", values: at("rtgs_credit_used_minor") }]} yFormat={(v) => usd(v * 100, 1)} />
        </Panel>
      </div>
    </>
  );
}
