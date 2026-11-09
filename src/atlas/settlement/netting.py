"""Partial multilateral netting ("gridlock resolution") over queued obligations.

Problem. Given queued obligations p (payer a, payee b, amount v_p) and each
account's available settlement cash L_a, choose a subset S to settle
simultaneously such that every account stays non-negative::

    L_a + sum_{p in S, payee=a} v_p - sum_{p in S, payer=a} v_p >= 0   for all a

and the settled value (optionally weighted) is maximal. This is a 0-1 integer
program; exact solution is NP-hard in general (it generalizes subset-sum).

Algorithms
----------
* ``partial_netting_heuristic`` — iterative removal. Start from the full queue;
  while some account is short, drop that account's *least important* outgoing
  obligation (lowest priority, then latest due, then largest), recompute and
  repeat. This is the family of gridlock-resolution algorithms described by
  Güntzer, Jungnickel & Leclerc (1998), "Efficient algorithms for the clearing of
  interbank payments", EJOR 106(1), and studied in RTGS simulations by Bech &
  Soramäki (2001), Bank of Finland Discussion Paper 9/2001. Polynomial; the
  result is always feasible but may be sub-optimal.
* ``partial_netting_milp`` — the exact 0-1 program above solved with HiGHS via
  ``scipy.optimize.milp``. Returns solver status and gap; never relaxes the
  non-negativity constraints. Used as the optimality reference for the heuristic.

Both return selections that are re-verified by ``is_feasible`` before use.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Obligation:
    obligation_id: str
    payer: str          # account id
    payee: str          # account id
    amount_minor: int
    priority: int = 1
    due_at: datetime | None = None
    submitted_seq: int = 0

    def __post_init__(self) -> None:
        if self.payer == self.payee:
            raise ValueError("payer and payee must differ")
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool) or self.amount_minor <= 0:
            raise ValueError("obligation amount must be positive integer minor units")


@dataclass(frozen=True, slots=True)
class NettingSelection:
    selected: tuple[Obligation, ...]
    algorithm: str
    status: str                       # "optimal" | "feasible" | "empty" | "infeasible" | "timeout"
    gross_value_minor: int
    net_liquidity_used_minor: int     # sum of net debits funded from cash
    runtime_ms: float
    objective: float | None = None
    mip_gap: float | None = None

    @property
    def liquidity_saving_ratio(self) -> float:
        """Share of gross value settled without cash (1 - net/gross). Diagnostic only, not ledger state."""
        if self.gross_value_minor == 0:
            return 0.0
        return 1.0 - self.net_liquidity_used_minor / self.gross_value_minor


def net_positions(obligations: Iterable[Obligation]) -> dict[str, int]:
    net: dict[str, int] = {}
    for o in obligations:
        net[o.payer] = net.get(o.payer, 0) - o.amount_minor
        net[o.payee] = net.get(o.payee, 0) + o.amount_minor
    return net


def is_feasible(obligations: Iterable[Obligation], available: Mapping[str, int]) -> bool:
    return all(available.get(acct, 0) + pos >= 0 for acct, pos in net_positions(obligations).items())


def _selection(selected: Sequence[Obligation], algorithm: str, status: str, started: float, **extra) -> NettingSelection:
    net = net_positions(selected)
    return NettingSelection(
        tuple(sorted(selected, key=lambda o: o.obligation_id)), algorithm, status if selected else "empty",
        sum(o.amount_minor for o in selected), sum(-v for v in net.values() if v < 0),
        (time.perf_counter() - started) * 1000.0, **extra,
    )


def _removal_key(o: Obligation) -> tuple:
    # remove lowest priority first, then latest deadline, then largest amount, then latest submitted
    due = o.due_at.timestamp() if o.due_at else float("inf")
    return (o.priority, -due, -o.amount_minor, -o.submitted_seq, o.obligation_id)


def _remove_until_feasible(obligations: Sequence[Obligation], available: Mapping[str, int], rule: str) -> list[Obligation]:
    """Iterative removal. ``rule`` picks which outgoing obligation of a short account to drop:

    * ``priority_largest`` - lowest priority, latest deadline, largest amount first (classic ordering);
    * ``priority_bestfit`` - within the lowest priority class, the smallest obligation that alone
      covers the deficit (else the largest), which destroys less settled value per removal.
    """
    active = {o.obligation_id: o for o in obligations}
    out_by: dict[str, list[Obligation]] = {}
    for o in obligations:
        out_by.setdefault(o.payer, []).append(o)
    net = net_positions(obligations)
    while True:
        short = sorted(a for a, pos in net.items() if available.get(a, 0) + pos < 0)
        if not short:
            return list(active.values())
        for acct in short:
            while available.get(acct, 0) + net[acct] < 0:
                cands = [o for o in out_by.get(acct, ()) if o.obligation_id in active]
                deficit = -(available.get(acct, 0) + net[acct])
                if rule == "priority_bestfit":
                    lowest = min(o.priority for o in cands)
                    pool = [o for o in cands if o.priority == lowest]
                    covering = [o for o in pool if o.amount_minor >= deficit]
                    o = min(covering, key=lambda x: (x.amount_minor, x.obligation_id)) if covering else max(pool, key=lambda x: (x.amount_minor, x.obligation_id))
                else:
                    o = min(cands, key=_removal_key)
                del active[o.obligation_id]
                net[o.payer] += o.amount_minor
                net[o.payee] -= o.amount_minor


def partial_netting_heuristic(obligations: Sequence[Obligation], available: Mapping[str, int]) -> NettingSelection:
    """Best of three polynomial constructions, each repaired by greedy reinsertion.

    Removal can cascade (dropping A->B starves B, which then drops B->A), so each
    candidate is extended by ``_extend`` and one candidate is grown from the
    bilateral-offset selection, which captures two-way pairs that are only
    feasible together. The candidate with the largest settled value wins.
    """
    started = time.perf_counter()
    if any(v < 0 for v in available.values()):
        raise ValueError("available liquidity must be non-negative")
    if len({o.obligation_id for o in obligations}) != len(obligations):
        raise ValueError("duplicate obligation ids")
    candidates = [
        _extend(_remove_until_feasible(obligations, available, "priority_largest"), obligations, available),
        _extend(_remove_until_feasible(obligations, available, "priority_bestfit"), obligations, available),
        _extend(list(bilateral_offsets(obligations, available).selected), obligations, available),
    ]
    selected = max(candidates, key=lambda s: (sum(o.amount_minor for o in s), len(s), sorted(o.obligation_id for o in s)))
    assert is_feasible(selected, available)
    return _selection(selected, "gridlock-heuristic-v3", "feasible", started)


def _extend(seed: list[Obligation], obligations: Sequence[Obligation], available: Mapping[str, int]) -> list[Obligation]:
    """Greedily add obligations (most important first) while every account stays non-negative."""
    chosen = {o.obligation_id for o in seed}
    net = net_positions(seed)
    rest = sorted((o for o in obligations if o.obligation_id not in chosen), key=_removal_key, reverse=True)
    out = list(seed)
    changed = True
    while changed and rest:
        changed = False
        for o in list(rest):
            # adding o only lowers the payer's position, so only the payer must be re-checked
            if available.get(o.payer, 0) + net.get(o.payer, 0) - o.amount_minor >= 0:
                out.append(o)
                net[o.payer] = net.get(o.payer, 0) - o.amount_minor
                net[o.payee] = net.get(o.payee, 0) + o.amount_minor
                rest.remove(o)
                changed = True
    return out


def partial_netting_milp(
    obligations: Sequence[Obligation],
    available: Mapping[str, int],
    *,
    weights: Mapping[str, float] | None = None,
    time_limit_s: float = 5.0,
) -> NettingSelection:
    """Exact 0-1 program via HiGHS. Raises ImportError if SciPy is not installed."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    started = time.perf_counter()
    if not obligations:
        return _selection([], "netting-milp-highs-v1", "empty", started)
    accounts = sorted({o.payer for o in obligations} | {o.payee for o in obligations})
    idx = {a: i for i, a in enumerate(accounts)}
    n, m = len(obligations), len(accounts)
    scale = max(o.amount_minor for o in obligations)
    a_mat = lil_matrix((m, n))
    for j, o in enumerate(obligations):
        a_mat[idx[o.payer], j] += o.amount_minor / scale
        a_mat[idx[o.payee], j] -= o.amount_minor / scale
    ub = np.array([available.get(a, 0) / scale for a in accounts])
    w = np.array([(weights or {}).get(o.obligation_id, 1.0) * o.amount_minor / scale for o in obligations])
    res = milp(
        c=-w, constraints=LinearConstraint(a_mat.tocsr(), -np.inf, ub + 1e-9), integrality=np.ones(n),
        bounds=Bounds(0, 1), options={"time_limit": time_limit_s, "disp": False},
    )
    if res.x is None:
        return _selection([], "netting-milp-highs-v1", "infeasible" if res.status == 2 else "timeout", started)
    chosen = [o for o, x in zip(obligations, res.x) if x > 0.5]
    # Floating-point solver output is re-verified in exact integer arithmetic; drop to heuristic subset if needed.
    if not is_feasible(chosen, available):
        fallback = partial_netting_heuristic(chosen, available)
        chosen = list(fallback.selected)
    status = "optimal" if res.status == 0 else "timeout"
    gap = getattr(res, "mip_gap", None)
    return _selection(chosen, "netting-milp-highs-v1", status, started, objective=float(-res.fun) * scale, mip_gap=gap)


