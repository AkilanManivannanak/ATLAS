"use client";

import { useState } from "react";
import { HBarChart, Sparkbar } from "@/components/charts";
import { ErrorBox, Header, Panel, RunPicker, Stat, SyntheticBadge, useAsync, useRun } from "@/components/ui";
import { api } from "@/lib/api";
import { mins, pct, RAIL_COLOR, usd } from "@/lib/format";

type InstDetail = { exposures: Record<string, { sent_minor: number; received_minor: number; unsettled_minor: number }>; payment_count: number };

export default function Treasury() {
  const { runs, runId, select, detail } = useRun();
  const [sel, setSel] = useState<string | null>(null);
  const d = detail.data;
  const L = d?.metrics.liquidity;
  const C = d?.metrics.costs_minor;
  const insts = [...(d?.per_institution ?? [])].sort((a, b) => b.sent_value_minor - a.sent_value_minor);
  const maxLU = Math.max(1, ...insts.map((i) => i.liquidity_usage_minor));
  const current = sel ?? insts[0]?.institution_id ?? null;
  const exp = useAsync<InstDetail | null>(
    () => (runId && current ? api<InstDetail>(`/simulations/${encodeURIComponent(runId)}/institutions/${current}`) : Promise.resolve(null)),
    [runId, current],
  );
  const me = insts.find((i) => i.institution_id === current);
  const costRows = C
    ? Object.entries(C).filter(([k]) => k !== "total").map(([k, v]) => ({ label: k.replace(/_/g, " "), value: v, color: k === "unsettled_penalty" ? "var(--bad)" : "var(--accent)" }))
    : [];
  return (
    <>
      <Header
        title="Treasury Center"
        subtitle="System and institution liquidity. Liquidity usage follows the Leinonen–Soramäki definition: the deepest cumulative net payment outflow each account funded during the day."
        right={<div className="ctl"><SyntheticBadge /><RunPicker runs={runs.data} runId={runId} onSelect={select} /></div>}
      />
      <ErrorBox error={runs.error || detail.error} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <Stat label="Opening large-value liquidity" value={usd(L?.opening_large_value_liquidity_minor as number)} sub="cash on RTGS + LSM accounts" />
        <Stat label="Liquidity used" value={usd(L?.system_liquidity_usage_minor as number)}
          sub={`bounds: lower ${usd(L?.lower_bound_minor as number)} · upper ${usd(L?.upper_bound_minor as number)}`} />
        <Stat label="Peak intraday credit" value={usd(L?.peak_intraday_credit_minor as number)} tone={(L?.peak_intraday_credit_minor as number) > 0 ? "warn" : "ok"}
          sub={`turnover ${(L?.liquidity_turnover as number)?.toFixed?.(1) ?? "—"}× settled value per unit liquidity`} />
        <Stat label="Total modeled cost" value={usd(C?.total)} sub={L?.liquidity_efficiency == null ? "bounds efficiency n/a (not all settled)" : `bounds efficiency ${pct(L?.liquidity_efficiency as number, 1)}`} />
      </div>
      <div className="grid g21">
        <Panel title="Institutions" tag="click a row for counterparty exposures">
          <div className="scroll">
            <table className="t">
              <thead>
                <tr><th>Institution</th><th>Tier</th><th>Strategy</th><th>Sent</th><th>Settled</th><th>Delay</th><th>Liquidity used</th><th>Peak credit</th><th>RTGS close</th></tr>
              </thead>
              <tbody>
                {insts.map((i) => (
                  <tr key={i.institution_id} className={i.institution_id === current ? "sel" : ""} onClick={() => setSel(i.institution_id)} style={{ cursor: "pointer" }}>
                    <td>{i.institution_id}</td>
                    <td className={i.tier === "core" ? "" : "muted"}>{i.tier}</td>
                    <td className="muted">{i.strategy}</td>
                    <td>{usd(i.sent_value_minor)}</td>
                    <td className={i.settlement_rate_value < 0.9 ? "bad" : i.settlement_rate_value < 0.98 ? "warn" : "ok"}>{pct(i.settlement_rate_value, 1)}</td>
                    <td>{mins(i.value_weighted_delay_s)}</td>
                    <td><div style={{ display: "flex", gap: 8, alignItems: "center" }}><Sparkbar value={i.liquidity_usage_minor} max={maxLU} />{usd(i.liquidity_usage_minor)}</div></td>
                    <td className={i.peak_credit_minor ? "warn" : "dim"}>{usd(i.peak_credit_minor)}</td>
                    <td>{usd(i.closing_minor.rtgs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <div className="grid" style={{ alignContent: "start" }}>
          <Panel title="Cost decomposition" tag="minor units → USD">
            <HBarChart rows={costRows} format={(v) => usd(v, 1)} />
          </Panel>
          <Panel title={`${current ?? ""} · balances by rail`}>
            {me && (
              <table className="t">
                <thead><tr><th>Rail</th><th>Open</th><th>Close</th><th>Δ</th></tr></thead>
                <tbody>
                  {Object.keys(me.opening_minor).map((r) => {
                    const delta = me.closing_minor[r] - me.opening_minor[r];
                    return (
                      <tr key={r}>
                        <td style={{ color: RAIL_COLOR[r] }}>{r}</td><td>{usd(me.opening_minor[r])}</td><td>{usd(me.closing_minor[r])}</td>
                        <td className={delta < 0 ? "bad" : "ok"}>{delta >= 0 ? "+" : ""}{usd(delta)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Panel>
          <Panel title="Top counterparty exposures" tag={exp.data ? `${exp.data.payment_count} payments` : ""}>
            <table className="t">
              <thead><tr><th>Counterparty</th><th>Sent</th><th>Received</th><th>Unsettled</th></tr></thead>
              <tbody>
                {Object.entries(exp.data?.exposures ?? {}).sort((a, b) => b[1].sent_minor + b[1].received_minor - a[1].sent_minor - a[1].received_minor).slice(0, 8).map(([cp, e]) => (
                  <tr key={cp}><td>{cp}</td><td>{usd(e.sent_minor)}</td><td>{usd(e.received_minor)}</td><td className={e.unsettled_minor ? "warn" : "dim"}>{usd(e.unsettled_minor)}</td></tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      </div>
    </>
  );
}
