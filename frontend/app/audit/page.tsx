"use client";

import { useState } from "react";
import { ErrorBox, Header, Panel, RunPicker, Stat, SyntheticBadge, useAsync, useRun } from "@/components/ui";
import { api } from "@/lib/api";
import { hhmm, num, short, usd } from "@/lib/format";

type Ev = { seq: number; type: string; at: string; aggregate_id: string; aggregate_type: string; payload: Record<string, unknown>; record_hash: string; prev_hash: string };
type Replay = { chain_valid: boolean; chain_events: number; chain_head: string; replayed_state_hash: string; live_state_hash: string; replay_matches: boolean; ledger_events_applied: number;
  conservation: { opening_total_minor: number; external_net_flow_minor: number; closing_total_minor: number }; runtime_ms: number };

const TYPES = ["", "PaymentSettled", "LiquiditySavingCycleSettled", "PaymentReleased", "PaymentRejected", "PaymentExpired", "LiquidityAdjusted", "CreditLimitChanged",
  "FundingDrawn", "FundingRepaid", "IntradayCreditRepaid", "RailOutageStarted", "RailOutageEnded", "StressSignalRaised", "ControlActionRejected", "BusinessDayClosed"];

export default function Audit() {
  const { runs, runId, select, detail } = useRun();
  const [type, setType] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const size = 100;
  const ev = useAsync<{ total: number; items: Ev[] } | null>(
    () => (runId ? api(`/simulations/${encodeURIComponent(runId)}/events?offset=${page * size}&limit=${size}${type ? `&event_type=${type}` : ""}`) : Promise.resolve(null)),
    [runId, type, page],
  );
  const [rep, setRep] = useState<Replay | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const verify = async () => {
    if (!runId) return;
    setBusy(true);
    setErr(null);
    try {
      setRep(await api<Replay>(`/simulations/${encodeURIComponent(runId)}/replay`, { method: "POST" }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const d = detail.data;
  return (
    <>
      <Header
        title="Audit & Governance"
        subtitle="Append-only, SHA-256 hash-chained financial event log. Replay re-folds every stored event through the strict ledger, which checks each event's before-balances, and compares the result with the live state hash."
        right={<div className="ctl"><SyntheticBadge /><RunPicker runs={runs.data} runId={runId} onSelect={(id) => { select(id); setPage(0); setRep(null); }} /></div>}
      />
      <ErrorBox error={runs.error || detail.error || ev.error || err} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <Stat label="Stored events" value={num(ev.data?.total)} sub={type || "all types"} />
        <Stat label="Live ledger state hash" value={<span style={{ fontSize: 15 }}>{short(d?.final_state_hash ?? "", 16)}</span>} sub={`simulator ${String(d?.manifest?.simulator_version ?? "")}`} />
        <Stat label="Scenario fingerprint" value={<span style={{ fontSize: 15 }}>{short(d?.scenario.fingerprint ?? "", 16)}</span>} sub={`seed ${String(d?.manifest?.seed ?? "—")} · ${String(d?.manifest?.generator_version ?? "")}`} />
        <Panel>
          <div className="stat">
            <div className="l">Deterministic replay</div>
            {rep ? (
              <div className={`v ${rep.chain_valid && rep.replay_matches ? "ok" : "bad"}`} style={{ fontSize: 18 }}>{rep.chain_valid && rep.replay_matches ? "VERIFIED" : "MISMATCH"}</div>
            ) : (
              <button className="btn" onClick={verify} disabled={busy || !runId} style={{ marginTop: 4 }}>{busy ? "Replaying…" : "Verify chain + replay"}</button>
            )}
            {rep && <div className="s">{num(rep.chain_events)} events · {rep.runtime_ms.toFixed(0)}ms</div>}
          </div>
        </Panel>
      </div>
      {rep && (
        <Panel title="Replay report" style={{ marginBottom: 14 }}>
          <dl className="kv">
            <dt>Hash chain</dt><dd className={rep.chain_valid ? "ok" : "bad"}>{rep.chain_valid ? "intact" : "broken"} · head {short(rep.chain_head, 20)}</dd>
            <dt>Replayed state hash</dt><dd>{rep.replayed_state_hash}</dd>
            <dt>Live state hash</dt><dd>{rep.live_state_hash}</dd>
            <dt>Ledger events applied</dt><dd>{num(rep.ledger_events_applied)}</dd>
            <dt>Cash conservation</dt><dd>opening {usd(rep.conservation.opening_total_minor)} + external {usd(rep.conservation.external_net_flow_minor)} = closing {usd(rep.conservation.closing_total_minor)}</dd>
          </dl>
        </Panel>
      )}
      <Panel title="Event log" tag={`page ${page + 1} of ${Math.max(1, Math.ceil((ev.data?.total ?? 0) / size))}`}>
        <div className="ctl" style={{ marginBottom: 10 }}>
          <label>Event type<select value={type} onChange={(e) => { setType(e.target.value); setPage(0); }}>{TYPES.map((t) => <option key={t} value={t}>{t || "all"}</option>)}</select></label>
          <button className="btn ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>← prev</button>
          <button className="btn ghost" disabled={(page + 1) * size >= (ev.data?.total ?? 0)} onClick={() => setPage((p) => p + 1)}>next →</button>
        </div>
        <div className="scroll" style={{ maxHeight: 560 }}>
          <table className="t">
            <thead><tr><th>Seq</th><th>Time (ET)</th><th>Type</th><th>Aggregate</th><th>Key payload</th><th>Record hash</th></tr></thead>
            <tbody>
              {ev.data?.items.map((e) => {
                const p = e.payload as Record<string, number | string>;
                const key = p.amount_minor !== undefined ? usd(Number(p.amount_minor)) : p.gross_value_minor !== undefined ? `gross ${usd(Number(p.gross_value_minor))} / net ${usd(Number(p.net_debit_value_minor))}` : p.reason ?? p.rail_id ?? "";
                return [
                  <tr key={e.seq} onClick={() => setOpen(open === e.seq ? null : e.seq)} style={{ cursor: "pointer" }} className={open === e.seq ? "sel" : ""}>
                    <td>{e.seq}</td><td>{hhmm(e.at)}</td>
                    <td className={e.type.includes("Rejected") || e.type.includes("Expired") || e.type.includes("Outage") ? "warn" : e.type.includes("Settled") ? "ok" : ""}>{e.type}</td>
                    <td>{e.aggregate_type}:{e.aggregate_id.length > 28 ? short(e.aggregate_id, 28) : e.aggregate_id}</td>
                    <td className="muted">{String(key)}</td><td className="dim">{short(e.record_hash, 14)}</td>
                  </tr>,
                  open === e.seq && (
                    <tr key={`${e.seq}-d`}><td colSpan={6} style={{ whiteSpace: "pre-wrap", color: "var(--muted)" }}>
                      {JSON.stringify(e.payload, null, 2)}{"\n"}prev_hash {e.prev_hash}{"\n"}record_hash {e.record_hash}
                    </td></tr>
                  ),
                ];
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
