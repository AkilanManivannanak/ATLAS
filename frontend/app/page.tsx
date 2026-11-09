"use client";

import { useCallback, useState } from "react";
import { NetworkGraph } from "@/components/NetworkGraph";
import { ErrorBox, Header, Panel, RunPicker, Stat, SyntheticBadge, useAsync, useRun } from "@/components/ui";
import { api, NetworkReport } from "@/lib/api";
import { hhmm, num, pct, usd } from "@/lib/format";

export default function GlobalNetwork() {
  const { runs, runId, select, detail } = useRun();
  const [rail, setRail] = useState<string>("");
  const [sel, setSel] = useState<string | null>(null);
  const net = useAsync<NetworkReport | null>(
    () => (runId ? api<NetworkReport>(`/simulations/${encodeURIComponent(runId)}/network${rail ? `?rail=${rail}` : ""}`) : Promise.resolve(null)),
    [runId, rail],
  );
  const onSelect = useCallback((id: string) => setSel(id), []);
  const d = detail.data;
  const n = net.data;
  const node = n?.nodes.find((x) => x.id === sel) ?? null;
  const inst = d?.per_institution.find((x) => x.institution_id === sel) ?? null;
  return (
    <>
      <Header
        title="Global Financial Network"
        subtitle="Settled large-value payment flows between simulated institutions. Node size is gross flow, the inner dot is a systemic-importance score (strength, PageRank, betweenness)."
        right={
          <div className="ctl">
            <SyntheticBadge />
            <label>
              Rail
              <select value={rail} onChange={(e) => setRail(e.target.value)}>
                <option value="">Large-value (RTGS + LSM)</option>
                <option value="rtgs">RTGS</option>
                <option value="lsm">LSM</option>
                <option value="fednow">Instant · public</option>
                <option value="rtp">Instant · private</option>
              </select>
            </label>
            <RunPicker runs={runs.data} runId={runId} onSelect={select} />
          </div>
        }
      />
      <ErrorBox error={runs.error || detail.error || net.error} />
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <Stat label="Institutions" value={num(n?.n_nodes)} sub={`${num(n?.n_edges)} directed links · density ${n ? n.density.toFixed(2) : "—"}`} />
        <Stat label="Sender concentration (HHI)" value={n ? n.hhi_sender_value.toFixed(3) : "—"} sub={`reciprocity ${n ? pct(n.reciprocity, 0) : "—"}`} />
        <Stat label="Largest strongly-connected core" value={num(n?.scc_sizes?.[0])} sub={`components: ${n?.scc_sizes.join(" · ") ?? "—"}`} />
        <Stat
          label="Residual gridlock at close"
          value={usd(n?.residual_gridlock.reduce((a, b) => a + b.unsettled_cycle_value_minor, 0) ?? null)}
          tone={n && n.residual_gridlock.length ? "warn" : "ok"}
          sub={n ? `${n.residual_gridlock.length} cyclic component(s) left unsettled` : ""}
        />
      </div>
      <div className="grid g21">
        <Panel title="Payment network" tag={d ? `${d.label ?? d.id} · fingerprint ${d.scenario.fingerprint.slice(0, 10)}` : ""}>
          {net.loading && !n ? <div className="skeleton">loading network…</div> : n && <NetworkGraph nodes={n.nodes} edges={n.edges} onSelect={onSelect} selected={sel} />}
          <div className="legend">
            <span><i style={{ background: "#6ea8ff" }} />core tier</span>
            <span><i style={{ background: "#7f8fab" }} />periphery</span>
            <span><i style={{ background: "#f2b341" }} />systemic score &gt; 0.8</span>
            <span className="dim">strongest 70 links shown · drag · scroll to zoom · click for detail</span>
          </div>
        </Panel>
        <div className="grid" style={{ alignContent: "start" }}>
          <Panel title="Critical participants" tag="systemic score">
            <table className="t">
              <tbody>
                {n?.critical_participants.map((c) => (
                  <tr key={c.id} className={c.id === sel ? "sel" : ""} onClick={() => setSel(c.id)} style={{ cursor: "pointer" }}>
                    <td>{c.id}</td>
                    <td style={{ width: "55%" }}>
                      <div className="bar-track"><div className="bar-fill" style={{ width: `${c.systemic_score * 100}%`, background: "var(--warn)" }} /></div>
                    </td>
                    <td style={{ textAlign: "right" }}>{c.systemic_score.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title={node ? `Institution ${node.id}` : "Institution detail"} tag={inst?.strategy ? `strategy: ${inst.strategy}` : ""}>
            {node && inst ? (
              <dl className="kv">
                <dt>Tier</dt><dd>{node.tier}</dd>
                <dt>Rails</dt><dd>{inst.rails.join(" · ")}</dd>
                <dt>Sent (LV)</dt><dd>{usd(inst.sent_value_minor)}</dd>
                <dt>Received (LV, settled)</dt><dd>{usd(inst.received_value_minor)}</dd>
                <dt>Settled share (value)</dt><dd className={inst.settlement_rate_value < 0.95 ? "warn" : "ok"}>{pct(inst.settlement_rate_value)}</dd>
                <dt>Liquidity usage</dt><dd>{usd(inst.liquidity_usage_minor)}</dd>
                <dt>Peak intraday credit</dt><dd>{usd(inst.peak_credit_minor)}</dd>
                <dt>PageRank / betweenness</dt><dd>{node.pagerank.toFixed(3)} / {node.betweenness.toFixed(3)}</dd>
                <dt>Value share</dt><dd>{pct(node.value_share, 1)}</dd>
              </dl>
            ) : (
              <div className="note">Select a node to inspect its flows, liquidity usage and centrality.</div>
            )}
          </Panel>
          <Panel title="Hourly network activity">
            <table className="t">
              <thead><tr><th>Hour</th><th>Links</th><th>Value</th><th>HHI</th></tr></thead>
              <tbody>
                {n?.hourly.map((h) => (
                  <tr key={h.start}><td>{hhmm(h.start)}</td><td>{h.n_edges}</td><td>{usd(h.value_minor)}</td><td>{h.hhi_sender_value.toFixed(3)}</td></tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      </div>
    </>
  );
}