def bilateral_offsets(obligations: Sequence[Obligation], available: Mapping[str, int]) -> NettingSelection:
    """Settle opposing pairs between two accounts when the net debit is covered.

    For each account pair, greedily include obligations in priority/submission order
    while both sides remain non-negative using only that pair's flows. Pairs are
    processed in sorted order and the running available balance is updated, so the
    combined selection is feasible.
    """
    started = time.perf_counter()
    pairs: dict[tuple[str, str], list[Obligation]] = {}
    for o in obligations:
        pairs.setdefault(tuple(sorted((o.payer, o.payee))), []).append(o)
    avail = dict(available)
    selected: list[Obligation] = []
    for key in sorted(pairs):
        group = pairs[key]
        if len({o.payer for o in group}) < 2:
            continue  # one-directional: nothing to offset
        group.sort(key=lambda o: (-o.priority, o.submitted_seq, o.obligation_id))
        chosen = list(group)
        while chosen and not is_feasible(chosen, avail):
            # drop the least important obligation from the side that is short
            net = net_positions(chosen)
            short = next(a for a in key if avail.get(a, 0) + net.get(a, 0) < 0)
            victim = max((o for o in chosen if o.payer == short), key=lambda o: (-o.priority, o.submitted_seq))
            chosen.remove(victim)
        if len({o.payer for o in chosen}) < 2:
            continue
        for a, pos in net_positions(chosen).items():
            avail[a] = avail.get(a, 0) + pos
        selected.extend(chosen)
    assert is_feasible(selected, available)
    return _selection(selected, "bilateral-offset-v1", "feasible", started)
