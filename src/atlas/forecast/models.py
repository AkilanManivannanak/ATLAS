"""Net-outflow forecasting for each institution and intraday bucket.

Target. Large-value net outflow (outgoing minus incoming instruction value) of an
institution in a 15-minute bucket, h buckets ahead of the forecast origin. It is
an exogenous demand process in the simulator (independent of settlement policy),
which keeps the forecasting experiment free of policy leakage.

Splits. Entire simulated *days* are assigned to train / validation / test
(blueprint section 23): no bucket from a test day is ever seen in training.
An out-of-distribution test set uses days generated under a shifted config.

Uncertainty. Every model produces a point forecast plus quantiles from split
conformal prediction on the validation days (Vovk et al., 2005; Lei et al., 2018,
JASA 113(523)): signed validation residuals give the quantile offsets, and the
symmetric absolute-residual quantile gives a (1-a) interval with finite-sample
marginal coverage under exchangeability of days. Coverage is *measured* on test
days, never assumed.

Metrics: MAE, RMSE, MASE (scaled by the in-sample seasonal-naive MAE, Hyndman &
Koehler, 2006), mean pinball loss, CRPS approximated by the quantile-grid
estimator 2 * mean pinball, empirical interval coverage and mean width.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

import numpy as np

from atlas.scenario import NexusPayConfig, generate_scenario

FORECAST_VERSION = "atlas-forecast-v2"
BUCKET_MIN = 15
QUANTILES = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
HORIZONS = {"15m": 1, "30m": 2, "1h": 4, "4h": 16}


def build_panel(config: NexusPayConfig, day_seeds: Sequence[int], topology_seed: int, target: str = "net_outflow") -> dict:
    """Return {'institutions', 'tiers', 'days': array [D, N, B]} in *major units* (float, analytics only).

    ``target``: ``net_outflow`` (sent - received) or ``gross_outflow`` (sent only, the liquidity a bank must find).
    """
    if target not in ("net_outflow", "gross_outflow"):
        raise ValueError("target must be net_outflow or gross_outflow")
    days = []
    insts: list[str] | None = None
    tiers: dict[str, str] = {}
    for k, seed in enumerate(day_seeds):
        cfg = replace(config, business_date=config.business_date + timedelta(days=7 * k))
        sc = generate_scenario(cfg, seed=seed, topology_seed=topology_seed)
        if insts is None:
            insts = [i.institution_id for i in sc.institutions]
            tiers = {i.institution_id: i.tier for i in sc.institutions}
        n_b = int((sc.close_at - sc.open_at).total_seconds() // (BUCKET_MIN * 60)) + 1
        grid = np.zeros((len(insts), n_b))
        idx = {i: j for j, i in enumerate(insts)}
        for p in sc.payments:
            if p.rail not in ("rtgs", "lsm"):
                continue
            b = int((p.arrival_at - sc.open_at).total_seconds() // (BUCKET_MIN * 60))
            grid[idx[p.sender], b] += p.amount_minor / 100.0
            if target == "net_outflow":
                grid[idx[p.receiver], b] -= p.amount_minor / 100.0
        days.append(grid)
    return {"institutions": insts, "tiers": tiers, "days": np.stack(days), "target": target}


def _features(day: np.ndarray, inst: int, origin: int, h: int, tier_core: float, scale: float,
              neighbours: Sequence[tuple[int, float]] | None = None, scales: dict | None = None) -> list[float]:
    target_b = origin + h
    n_b = day.shape[1]
    lag = lambda k: day[inst, origin - k] / scale if origin - k >= 0 else 0.0
    cum = day[inst, : origin + 1].sum() / scale
    tod = 2 * math.pi * target_b / n_b
    sys_lag = lambda k: day[:, origin - k].sum() / (scale * day.shape[0]) if origin - k >= 0 else 0.0
    roll4 = sum(lag(k) for k in range(4)) / 4
    feats = [1.0, math.sin(tod), math.cos(tod), math.sin(2 * tod), math.cos(2 * tod), tier_core, lag(0), lag(1), lag(2), lag(3),
             lag(4), lag(5), lag(6), lag(7), roll4, cum, sys_lag(0), sys_lag(1), sys_lag(2), h / 16.0, (origin + 1) / n_b]
    if neighbours is not None:
        # graph-conditioned: recent activity of the institutions most correlated with this one on training days
        nb = sum(w * (day[j, origin] + (day[j, origin - 1] if origin >= 1 else 0.0)) / (2 * scales[j]) for j, w in neighbours)
        feats.append(nb)
    return feats


def _samples(panel: dict, day_idx: Sequence[int], h: int, scale: dict[int, float], graph: dict | None = None) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int, int]]]:
    X, y, keys = [], [], []
    days = panel["days"]
    for d in day_idx:
        for i, inst in enumerate(panel["institutions"]):
            core = 1.0 if panel["tiers"][inst] == "core" else 0.0
            nb = graph.get(i, []) if graph is not None else None
            for origin in range(0, days.shape[2] - h):
                X.append(_features(days[d], i, origin, h, core, scale[i], nb, scale))
                y.append(days[d, i, origin + h] / scale[i])
                keys.append((d, i, origin + h))
    return np.array(X), np.array(y), keys


class _Base:
    name = "base"

    def fit(self, panel: dict, train: Sequence[int], h: int) -> None: ...

    def predict(self, panel: dict, day_idx: Sequence[int], h: int) -> tuple[np.ndarray, list]: ...


class HistoricalMeanForecaster(_Base):
    """Mean of the same institution and bucket across training days."""

    name = "historical_mean"

    def fit(self, panel, train, h):
        self.mean = panel["days"][list(train)].mean(axis=0)

    def predict(self, panel, day_idx, h):
        keys, out = [], []
        for d in day_idx:
            for i in range(len(panel["institutions"])):
                for b in range(h, panel["days"].shape[2]):
                    keys.append((d, i, b))
                    out.append(self.mean[i, b])
        return np.array(out), keys


class SeasonalNaiveForecaster(_Base):
    """Same bucket on the most recent training day (the MASE reference)."""

    name = "seasonal_naive"

    def fit(self, panel, train, h):
        self.last = panel["days"][list(train)[-1]]

    def predict(self, panel, day_idx, h):
        keys, out = [], []
        for d in day_idx:
            for i in range(len(panel["institutions"])):
                for b in range(h, panel["days"].shape[2]):
                    keys.append((d, i, b))
                    out.append(self.last[i, b])
        return np.array(out), keys


class RidgeForecaster(_Base):
    """Closed-form ridge regression on time-of-day, tier, intraday lags and cumulative flow."""

    name = "ridge"

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha

    def fit(self, panel, train, h):
        self.scale = {i: max(1.0, np.abs(panel["days"][list(train), i]).mean()) for i in range(len(panel["institutions"]))}
        X, y, _ = _samples(panel, train, h, self.scale)
        reg = self.alpha * np.eye(X.shape[1])
        reg[0, 0] = 0.0
        self.w = np.linalg.solve(X.T @ X + reg, X.T @ y)

    def predict(self, panel, day_idx, h):
        X, _, keys = _samples(panel, day_idx, h, self.scale)
        pred = X @ self.w
        return np.array([pred[k] * self.scale[key[1]] for k, key in enumerate(keys)]), keys


class GradientBoostingForecaster(_Base):
    """Histogram gradient boosting (scikit-learn), the LightGBM-style baseline."""

    name = "gradient_boosting"

    def __init__(self, max_iter: int = 200, seed: int = 0) -> None:
        self.max_iter = max_iter
        self.seed = seed

    def fit(self, panel, train, h):
        from sklearn.ensemble import HistGradientBoostingRegressor
        self.scale = {i: max(1.0, np.abs(panel["days"][list(train), i]).mean()) for i in range(len(panel["institutions"]))}
        X, y, _ = _samples(panel, train, h, self.scale)
        self.model = HistGradientBoostingRegressor(max_iter=self.max_iter, learning_rate=0.05, random_state=self.seed).fit(X, y)

    def predict(self, panel, day_idx, h):
        X, _, keys = _samples(panel, day_idx, h, self.scale)
        pred = self.model.predict(X)
        return np.array([pred[k] * self.scale[key[1]] for k, key in enumerate(keys)]), keys


def learn_graph(panel: dict, train: Sequence[int], k: int = 3) -> dict[int, list[tuple[int, float]]]:
    """Top-k positively correlated institutions on training days (a learned dependency graph)."""
    d = panel["days"][list(train)]
    series = d.transpose(1, 0, 2).reshape(d.shape[1], -1)
    c = np.corrcoef(series)
    out = {}
    for i in range(len(c)):
        cand = sorted(((c[i, j], j) for j in range(len(c)) if j != i and np.isfinite(c[i, j]) and c[i, j] > 0), reverse=True)[:k]
        tot = sum(w for w, _ in cand)
        out[i] = [(j, w / tot) for w, j in cand] if tot > 0 else []
    return out


class GraphRidgeForecaster(RidgeForecaster):
    """Ridge with a graph-conditioned feature from a dependency graph learned on training days."""

    name = "graph_ridge"

    def fit(self, panel, train, h):
        self.graph = learn_graph(panel, train)
        self.scale = {i: max(1.0, np.abs(panel["days"][list(train), i]).mean()) for i in range(len(panel["institutions"]))}
        X, y, _ = _samples(panel, train, h, self.scale, self.graph)
        reg = self.alpha * np.eye(X.shape[1])
        reg[0, 0] = 0.0
        self.w = np.linalg.solve(X.T @ X + reg, X.T @ y)

    def predict(self, panel, day_idx, h):
        X, _, keys = _samples(panel, day_idx, h, self.scale, self.graph)
        pred = X @ self.w
        return np.array([pred[k] * self.scale[key[1]] for k, key in enumerate(keys)]), keys


class NeuralWindowForecaster(_Base):
    """Feed-forward neural network (scikit-learn MLPRegressor) on the lag window and calendar features.

    A neural sequence baseline that runs without a deep-learning framework. It is *not* an LSTM or TFT.
    """

    name = "neural_window"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def fit(self, panel, train, h):
        from sklearn.neural_network import MLPRegressor
        self.scale = {i: max(1.0, np.abs(panel["days"][list(train), i]).mean()) for i in range(len(panel["institutions"]))}
        X, y, _ = _samples(panel, train, h, self.scale)
        self.model = MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1e-3, learning_rate_init=1e-3, max_iter=300, early_stopping=True,
                                  random_state=self.seed).fit(X, y)

    def predict(self, panel, day_idx, h):
        X, _, keys = _samples(panel, day_idx, h, self.scale)
        pred = self.model.predict(X)
        return np.array([pred[k] * self.scale[key[1]] for k, key in enumerate(keys)]), keys


def adaptive_interval_coverage(y: np.ndarray, pred: np.ndarray, keys: list, h: int, w0: float, alpha: float = 0.1,
                               eta: float = 0.05) -> tuple[float, float]:
    """Online quantile tracking of the interval half-width (Angelopoulos, Candes & Tibshirani, 2023; cf. Gibbs & Candes, 2021).

    Causal: the half-width used for a forecast of bucket b is updated only with outcomes of buckets <= b - h
    (the information available at the forecast origin). Returns (coverage, mean width).
    """
    order = sorted(range(len(keys)), key=lambda k: (keys[k][0], keys[k][2], keys[k][1]))
    log_w = math.log(max(w0, 1e-9))
    pending: list[tuple[int, int, bool]] = []    # (day, bucket, covered)
    cov, widths = [], []
    cur_day = None
    for k in order:
        d, _, b = keys[k]
        if d != cur_day:
            for _, _, c in pending:
                log_w += eta * ((0.0 if c else 1.0) - alpha)
            pending, cur_day = [], d
        ready = [x for x in pending if x[1] <= b - h]
        pending = [x for x in pending if x[1] > b - h]
        for _, _, c in ready:
            log_w += eta * ((0.0 if c else 1.0) - alpha)
        w = math.exp(log_w)
        covered = abs(y[k] - pred[k]) <= w
        cov.append(covered)
        widths.append(2 * w)
        pending.append((d, b, covered))
    return float(np.mean(cov)), float(np.mean(widths))


def _truth(panel: dict, keys: list) -> np.ndarray:
    return np.array([panel["days"][d, i, b] for d, i, b in keys])


def _pinball(y: np.ndarray, q_pred: np.ndarray, q: float) -> float:
    diff = y - q_pred
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def evaluate(model: _Base, panel: dict, train: Sequence[int], val: Sequence[int], test: Sequence[int], h: int, *, mase_scale: float,
             interval_bp: int = 9_000) -> dict:
    model.fit(panel, train, h)
    val_pred, val_keys = model.predict(panel, val, h)
    resid = _truth(panel, val_keys) - val_pred
    offsets = {q: float(np.quantile(resid, q)) for q in QUANTILES}
    a = 1 - interval_bp / 10_000
    n = len(resid)
    level = min(1.0, math.ceil((n + 1) * (1 - a)) / n)
    half = float(np.quantile(np.abs(resid), level))
    pred, keys = model.predict(panel, test, h)
    y = _truth(panel, keys)
    err = y - pred
    pinballs = {q: _pinball(y, pred + offsets[q], q) for q in QUANTILES}
    covered = np.mean((y >= pred - half) & (y <= pred + half))
    aci_cov, aci_width = adaptive_interval_coverage(y, pred, keys, h, half, alpha=a)
    return {
        "adaptive_interval_coverage": aci_cov, "adaptive_interval_mean_width": aci_width,
        "model": model.name, "horizon_buckets": h, "n_test": int(len(y)),
        "mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mase": float(np.mean(np.abs(err)) / mase_scale) if mase_scale > 0 else None,
        "pinball_mean": float(np.mean(list(pinballs.values()))), "crps_approx": 2 * float(np.mean(list(pinballs.values()))),
        "interval_nominal": interval_bp / 10_000, "interval_coverage": float(covered), "interval_mean_width": 2 * half,
        "calibration_error": abs(float(covered) - interval_bp / 10_000),
    }


def run_forecast_experiment(
    config: NexusPayConfig = NexusPayConfig(n_institutions=12, payments_per_day=2_000, instant_payments_per_day=0),
    *,
    topology_seed: int = 2026,
    train_seeds: Sequence[int] = tuple(range(1000, 1012)),
    val_seeds: Sequence[int] = tuple(range(2000, 2004)),
    test_seeds: Sequence[int] = tuple(range(3000, 3004)),
    ood_config: NexusPayConfig | None = None,
    horizons: dict[str, int] = HORIZONS,
    include_gbm: bool = True,
    include_neural: bool = True,
    target: str = "net_outflow",
) -> dict:
    seeds = list(train_seeds) + list(val_seeds) + list(test_seeds)
    panel = build_panel(config, seeds, topology_seed, target)
    tr = list(range(len(train_seeds)))
    va = list(range(len(train_seeds), len(train_seeds) + len(val_seeds)))
    te = list(range(len(train_seeds) + len(val_seeds), len(seeds)))
    days = panel["days"][tr]
    mase_scale = float(np.mean(np.abs(days[1:] - days[:-1]))) if len(tr) > 1 else 1.0
    models = ([HistoricalMeanForecaster, SeasonalNaiveForecaster, RidgeForecaster, GraphRidgeForecaster]
              + ([GradientBoostingForecaster] if include_gbm else []) + ([NeuralWindowForecaster] if include_neural else []))
    results = []
    for label, h in horizons.items():
        for cls in models:
            r = evaluate(cls(), panel, tr, va, te, h, mase_scale=mase_scale)
            r["horizon"] = label
            r["split"] = "test_in_distribution"
            results.append(r)
    ood = []
    if ood_config is not None:
        ood_panel = build_panel(ood_config, list(train_seeds) + list(val_seeds) + list(test_seeds), topology_seed, target)
        # train/val on in-distribution days, test on shifted-config days
        merged = {"institutions": panel["institutions"], "tiers": panel["tiers"],
                  "days": np.concatenate([panel["days"][tr + va], ood_panel["days"][te]])}
        te2 = list(range(len(tr) + len(va), len(tr) + len(va) + len(te)))
        for label, h in horizons.items():
            for cls in models:
                r = evaluate(cls(), merged, tr, va, te2, h, mase_scale=mase_scale)
                r["horizon"] = label
                r["split"] = "test_out_of_distribution"
                ood.append(r)
    return {
        "version": FORECAST_VERSION, "target": f"large-value {target.replace('_', ' ')} per institution per 15-minute bucket (major units)",
        "splits": {"train_days": list(train_seeds), "val_days": list(val_seeds), "test_days": list(test_seeds), "unit": "whole simulated day"},
        "topology_seed": topology_seed, "config": config.to_dict(), "results": results + ood,
        "uncertainty_method": "split conformal (validation-day residuals) and causal online quantile tracking (adaptive)",
    }
