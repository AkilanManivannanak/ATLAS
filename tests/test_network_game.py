import networkx as nx
import pytest

from atlas.agents.game import deviation_analysis, institution_cost
from atlas.network import betweenness_centrality, build_flow_graph, network_report, pagerank, residual_gridlock_components, strongly_connected_components
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import CostModel, SimulationSettings, run_day


def _payments(edges):
    return [{"payment_id": f"p{i}", "sender": s, "receiver": r, "rail": "rtgs", "amount_minor": v, "status": "settled",
             "arrival": "2026-03-10T13:00:00+00:00", "settled_at": "2026-03-10T13:01:00+00:00"} for i, (s, r, v) in enumerate(edges)]


EDGES = [("A", "B", 5), ("B", "C", 3), ("C", "A", 2), ("C", "D", 9), ("D", "E", 1), ("E", "D", 4), ("A", "D", 7), ("F", "A", 1)]


def _nx(edges, weighted=False):
    g = nx.DiGraph()
    for s, r, v in edges:
        if g.has_edge(s, r):
            g[s][r]["weight"] += v
        else:
            g.add_edge(s, r, weight=v)
    return g


def test_betweenness_matches_networkx():
    adj = build_flow_graph(_payments(EDGES)).adjacency()
    ours = betweenness_centrality(adj)
    ref = nx.betweenness_centrality(_nx(EDGES), normalized=True)
    assert ours == pytest.approx(ref, abs=1e-12)


def test_pagerank_matches_networkx():
    adj = build_flow_graph(_payments(EDGES)).adjacency(weighted=True)
    ours = pagerank(adj)
    ref = nx.pagerank(_nx(EDGES), weight="weight", tol=1e-13)
    assert ours == pytest.approx(ref, abs=1e-8)


def test_scc_matches_networkx():
    adj = build_flow_graph(_payments(EDGES)).adjacency()
    ours = {frozenset(c) for c in strongly_connected_components(adj)}
    ref = {frozenset(c) for c in nx.strongly_connected_components(_nx(EDGES))}
    assert ours == ref


def test_edges_keep_provenance_and_report_ranks_critical_nodes():
    g = build_flow_graph(_payments(EDGES))
    assert g.edges[("A", "B", "rtgs")].payment_ids == ["p0"]
    rep = network_report(_payments(EDGES))
    assert rep["n_nodes"] == 6 and rep["n_edges"] == 8
    assert 0 < rep["hhi_sender_value"] <= 1
    assert rep["critical_participants"][0]["id"] in {"A", "C", "D"}


def test_residual_gridlock_detects_unsettled_cycle():
    pays = _payments([("A", "B", 5), ("B", "A", 6), ("C", "A", 1)])
    for p in pays:
        p["status"] = "unsettled"
    comps = residual_gridlock_components(pays)
    assert comps == [{"institutions": ["A", "B"], "unsettled_cycle_value_minor": 11}]


def test_report_on_simulated_day():
    sc = generate_scenario(NexusPayConfig(n_institutions=8, payments_per_day=400, instant_payments_per_day=100), seed=5)
    r = run_day(sc, SimulationSettings())
    rep = network_report(r.payments, r.per_institution)
    assert rep["n_nodes"] == 8 and rep["largest_scc"]
    core = {x["institution_id"] for x in r.per_institution if x["tier"] == "core"}
    top = rep["critical_participants"][0]["id"]
    assert top in core


def test_institution_cost_components():
    stats = {"sent_value_minor": 1_000_000, "settlement_rate_value": 0.5, "value_weighted_delay_s": 3600,
             "liquidity_usage_minor": 200_000, "peak_credit_minor": 0}
    c = CostModel(delay_bp_per_hour=10, unsettled_penalty_bp=100, liquidity_bp_per_day=50, credit_bp_per_day=0)
    assert institution_cost(stats, c) == 500 + 5_000 + 1_000


def test_deviation_analysis_reports_scoped_claims():
    res = deviation_analysis(config=NexusPayConfig(n_institutions=6, payments_per_day=200, instant_payments_per_day=50,
                                                   opening_liquidity_bp=600), seeds=(1, 2), focal=("@largest",))
    assert set(res["profiles"]) == {"early", "conservative"}
    for v in res["profiles"].values():
        assert v["verdict"] in {"unstable", "inconclusive", "empirical_epsilon_equilibrium"}
        assert "not a proof" in v["claim_scope"]
    assert len(res["deviations"]) == 2
