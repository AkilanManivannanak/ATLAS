import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atlas.settlement import Obligation, bilateral_offsets, is_feasible, net_positions, partial_netting_heuristic, partial_netting_milp


def ob(i, a, b, v, pr=1):
    return Obligation(f"o{i}", a, b, v, pr, None, i)


def brute_force(obligations, available):
    best = 0
    for r in range(len(obligations) + 1):
        for combo in itertools.combinations(obligations, r):
            if is_feasible(combo, available):
                best = max(best, sum(o.amount_minor for o in combo))
    return best


def test_two_way_pair_with_zero_cash_settles_by_offset():
    obs = [ob(0, "A", "B", 100), ob(1, "B", "A", 100), ob(2, "A", "C", 50)]
    avail = {"A": 0, "B": 0, "C": 0}
    for algo in (partial_netting_heuristic, partial_netting_milp, bilateral_offsets):
        sel = algo(obs, avail)
        assert {o.obligation_id for o in sel.selected} == {"o0", "o1"}
        assert sel.net_liquidity_used_minor == 0 and sel.liquidity_saving_ratio == 1.0


def test_gridlock_cycle_resolved_multilaterally_not_bilaterally():
    obs = [ob(0, "A", "B", 100), ob(1, "B", "C", 100), ob(2, "C", "A", 100)]
    avail = {"A": 0, "B": 0, "C": 0}
    assert bilateral_offsets(obs, avail).selected == ()
    assert len(partial_netting_heuristic(obs, avail).selected) == 3 or len(partial_netting_milp(obs, avail).selected) == 3
    assert len(partial_netting_milp(obs, avail).selected) == 3


def test_net_positions_sum_to_zero_and_invalid_obligations_rejected():
    obs = [ob(0, "A", "B", 7), ob(1, "B", "C", 3)]
    assert sum(net_positions(obs).values()) == 0
    with pytest.raises(ValueError):
        Obligation("x", "A", "A", 1)
    with pytest.raises(ValueError):
        Obligation("x", "A", "B", 0)


@settings(max_examples=80, deadline=None)
@given(
    edges=st.lists(st.tuples(st.integers(0, 4), st.integers(0, 4), st.integers(1, 50), st.integers(0, 2)), min_size=1, max_size=9),
    cash=st.lists(st.integers(0, 60), min_size=5, max_size=5),
)
def test_property_heuristic_feasible_and_milp_optimal(edges, cash):
    obs = [ob(i, f"N{a}", f"N{b}", v, pr) for i, (a, b, v, pr) in enumerate(edges) if a != b]
    if not obs:
        return
    avail = {f"N{i}": c for i, c in enumerate(cash)}
    h = partial_netting_heuristic(obs, avail)
    m = partial_netting_milp(obs, avail)
    b = bilateral_offsets(obs, avail)
    opt = brute_force(obs, avail)
    for sel in (h, m, b):
        assert is_feasible(sel.selected, avail)   # never violates a hard liquidity constraint
    assert m.gross_value_minor == opt             # exact program reaches the brute-force optimum
    assert b.gross_value_minor <= h.gross_value_minor <= opt
