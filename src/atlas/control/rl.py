"""Safe reinforcement learning for cross-rail liquidity control (``atlas-safe-ppo-v1``).

Problem. Every ``interval`` minutes each institution decides how much liquidity to
keep on each of its rails. The policy outputs, per bank and rail, a *buffer
multiplier* b in (0, 3): target cash = b x forecast need (the same need forecast
the MPC uses). Cash is then moved from rails above target to rails below target.
Proposals are **not** pre-clipped to the safety controller's per-action limits;
the policy must learn to stay inside them, which is what the constraint measures.

Algorithm. PPO (Schulman et al., 2017, arXiv:1707.06347) with a clipped surrogate,
GAE(lambda) advantages (Schulman et al., 2016) and a parameter-shared Gaussian
policy across banks (a cooperative multi-agent setting with a shared team reward,
in the spirit of MAPPO, Yu et al., 2022). Safety: Lagrangian constrained policy
optimisation (Altman, 1999; Ray, Achiam & Amodei, 2019): the per-step cost signal is
the number of proposals the SafetyController rejected, and the multiplier lambda
is updated by dual ascent towards a target rejection rate. Setting
``constrained=False`` gives plain PPO for ablation. Rejected proposals are never
executed in either variant (the safety filter is always on).

Reward = -(modeled cost accrued during the step): waiting value x delay rate,
newly late or rejected value x penalty, PSR overdraft fee accrual, plus the
unsettled-at-close penalty at the final step. Scaled to O(1).

Pure NumPy, one hidden layer, analytic gradients (checked by finite differences
in tests). Small on purpose: the point is a controlled comparison with MPC, not a
large model.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .mpc import INSTANT, LARGE, MPCConfig, _NeedsMixin

RL_VERSION = "atlas-safe-ppo-v2"
RAILS = ("rtgs", "lsm", "fednow", "rtp")
OBS_DIM = 4 * len(RAILS) + 3
ACT_DIM = len(RAILS) + 1          # per-rail buffer multipliers + transfer aggressiveness (share of source cash per move)
B_MAX = 3.0


# ----------------------------------------------------------------------------- networks
class MLP:
    """tanh MLP with one hidden layer; returns output and a cache for backprop."""

    def __init__(self, n_in: int, n_hidden: int, n_out: int, rng: np.random.Generator, out_scale: float = 0.01) -> None:
        self.W1 = rng.normal(0, 1 / math.sqrt(n_in), (n_in, n_hidden))
        self.b1 = np.zeros(n_hidden)
        self.W2 = rng.normal(0, out_scale / math.sqrt(n_hidden), (n_hidden, n_out))
        self.b2 = np.zeros(n_out)

    def params(self) -> list[np.ndarray]:
        return [self.W1, self.b1, self.W2, self.b2]

    def forward(self, x: np.ndarray):
        h = np.tanh(x @ self.W1 + self.b1)
        return h @ self.W2 + self.b2, (x, h)

    @staticmethod
    def backward(params, cache, d_out: np.ndarray) -> list[np.ndarray]:
        W1, b1, W2, b2 = params
        x, h = cache
        dW2 = h.T @ d_out
        db2 = d_out.sum(0)
        dh = (d_out @ W2.T) * (1 - h * h)
        return [x.T @ dh, dh.sum(0), dW2, db2]


class Adam:
    def __init__(self, params: list[np.ndarray], lr: float) -> None:
        self.p, self.lr, self.t = params, lr, 0
        self.m = [np.zeros_like(x) for x in params]
        self.v = [np.zeros_like(x) for x in params]

    def step(self, grads: list[np.ndarray], max_norm: float = 0.5) -> None:
        norm = math.sqrt(sum(float((g * g).sum()) for g in grads))
        if norm > max_norm:
            grads = [g * (max_norm / norm) for g in grads]
        self.t += 1
        for i, g in enumerate(grads):
            self.m[i] = 0.9 * self.m[i] + 0.1 * g
            self.v[i] = 0.999 * self.v[i] + 0.001 * g * g
            mh = self.m[i] / (1 - 0.9 ** self.t)
            vh = self.v[i] / (1 - 0.999 ** self.t)
            self.p[i] -= self.lr * mh / (np.sqrt(vh) + 1e-8)


@dataclass
class PPOConfig:
    hidden: int = 32
    lr_pi: float = 3e-4
    lr_v: float = 1e-3
    gamma: float = 0.995
    lam: float = 0.95
    clip: float = 0.2
    epochs: int = 6
    minibatch: int = 512
    init_log_std: float = -0.7
    constrained: bool = True
    rejection_target: float = 0.0       # target rejected proposals per control step (summed over banks)
    lambda_lr: float = 0.05
    lambda_init: float = 0.0
    reward_scale_minor: float = 1e8     # $1M of modeled cost = 1 unit of reward
    seed: int = 0


@dataclass
class Policy:
    cfg: PPOConfig
    rng: np.random.Generator = field(init=False)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.cfg.seed)
        self.pi = MLP(OBS_DIM, self.cfg.hidden, ACT_DIM, self.rng)
        self.log_std = np.full(ACT_DIM, self.cfg.init_log_std)
        self.v = MLP(OBS_DIM + 1, self.cfg.hidden, 1, self.rng, out_scale=1.0)
        self.opt_pi = Adam(self.pi.params() + [self.log_std], self.cfg.lr_pi)
        self.opt_v = Adam(self.v.params(), self.cfg.lr_v)
        self.lmbda = self.cfg.lambda_init

    def act(self, obs: np.ndarray, deterministic: bool = False):
        mean, _ = self.pi.forward(obs)
        if deterministic:
            return mean, np.zeros(len(obs))
        z = mean + np.exp(self.log_std) * self.rng.standard_normal(mean.shape)
        return z, self.logp(z, mean)

    def logp(self, z: np.ndarray, mean: np.ndarray) -> np.ndarray:
        std = np.exp(self.log_std)
        return (-0.5 * ((z - mean) / std) ** 2 - self.log_std - 0.5 * math.log(2 * math.pi)).sum(-1)

    def to_dict(self) -> dict:
        return {"version": RL_VERSION, "cfg": self.cfg.__dict__, "pi": [p.tolist() for p in self.pi.params()], "log_std": self.log_std.tolist(),
                "v": [p.tolist() for p in self.v.params()], "lambda": self.lmbda}

    @classmethod
    def from_dict(cls, d: dict) -> Policy:
        pol = cls(PPOConfig(**d["cfg"]))
        for tgt, src in zip(pol.pi.params(), d["pi"]):
            tgt[...] = np.array(src)
        for tgt, src in zip(pol.v.params(), d["v"]):
            tgt[...] = np.array(src)
        pol.log_std[...] = np.array(d["log_std"])
        pol.lmbda = d["lambda"]
        return pol


def buffer_multiplier(z: np.ndarray) -> np.ndarray:
    return B_MAX / (1 + np.exp(-z))


# ----------------------------------------------------------------------------- controller
@dataclass
class RLController(_NeedsMixin):
    """Controller wrapper used both for training rollouts and evaluation."""

    policy: Policy
    deterministic: bool = False
    cfg: MPCConfig = field(default_factory=lambda: MPCConfig(enable_queue_milp=False))
    name: str = RL_VERSION
    min_transfer_minor: int = 50_000_00

    def __post_init__(self) -> None:
        self.traj: list[dict] = []
        self._sim = None
        self._last_cost = 0.0
        self._step_rejections = 0
        self._rej_by_inst: dict[str, int] = {}
        self._insts: list[str] = []

    # simulator hooks
    def attach(self, sim) -> None:
        self._sim = sim
        self._last_cost = self._cost_so_far()

    def on_verdict(self, action, verdict) -> None:
        if not verdict.approved:
            self._step_rejections += 1
            self._rej_by_inst[action.institution] = self._rej_by_inst.get(action.institution, 0) + 1

    def on_close(self, sim) -> None:
        self._close_step(final=True)

    def _cost_so_far(self) -> float:
        """Modeled cost accrued so far, using the simulator's own counters (read-only)."""
        sim = self._sim
        c = sim.settings.cost
        waiting = sim.held_value + sum(v for (_, r), v in sim.queued_by.items() if r in LARGE)
        self._wait_integral = getattr(self, "_wait_integral", 0.0) + waiting * sim.settings.controller_interval_min / 60.0
        delay = self._wait_integral * c.delay_bp_per_hour / 10_000
        rejected = sim.counters["instant_rejected_value_minor"] * c.unsettled_penalty_bp / 10_000
        psr = sim._psr_fee(sim.uncollat_minute_sum)
        return delay + rejected + psr

    def _close_step(self, final: bool = False) -> None:
        if not self.traj or "reward" in self.traj[-1]:
            return
        cost = self._cost_so_far()
        step_cost = cost - self._last_cost
        if final:
            sim = self._sim
            unsettled = sum(m["amount"] for m in sim.meta.values() if m["rail"] in LARGE and m["status"] not in ("settled",))
            step_cost += unsettled * sim.settings.cost.unsettled_penalty_bp / 10_000
        self._last_cost = cost
        self.traj[-1]["reward"] = -step_cost / self.policy.cfg.reward_scale_minor
        self.traj[-1]["cost_c"] = float(self._step_rejections)
        self.traj[-1]["cost_vec"] = np.array([self._rej_by_inst.get(i, 0) for i in self._insts], dtype=float)
        self.traj[-1]["done"] = final

    def _features(self, view, needs) -> tuple[list[str], np.ndarray, np.ndarray]:
        insts = sorted(needs)
        day = max(1.0, (view.close_at - view.now).total_seconds())
        t_left = min(1.0, day / (10.5 * 3600))
        rows = []
        for inst in insts:
            accts = {r: view.accounts.get(f"{inst}:{r}") for r in RAILS}
            scale = max(1, sum(a.cash_available_minor + a.undrawn_credit_minor for a in accts.values() if a is not None))
            f = []
            for r in RAILS:
                a = accts[r]
                if a is None:
                    f += [0.0, 0.0, 0.0, 0.0]
                else:
                    f += [a.cash_available_minor / scale, needs[inst].get(r, 0) / scale, a.undrawn_credit_minor / scale, 1.0]
            rows.append(f + [t_left, 1.0, math.log10(scale) / 12])
        obs = np.array(rows)
        glob = np.concatenate([obs.mean(0), [len(insts) / 100]])
        return insts, obs, glob

    def propose(self, view) -> list:
        from atlas.sim.day import Action
        self._close_step()
        self._step_rejections = 0
        self._rej_by_inst = {}
        if (view.close_at - view.now).total_seconds() / 60 < self.cfg.transfer_cutoff_min:
            return []
        needs = self.needs(view)
        insts, obs, glob = self._features(view, needs)
        self._insts = insts
        z, logp = self.policy.act(obs, self.deterministic)
        b = buffer_multiplier(z[:, :len(RAILS)])
        aggressiveness = 1 / (1 + np.exp(-z[:, len(RAILS)]))
        if not self.deterministic:
            self.traj.append({"obs": obs, "z": z, "logp": logp, "glob": glob})
        actions = []
        for k, inst in enumerate(insts):
            rails = [r for r in RAILS if f"{inst}:{r}" in view.accounts and view.rail_up.get(r, False)]
            if len(rails) < 2:
                continue
            cash = {r: view.accounts[f"{inst}:{r}"].cash_available_minor for r in rails}
            target = {r: int(b[k][RAILS.index(r)] * needs[inst].get(r, 0)) for r in rails}
            surplus = {r: cash[r] - target[r] for r in rails}
            for dst in sorted(rails, key=lambda r: surplus[r]):
                if surplus[dst] >= 0:
                    break
                src = max(rails, key=lambda r: (surplus[r], r))
                if src == dst or surplus[src] <= 0:
                    break
                amount = int(min(-surplus[dst], surplus[src], cash[src], aggressiveness[k] * cash[src]))
                if amount >= self.min_transfer_minor:
                    actions.append(Action("transfer", institution=inst, from_rail=src, to_rail=dst, amount_minor=amount,
                                          rationale=f"learned buffer {dst}={b[k][RAILS.index(dst)]:.2f}x need"))
                    surplus[src] -= amount
                    surplus[dst] += amount
                    cash[src] -= amount
        return actions


