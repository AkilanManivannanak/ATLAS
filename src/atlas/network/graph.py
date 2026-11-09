"""Directed, value-weighted payment-flow graph and systemic-importance metrics.

Algorithms (implemented directly so the core has no graph dependency; each is
cross-checked against networkx in tests):

* Brandes (2001), "A faster algorithm for betweenness centrality", J. Math. Sociology 25(2).
* PageRank by power iteration (Page et al., 1999) on value-weighted out-edges.
* Tarjan (1972) strongly connected components (iterative, recursion-free).
* Herfindahl–Hirschman index of sender value shares for concentration.

Every edge keeps its provenance (payment ids) and validity window, so a graph
snapshot is traceable to the events that produced it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Edge:
    source: str
    target: str
    rail: str
    value_minor: int = 0
    count: int = 0
    first_at: str | None = None
    last_at: str | None = None
    payment_ids: list[str] = field(default_factory=list)


@dataclass
class FlowGraph:
    nodes: dict[str, dict]
    edges: dict[tuple[str, str, str], Edge]

    def adjacency(self, *, weighted: bool = False) -> dict[str, dict[str, int]]:
        adj: dict[str, dict[str, int]] = {n: {} for n in self.nodes}
        for (s, t, _), e in self.edges.items():
            adj[s][t] = adj[s].get(t, 0) + (e.value_minor if weighted else 1)
        if not weighted:
            adj = {s: {t: 1 for t in d} for s, d in adj.items()}
        return adj

    def strength(self) -> tuple[dict[str, int], dict[str, int]]:
        out = {n: 0 for n in self.nodes}
        inn = {n: 0 for n in self.nodes}
        for (s, t, _), e in self.edges.items():
            out[s] += e.value_minor
            inn[t] += e.value_minor
        return out, inn

    def to_dict(self, *, max_payment_refs: int = 5) -> dict:
        return {
            "nodes": [{"id": n, **attrs} for n, attrs in sorted(self.nodes.items())],
            "edges": [{"source": e.source, "target": e.target, "rail": e.rail, "value_minor": e.value_minor, "count": e.count,
                       "first_at": e.first_at, "last_at": e.last_at, "payment_refs": e.payment_ids[:max_payment_refs]}
                      for _, e in sorted(self.edges.items())],
        }


def build_flow_graph(payments: Iterable[Mapping], institutions: Iterable[Mapping] | None = None, *,
                     statuses: tuple[str, ...] | None = ("settled",), rails: tuple[str, ...] | None = None,
                     start: datetime | None = None, end: datetime | None = None) -> FlowGraph:
    """Payments are dicts with payment_id, sender, receiver, rail, amount_minor, arrival, status (SimulationResult.payments)."""
    nodes: dict[str, dict] = {}
    for inst in institutions or ():
        nodes[inst["institution_id"]] = {k: v for k, v in inst.items() if k != "institution_id"}
    edges: dict[tuple[str, str, str], Edge] = {}
    for p in payments:
        if statuses is not None and p.get("status") not in statuses:
            continue
        if rails is not None and p["rail"] not in rails:
            continue
        at = p.get("settled_at") or p.get("arrival")
        if (start or end) and at is not None:
            t = datetime.fromisoformat(at) if isinstance(at, str) else at
            if (start and t < start) or (end and t >= end):
                continue
        s, r = p["sender"], p["receiver"]
        nodes.setdefault(s, {})
        nodes.setdefault(r, {})
        key = (s, r, p["rail"])
        e = edges.get(key) or edges.setdefault(key, Edge(s, r, p["rail"]))
        e.value_minor += p["amount_minor"]
        e.count += 1
        ts = at if isinstance(at, str) or at is None else at.isoformat()
        e.first_at = min(filter(None, (e.first_at, ts)), default=None)
        e.last_at = max(filter(None, (e.last_at, ts)), default=None)
        e.payment_ids.append(p["payment_id"])
    return FlowGraph(nodes, edges)


def betweenness_centrality(adj: Mapping[str, Mapping[str, int]], *, normalized: bool = True) -> dict[str, float]:
    """Brandes' algorithm for unweighted directed graphs."""
    nodes = sorted(adj)
    cb = {v: 0.0 for v in nodes}
    for s in nodes:
        stack: list[str] = []
        pred: dict[str, list[str]] = {w: [] for w in nodes}
        sigma = {w: 0 for w in nodes}
        sigma[s] = 1
        dist = {w: -1 for w in nodes}
        dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in sorted(adj[v]):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = {w: 0.0 for w in nodes}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]
    n = len(nodes)
    if normalized and n > 2:
        scale = 1.0 / ((n - 1) * (n - 2))
        cb = {v: c * scale for v, c in cb.items()}
    return cb


