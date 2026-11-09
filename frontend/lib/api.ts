// Typed client for the ATLAS-Σ REST API. Every value rendered in the UI comes from these calls.

export type Headline = {
  total_cost_minor: number;
  lv_settlement_rate_value: number;
  lv_value_weighted_delay_s: number;
  instant_rejected: number;
  liquidity_usage_minor: number;
  events: number;
  runtime_s: number;
};

export type RunSummary = {
  id: string;
  label: string | null;
  request: Record<string, unknown>;
  created_at: number;
  stress: string;
  policy: string;
  controller: string | null;
  headline: Headline;
  final_state_hash: string;
  scenario: { institutions: number; payments: number; fingerprint: string; by_rail: Record<string, { count: number; value_minor: number }> };
};

export type RailStats = {
  count: number;
  value_minor: number;
  settled_count: number;
  settled_value_minor: number;
  settlement_rate_value: number;
  settlement_rate_count: number;
  mean_delay_s: number;
  p95_delay_s: number;
  value_weighted_delay_s: number;
  deadline_miss_count: number;
  deadline_miss_value_minor: number;
};

export type Institution = {
  institution_id: string;
  tier: string;
  strategy: string;
  rails: string[];
  sent_count: number;
  sent_value_minor: number;
  settlement_rate_value: number;
  value_weighted_delay_s: number;
  liquidity_usage_minor: number;
  peak_credit_minor: number;
  opening_minor: Record<string, number>;
  closing_minor: Record<string, number>;
  received_value_minor: number;
};

export type RunDetail = RunSummary & {
  metrics: {
    large_value: RailStats;
    instant: RailStats;
    by_rail: Record<string, RailStats>;
    liquidity: Record<string, number | null>;
    costs_minor: Record<string, number>;
    counters: Record<string, number>;
    events: number;
    runtime_s: number;
    events_per_second: number;
  };
  per_institution: Institution[];
  timeseries: Record<string, number | string>[];
  manifest: Record<string, unknown>;
  controller_log: { at: string; kind: string; approved: boolean; reason: string; rationale: string; amount_minor: number; institution: string; from_rail: string; to_rail: string; payment_count: number }[];
  settings: Record<string, unknown>;
};

export type NetworkNode = {
  id: string;
  tier?: string;
  strategy?: string;
  out_strength_minor: number;
  in_strength_minor: number;
  betweenness: number;
  pagerank: number;
  systemic_score: number;
  value_share: number;
  out_degree: number;
  in_degree: number;
};
export type NetworkEdge = { source: string; target: string; rail: string; value_minor: number; count: number };
export type NetworkReport = {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  n_nodes: number;
  n_edges: number;
  density: number;
  reciprocity: number;
  hhi_sender_value: number;
  scc_sizes: number[];
  critical_participants: { id: string; systemic_score: number }[];
  hourly: { start: string; n_edges: number; value_minor: number; hhi_sender_value: number; largest_scc: number }[];
  residual_gridlock: { institutions: string[]; unsettled_cycle_value_minor: number }[];
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body?.error?.message === "string" ? body.error.message : JSON.stringify(body?.error?.message ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}