# ----------------------------------------------------------------------------- PPO update
def gae(rewards: np.ndarray, values: np.ndarray, gamma: float, lam: float) -> np.ndarray:
    adv = np.zeros_like(rewards)
    last = 0.0
    for t in reversed(range(len(rewards))):
        nxt = values[t + 1] if t + 1 < len(values) else 0.0
        delta = rewards[t] + gamma * nxt - values[t]
        last = delta + gamma * lam * last
        adv[t] = last
    return adv


def ppo_update(policy: Policy, episodes: list[list[dict]]) -> dict:
    cfg = policy.cfg
    obs_l, Z, LP, A, C, G_obs, R_tgt = [], [], [], [], [], [], []
    mean_rej = []
    for traj in episodes:
        steps = [s for s in traj if "reward" in s]
        if not steps:
            continue
        r = np.array([s["reward"] for s in steps])
        cc = np.array([s["cost_c"] for s in steps])
        mean_rej.append(cc.mean())
        glob = np.array([s["glob"] for s in steps])
        vals, _ = policy.v.forward(glob)
        vals = vals[:, 0]
        adv = gae(r, vals, cfg.gamma, cfg.lam)
        ret = adv + vals
        for s, a, rt, g in zip(steps, adv, ret, glob):
            n = len(s["obs"])
            obs_l.append(s["obs"])
            Z.append(s["z"])
            LP.append(s["logp"])
            A.append(np.full(n, a))
            C.append(s.get("cost_vec", np.zeros(n)) if len(s.get("cost_vec", ())) == n else np.zeros(n))
            G_obs.append(g)
            R_tgt.append(rt)
    if not obs_l:
        return {}
    obs_m, Z, LP, A, C = np.concatenate(obs_l), np.concatenate(Z), np.concatenate(LP), np.concatenate(A), np.concatenate(C)
    A = (A - A.mean()) / (A.std() + 1e-8)
    if cfg.constrained:
        # Lagrangian term attributed to the bank whose own proposals were rejected this step (immediate cost).
        A = A - policy.lmbda * C
    G_obs, R_tgt = np.array(G_obs), np.array(R_tgt)
    n = len(obs_m)
    clip_frac = []
    for _ in range(cfg.epochs):
        idx = policy.rng.permutation(n)
        for start in range(0, n, cfg.minibatch):
            mb = idx[start:start + cfg.minibatch]
            mean, cache = policy.pi.forward(obs_m[mb])
            std = np.exp(policy.log_std)
            logp = policy.logp(Z[mb], mean)
            ratio = np.exp(logp - LP[mb])
            adv = A[mb]
            unclipped = ratio * adv
            clipped = np.clip(ratio, 1 - cfg.clip, 1 + cfg.clip) * adv
            active = (unclipped <= clipped).astype(float)          # gradient flows only through the unclipped branch when it is the min
            clip_frac.append(1 - active.mean())
            # d(-L)/d logp = -adv*ratio*active / m
            dlogp = -(adv * ratio * active) / len(mb)
            d_mean = (dlogp[:, None] * (Z[mb] - mean) / std ** 2)
            d_logstd = (dlogp[:, None] * (((Z[mb] - mean) / std) ** 2 - 1)).sum(0)
            grads = MLP.backward(policy.pi.params(), cache, d_mean) + [d_logstd - 0.0]
            policy.opt_pi.step(grads)
            np.clip(policy.log_std, -2.5, 0.5, out=policy.log_std)
        for start in range(0, len(G_obs), 256):
            mb = slice(start, start + 256)
            v, cache = policy.v.forward(G_obs[mb])
            d = 2 * (v[:, 0] - R_tgt[mb])[:, None] / len(v)
            policy.opt_v.step(MLP.backward(policy.v.params(), cache, d), max_norm=5.0)
    rej = float(np.mean(mean_rej)) if mean_rej else 0.0
    if cfg.constrained:
        policy.lmbda = max(0.0, policy.lmbda + cfg.lambda_lr * (rej - cfg.rejection_target))
    return {"samples": int(n), "mean_rejections_per_step": rej, "lambda": policy.lmbda, "clip_frac": float(np.mean(clip_frac))}


def save_policy(policy: Policy, path: str | Path) -> None:
    Path(path).write_text(json.dumps(policy.to_dict()))


def load_policy(path: str | Path) -> Policy:
    return Policy.from_dict(json.loads(Path(path).read_text()))


__all__ = ["RL_VERSION", "MLP", "PPOConfig", "Policy", "RLController", "gae", "load_policy", "ppo_update", "save_policy", "INSTANT"]
