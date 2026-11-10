"use client";

import { useState } from "react";
import { ErrorBox, Header, Panel, RunPicker, SyntheticBadge, useRun } from "@/components/ui";
import { api } from "@/lib/api";

type Answer = { intent: string; answer: string; evidence: { path: string; value: unknown }[]; grounding: string; can_execute: boolean };
type Statement = { account_id: string; reconciliation: { entries: number; opening_minor: number; credits_minor: number; debits_minor: number; closing_minor: number; balanced: boolean; matches_ledger: boolean }; xml: string };

const SUGGESTED = [
  "Why is liquidity declining?",
  "Which institutions are most exposed?",
  "Which settlement policy performed best?",
  "What happens if a major incoming payment is delayed?",
  "Which intervention has the lowest modeled cost?",
  "Why did payments not settle?",
];

const usd = (m: number) => `$${(m / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export default function DecisionCenter() {
  const { runs, runId, select, detail } = useRun();
  const [q, setQ] = useState(SUGGESTED[0]);
  const [log, setLog] = useState<Answer[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [acct, setAcct] = useState("");
  const [stmt, setStmt] = useState<Statement | null>(null);
  const ask = async (question: string) => {
    if (!runId) return;
    setBusy(true);
    setErr(null);
    try {
      const a = await api<Answer>(`/simulations/${encodeURIComponent(runId)}/ask`, { method: "POST", body: JSON.stringify({ question }) });
      setLog((l) => [a, ...l].slice(0, 8));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const accounts = (detail.data?.per_institution ?? []).flatMap((i) => i.rails.map((r) => `${i.institution_id}:${r}`));
  const loadStmt = async (a: string) => {
    setAcct(a);
    setStmt(null);
    if (!a || !runId) return;
    try {
      setStmt(await api<Statement>(`/simulations/${encodeURIComponent(runId)}/statements/${encodeURIComponent(a)}`));
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <>
      <Header
        title="Decision Center"
        subtitle="Ask questions about a simulated day. Answers are produced by deterministic queries over this run; every number is cited to the field it came from. The analyst cannot execute anything."
        right={<div className="ctl"><SyntheticBadge /><RunPicker runs={runs.data} runId={runId} onSelect={(id) => { select(id); setLog([]); setStmt(null); }} /></div>}
      />
      <ErrorBox error={runs.error || detail.error || err} />
      <div className="grid g21">
        <Panel title="Ask the analyst" tag="atlas-analyst-v1 · grounded, no generative model">
          <div className="ctl">
            <input type="text" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(q)} style={{ flex: 1, minWidth: 260 }} />
            <button className="btn" disabled={busy || !runId} onClick={() => ask(q)}>{busy ? "Querying…" : "Ask"}</button>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0" }}>
            {SUGGESTED.map((s) => <button key={s} className="btn ghost" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => { setQ(s); ask(s); }}>{s}</button>)}
          </div>
          {log.map((a, i) => (
            <div key={i} style={{ borderTop: "1px solid var(--line)", padding: "12px 0" }}>
              <div className="mono dim" style={{ fontSize: 11 }}>intent: {a.intent}</div>
              <p style={{ margin: "6px 0 8px" }}>{a.answer}</p>
              {a.evidence.length > 0 && (
                <table className="t">
                  <thead><tr><th>Evidence field</th><th>Value</th></tr></thead>
                  <tbody>{a.evidence.map((e, k) => <tr key={k}><td>{e.path}</td><td>{JSON.stringify(e.value)}</td></tr>)}</tbody>
                </table>
              )}
            </div>
          ))}
        </Panel>
        <Panel title="ISO 20022 statement" tag="camt.053.001.08 from the event store">
          <div className="ctl">
            <label>Account
              <select value={acct} onChange={(e) => loadStmt(e.target.value)}>
                <option value="">choose…</option>
                {accounts.map((a) => <option key={a}>{a}</option>)}
              </select>
            </label>
          </div>
          {stmt && (
            <>
              <dl className="kv" style={{ marginTop: 10 }}>
                <dt>Entries</dt><dd>{stmt.reconciliation.entries}</dd>
                <dt>Opening (OPBD)</dt><dd>{usd(stmt.reconciliation.opening_minor)}</dd>
                <dt>Credits</dt><dd className="ok">+{usd(stmt.reconciliation.credits_minor)}</dd>
                <dt>Debits</dt><dd className="bad">−{usd(stmt.reconciliation.debits_minor)}</dd>
                <dt>Closing (CLBD)</dt><dd>{usd(stmt.reconciliation.closing_minor)}</dd>
                <dt>Statement balances</dt><dd className={stmt.reconciliation.balanced ? "ok" : "bad"}>{String(stmt.reconciliation.balanced)}</dd>
                <dt>Matches ledger replay</dt><dd className={stmt.reconciliation.matches_ledger ? "ok" : "bad"}>{String(stmt.reconciliation.matches_ledger)}</dd>
              </dl>
              <pre className="mono" style={{ maxHeight: 260, overflow: "auto", fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-all", color: "var(--muted)" }}>
                {stmt.xml.slice(0, 2500)}{stmt.xml.length > 2500 ? "\n…" : ""}
              </pre>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}