def pagerank(adj_weighted: Mapping[str, Mapping[str, int]], *, damping: float = 0.85, tol: float = 1e-12, max_iter: int = 500) -> dict[str, float]:
    nodes = sorted(adj_weighted)
    n = len(nodes)
    if n == 0:
        return {}
    rank = {v: 1.0 / n for v in nodes}
    out_w = {v: sum(adj_weighted[v].values()) for v in nodes}
    for _ in range(max_iter):
        dangling = sum(rank[v] for v in nodes if out_w[v] == 0)
        new = {v: (1 - damping) / n + damping * dangling / n for v in nodes}
        for v in nodes:
            if out_w[v]:
                for w, wt in adj_weighted[v].items():
                    new[w] += damping * rank[v] * wt / out_w[v]
        err = sum(abs(new[v] - rank[v]) for v in nodes)
        rank = new
        if err < n * tol:
            break
    return rank


def strongly_connected_components(adj: Mapping[str, Mapping[str, int]]) -> list[list[str]]:
    """Iterative Tarjan; components returned sorted by size desc then name."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    comps: list[list[str]] = []
    counter = 0
    for root in sorted(adj):
        if root in index:
            continue
        work = [(root, iter(sorted(adj[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(adj.get(w, {})))))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(sorted(comp))
    return sorted(comps, key=lambda c: (-len(c), c))


def hhi(shares: Iterable[int]) -> float:
    vals = [s for s in shares if s > 0]
    total = sum(vals)
    return sum((v / total) ** 2 for v in vals) if total else 0.0


def residual_gridlock_components(payments: Iterable[Mapping], rails: tuple[str, ...] = ("rtgs", "lsm")) -> list[dict]:
    """Cyclic components among payments left unsettled at close: candidates for liquidity-saving intervention."""
    g = build_flow_graph(payments, statuses=("unsettled",), rails=rails)
    out = []
    for comp in strongly_connected_components(g.adjacency()):
        if len(comp) < 2:
            continue
        members = set(comp)
        value = sum(e.value_minor for (s, t, _), e in g.edges.items() if s in members and t in members)
        out.append({"institutions": comp, "unsettled_cycle_value_minor": value})
    return out


def network_report(payments: list[Mapping], institutions: list[Mapping] | None = None, *, statuses: tuple[str, ...] | None = ("settled",),
                   rails: tuple[str, ...] | None = None) -> dict:
    g = build_flow_graph(payments, institutions, statuses=statuses, rails=rails)
    adj = g.adjacency()
    out_s, in_s = g.strength()
    n = len(g.nodes)
    m = sum(len(v) for v in adj.values())
    bc = betweenness_centrality(adj)
    pr = pagerank(g.adjacency(weighted=True))
    sccs = strongly_connected_components(adj)
    recip = sum(1 for s, d in adj.items() for t in d if s in adj.get(t, {})) / m if m else 0.0
    total = sum(out_s.values())
    nodes = []
    for v in sorted(g.nodes):
        nodes.append({
            "id": v, **g.nodes[v], "out_degree": len(adj[v]), "in_degree": sum(1 for d in adj.values() if v in d),
            "out_strength_minor": out_s[v], "in_strength_minor": in_s[v], "betweenness": bc[v], "pagerank": pr[v],
            "value_share": out_s[v] / total if total else 0.0,
        })
    # systemic-importance ranking: mean of percentile ranks over strength, pagerank and betweenness
    def ranks(key: str) -> dict[str, float]:
        order = sorted(nodes, key=lambda x: x[key])
        return {x["id"]: i / max(1, len(order) - 1) for i, x in enumerate(order)}
    rs, rp, rb = ranks("out_strength_minor"), ranks("pagerank"), ranks("betweenness")
    for x in nodes:
        x["systemic_score"] = (rs[x["id"]] + rp[x["id"]] + rb[x["id"]]) / 3
    critical = sorted(nodes, key=lambda x: (-x["systemic_score"], x["id"]))[:5]
    return {
        "nodes": nodes, "edges": g.to_dict()["edges"], "n_nodes": n, "n_edges": m,
        "density": m / (n * (n - 1)) if n > 1 else 0.0, "reciprocity": recip,
        "hhi_sender_value": hhi(out_s.values()), "hhi_receiver_value": hhi(in_s.values()),
        "scc_sizes": [len(c) for c in sccs], "largest_scc": sccs[0] if sccs else [],
        "critical_participants": [{"id": x["id"], "systemic_score": x["systemic_score"]} for x in critical],
    }


def hourly_snapshots(payments: list[Mapping], open_at: datetime, close_at: datetime, *, statuses: tuple[str, ...] | None = ("settled",)) -> list[dict]:
    from datetime import timedelta
    out = []
    t = open_at
    while t < close_at:
        g = build_flow_graph(payments, statuses=statuses, start=t, end=t + timedelta(hours=1))
        adj = g.adjacency()
        out_s, _ = g.strength()
        out.append({"start": t.isoformat(), "n_edges": sum(len(v) for v in adj.values()), "value_minor": sum(out_s.values()),
                    "hhi_sender_value": hhi(out_s.values()), "largest_scc": len(strongly_connected_components(adj)[0]) if adj else 0})
        t += timedelta(hours=1)
    return out
