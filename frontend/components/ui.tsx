"use client";

import { ReactNode, useEffect, useState } from "react";
import { api, RunDetail, RunSummary } from "@/lib/api";

export function Panel({ title, tag, children, style }: { title?: string; tag?: ReactNode; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <section className="panel" style={style}>
      {title && (
        <h3>
          <span>{title}</span>
          {tag && <span className="tag">{tag}</span>}
        </h3>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ok" | "warn" | "bad" }) {
  return (
    <Panel>
      <div className="stat">
        <div className="l">{label}</div>
        <div className={`v ${tone ?? ""}`}>{value}</div>
        {sub && <div className="s">{sub}</div>}
      </div>
    </Panel>
  );
}

export function Header({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="topbar">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="err">API error: {error instanceof Error ? error.message : String(error)}</div>;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: unknown; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

const RUN_KEY = "atlas.selectedRun";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(RUN_KEY);
  } catch {
    return null;
  }
}
function writeStored(v: string) {
  try {
    window.localStorage.setItem(RUN_KEY, v);
  } catch {
    /* storage unavailable: selection just won't persist */
  }
}

/** Shared simulation-run selector; the choice is a per-viewer convenience kept in localStorage. */
export function useRun() {
  const runs = useAsync(() => api<RunSummary[]>("/simulations"), []);
  const [runId, setRunId] = useState<string | null>(null);
  useEffect(() => {
    if (!runs.data?.length) return;
    const stored = readStored();
    const pick = runs.data.find((r) => r.id === stored)?.id ?? runs.data[runs.data.length - 1].id;
    setRunId((cur) => cur ?? pick);
  }, [runs.data]);
  const detail = useAsync<RunDetail | null>(() => (runId ? api<RunDetail>(`/simulations/${encodeURIComponent(runId)}`) : Promise.resolve(null)), [runId]);
  const select = (id: string) => {
    writeStored(id);
    setRunId(id);
  };
  return { runs, runId, select, detail };
}

export function RunPicker({ runs, runId, onSelect }: { runs: RunSummary[] | null; runId: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="ctl">
      <label>
        Simulation run
        <select value={runId ?? ""} onChange={(e) => onSelect(e.target.value)} style={{ minWidth: "min(320px, 100%)" }}>
          {(runs ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.label ?? r.id} · {r.policy}
              {r.controller ? ` + ${r.controller}` : ""} · {r.stress}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export function SyntheticBadge() {
  return (
    <span className="pill warn" title="All data in ATLAS-Σ is produced by the simulator">
      <span className="dot" /> SIMULATED DATA
    </span>
  );
}
