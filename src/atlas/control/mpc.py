"""Receding-horizon (MPC) multi-rail liquidity controller.

At each decision interval the controller:

1. reads the current financial state (``SystemView``) - it never sees future payments;
2. forecasts each institution's per-rail liquidity *need* over the horizon H:
   known obligations (central-queue and held outgoing payments due within H) plus
   an empirical q-quantile of recent instant-payment outflow scaled to H
   (a scenario-quantile approximation of the chance constraint
   P(cash >= outflow) >= q);
3. solves, per institution, the rebalancing LP (HiGHS)::

       min  sum_r  pen_r * s_r  +  c * sum_{r != r'} x_{r,r'}
       s.t. avail_r - sum_{r'} x_{r,r'} + sum_{r'} x_{r',r} + s_r >= need_r      for all rails r
            sum_{r'} x_{r,r'} <= movable_r                                        for all rails r
            x, s >= 0

   where ``movable_r`` already respects the safety limits (share cap, committed cash);
4. solves an urgency-weighted 0-1 netting program on the RTGS queue;
5. emits only the *first* step's actions; each must pass the SafetyController.

Rationale and references: Model Predictive Control (Rawlings, Mayne & Diehl,
2017); chance constraints via scenario quantiles (Calafiore & Campi, 2006).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from atlas.settlement import Obligation, partial_netting_milp

INSTANT = ("fednow", "rtp")
LARGE = ("rtgs", "lsm")


@dataclass(frozen=True)
class MPCConfig:
    horizon_min: int = 30
    interval_min: int = 5
    quantile_bp: int = 9_500
    history_windows: int = 12
    instant_penalty: float = 10.0
    rtgs_penalty: float = 3.0
    lsm_penalty: float = 3.0
    transfer_cost: float = 0.01
    min_transfer_minor: int = 50_000_00
    share_cap_bp: int = 3_300              # total out <= 1/3 of cash keeps every sequential action under the 50% safety cap
    transfer_cutoff_min: int = 15
    enable_rebalancing: bool = True
    enable_queue_milp: bool = True
    milp_time_limit_s: float = 1.0


def _quantile(xs: Sequence[int], q_bp: int) -> int:
    if not xs:
        return 0
    s = sorted(xs)
    k = min(len(s) - 1, (len(s) - 1) * q_bp // 10_000 + (1 if ((len(s) - 1) * q_bp) % 10_000 else 0))
    return s[k]


class _NeedsMixin:
    cfg: MPCConfig

    def needs(self, view) -> dict[str, dict[str, int]]:
        """Per institution, per rail: forecast liquidity need over the horizon (integer minor units)."""
        from datetime import timedelta
        horizon_end = view.now + timedelta(minutes=self.cfg.horizon_min)
        out: dict[str, dict[str, int]] = {}
        for acct in view.accounts.values():
            out.setdefault(acct.institution_id, {})[acct.payment_rail_id] = 0
        for p in view.rtgs_queue:
            out[p.sender_institution_id]["rtgs"] += p.amount_minor
        for p in view.lsm_queue:
            out[p.sender_institution_id]["lsm"] += p.amount_minor
        for inst, held in view.held.items():
            for h in held:
                if h.due_at <= horizon_end and h.rail in out[inst]:
                    out[inst][h.rail] += h.amount_minor
        scale_num, scale_den = self.cfg.horizon_min, self.cfg.interval_min
        for acct_id, hist in view.instant_outflow_history.items():
            inst, rail = acct_id.rsplit(":", 1)
            recent = hist[-self.cfg.history_windows:]
            out[inst][rail] += _quantile(recent, self.cfg.quantile_bp) * scale_num // scale_den
        return out


@dataclass
class MPCController(_NeedsMixin):
    cfg: MPCConfig = field(default_factory=MPCConfig)
    name: str = "mpc-highs-v1"
    solve_log: list = field(default_factory=list, repr=False)

    def propose(self, view) -> list:
        from atlas.sim.day import Action
        actions: list = []
        if self.cfg.enable_queue_milp and view.rtgs_queue and view.rail_up.get("rtgs"):
            a = self._queue_action(view, Action)
            if a is not None:
                actions.append(a)
        minutes_left = (view.close_at - view.now).total_seconds() / 60
        if self.cfg.enable_rebalancing and minutes_left >= self.cfg.transfer_cutoff_min:
            actions.extend(self._rebalance(view, Action))
        return actions

    # -- queue optimisation
    def _queue_action(self, view, Action):
        obligations, weights = [], {}
        for seq, p in enumerate(view.rtgs_queue):
            minutes_to_due = (p.due_at - view.now).total_seconds() / 60
            urgency = 1.0 + 4.0 * max(0.0, 1.0 - max(0.0, minutes_to_due) / 60.0) + 0.5 * p.priority
            obligations.append(Obligation(p.payment_id, p.sender_account_id, p.receiver_account_id, p.amount_minor, p.priority, p.due_at, seq))
            weights[p.payment_id] = urgency
        accts = {o.payer for o in obligations} | {o.payee for o in obligations}
        available = {a: view.accounts[a].cash_available_minor for a in accts}
        sel = partial_netting_milp(obligations, available, weights=weights, time_limit_s=self.cfg.milp_time_limit_s)
        self.solve_log.append({"at": view.now.isoformat(), "problem": "queue_milp", "status": sel.status,
                               "n": len(obligations), "selected": len(sel.selected), "runtime_ms": sel.runtime_ms})
        if not sel.selected:
            return None
        return Action("settle_batch", payment_ids=tuple(o.obligation_id for o in sel.selected),
                      rationale=f"urgency-weighted netting ({sel.status}, {len(sel.selected)}/{len(obligations)} payments)")

    # -- liquidity rebalancing
    def _movable(self, view, inst: str, rail: str) -> int:
        acct = view.accounts[f"{inst}:{rail}"]
        queue = view.rtgs_queue if rail == "rtgs" else view.lsm_queue if rail == "lsm" else ()
        committed = sum(p.amount_minor for p in queue if p.sender_account_id == acct.account_id)
        free = max(0, acct.cash_available_minor - committed)
        return min(free, acct.cash_available_minor * self.cfg.share_cap_bp // 10_000)

    def _rebalance(self, view, Action) -> list:
        import numpy as np
        from scipy.optimize import linprog

        actions = []
        needs = self.needs(view)
        for inst in sorted(needs):
            rails = sorted(r for r in needs[inst] if view.rail_up.get(r, False))
            if len(rails) < 2:
                continue
            avail = {r: view.accounts[f"{inst}:{r}"].cash_available_minor + (view.accounts[f"{inst}:{r}"].undrawn_credit_minor if r == "rtgs" else 0) for r in rails}
            deficit = {r: needs[inst][r] - avail[r] for r in rails}
            if all(d <= 0 for d in deficit.values()):
                continue
            pairs = [(a, b) for a in rails for b in rails if a != b]
            nx_, nr = len(pairs), len(rails)
            scale = max(1, max(abs(v) for v in list(avail.values()) + list(needs[inst].values())))
            pen = {"fednow": self.cfg.instant_penalty, "rtp": self.cfg.instant_penalty, "rtgs": self.cfg.rtgs_penalty, "lsm": self.cfg.lsm_penalty}
            c = np.array([self.cfg.transfer_cost] * nx_ + [pen[r] for r in rails])
            a_ub, b_ub = [], []
            for k, r in enumerate(rails):  # -(avail - out + in + s) <= -need
                row = [0.0] * (nx_ + nr)
                for j, (a, b) in enumerate(pairs):
                    if a == r:
                        row[j] = 1.0
                    if b == r:
                        row[j] = -1.0
                row[nx_ + k] = -1.0
                a_ub.append(row)
                b_ub.append((avail[r] - needs[inst][r]) / scale)
            for r in rails:  # outflow <= movable
                row = [0.0] * (nx_ + nr)
                for j, (a, _b) in enumerate(pairs):
                    if a == r:
                        row[j] = 1.0
                a_ub.append(row)
                b_ub.append(self._movable(view, inst, r) / scale)
            res = linprog(c, A_ub=np.array(a_ub), b_ub=np.array(b_ub), bounds=[(0, None)] * (nx_ + nr), method="highs")
            self.solve_log.append({"at": view.now.isoformat(), "problem": "rebalance_lp", "institution": inst, "status": res.status,
                                   "message": res.message if res.status != 0 else "optimal"})
            if res.status != 0:
                continue  # explicit failure: no action, never a relaxed constraint
            for j, (a, b) in enumerate(pairs):
                amount = int(res.x[j] * scale)
                amount = min(amount, self._movable(view, inst, a))
                if amount >= self.cfg.min_transfer_minor:
                    actions.append(Action("transfer", institution=inst, from_rail=a, to_rail=b, amount_minor=amount,
                                          rationale=f"forecast {b} need ${needs[inst][b] / 100:,.0f} vs available ${avail[b] / 100:,.0f} (horizon {self.cfg.horizon_min}m, q{self.cfg.quantile_bp // 100})"))
        return actions


@dataclass
class RuleBasedRebalancer(_NeedsMixin):
    """Ablation baseline: move surplus from the richest rail to each deficit rail (no optimisation, no queue MILP)."""

    cfg: MPCConfig = field(default_factory=lambda: MPCConfig(enable_queue_milp=False))
    name: str = "rule-rebalancer-v1"

    def propose(self, view) -> list:
        from atlas.sim.day import Action
        actions = []
        if (view.close_at - view.now).total_seconds() / 60 < self.cfg.transfer_cutoff_min:
            return actions
        needs = self.needs(view)
        for inst in sorted(needs):
            rails = [r for r in needs[inst] if view.rail_up.get(r, False)]
            cash = {r: view.accounts[f"{inst}:{r}"].cash_available_minor for r in rails}
            surplus = {r: cash[r] - needs[inst][r] for r in rails}
            for dst in sorted(rails, key=lambda r: surplus[r]):
                if surplus[dst] >= 0:
                    break
                src = max(rails, key=lambda r: (surplus[r], r))
                if src == dst or surplus[src] <= 0:
                    break
                acct = view.accounts[f"{inst}:{src}"]
                amount = min(-surplus[dst], surplus[src], acct.cash_available_minor * self.cfg.share_cap_bp // 10_000)
                queue = view.rtgs_queue if src == "rtgs" else view.lsm_queue if src == "lsm" else ()
                committed = sum(p.amount_minor for p in queue if p.sender_account_id == acct.account_id)
                amount = min(amount, max(0, acct.cash_available_minor - committed))
                if amount >= self.cfg.min_transfer_minor:
                    actions.append(Action("transfer", institution=inst, from_rail=src, to_rail=dst, amount_minor=amount, rationale="greedy surplus move"))
                    surplus[src] -= amount
                    surplus[dst] += amount
        return actions
