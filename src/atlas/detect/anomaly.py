"""Payment anomaly detection (``atlas-detect-v1``).

A bank learns what "normal" looks like for every sender and corridor from past days, then scores each new payment
before release. Three detectors are compared on the same features:

* ``robust_z``   no training: the largest robust z-score among the behavioural features (the rule a payments
                 operations team would write by hand)
* ``iforest``    unsupervised isolation forest fitted on clean history
* ``gbt``        supervised gradient boosting, trained on labelled past incidents

**Labels are synthetic.** No real fraud data exists in this repository, so anomalies are *injected* using six
typologies (see ``TYPOLOGIES``). To avoid grading a model on patterns it has memorised, the supervised model is
also evaluated leave-one-typology-out: trained without ever seeing the typology it is then tested on.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from atlas.scenario import NexusPayConfig, generate_scenario

DETECT_VERSION = "atlas-detect-v1"
INSTANT = ("fednow", "rtp")
TYPOLOGIES = {
    "amount_spike": "known corridor, amount 8-30x the corridor's usual size",
    "new_corridor": "first-ever payment between two banks, well above the sender's usual size",
    "off_hours_burst": "6-12 instant payments inside two minutes in the sender's quietest half hour",
    "structuring": "4-8 instant payments at 95-99.9% of the network limit to one receiver",
    "fan_in": "many different senders paying one small receiver within twenty minutes (mule-account pattern)",
    "duplicate": "the same payment submitted twice within a minute (operational error)",
}
FEATURES = ("log_amount", "corridor_z", "sender_z", "corridor_novelty", "time_surprise", "sender_burst_5m", "sender_value_5m",
            "receiver_fan_in_30m", "limit_proximity", "repeat_60s", "is_instant")


@dataclass
class Row:
    payment_id: str
    rail: str
    sender: str
    receiver: str
    amount_minor: int
    at: datetime
    label: int = 0
    typology: str = ""


def rows_from_scenario(scenario) -> list[Row]:
    return [Row(p.payment_id, p.rail, p.sender, p.receiver, p.amount_minor, p.arrival_at) for p in scenario.payments]


def rows_from_dicts(payments: Sequence[dict]) -> list[Row]:
    return [Row(p["payment_id"], p["rail"], p["sender"], p["receiver"], p["amount_minor"], datetime.fromisoformat(p["arrival"])) for p in payments]


def _robust(xs: list[float]) -> tuple[float, float]:
    xs = sorted(xs)
    med = xs[len(xs) // 2]
    mad = sorted(abs(x - med) for x in xs)[len(xs) // 2]
    return med, max(1.4826 * mad, 0.25)


@dataclass
class CorridorProfile:
    """What past days say about each sender, corridor and receiver."""

    corridor: dict = field(default_factory=dict)      # (s, r, class) -> (median log amt, scale, count)
    sender: dict = field(default_factory=dict)        # (s, class) -> (median, scale, count)
    tod: dict = field(default_factory=dict)           # (s, class) -> [prob per half-hour bucket]
    burst_p99: dict = field(default_factory=dict)     # (s, class) -> 99th pct of 5-minute payment count
    value_p99: dict = field(default_factory=dict)     # (s, class) -> 99th pct of 5-minute value
    fan_in_p99: dict = field(default_factory=dict)    # receiver -> 99th pct of distinct instant senders per 30 min
    days: int = 0
    n_buckets: int = 21

    @staticmethod
    def _cls(rail: str) -> str:
        return "instant" if rail in INSTANT else "lv"

    @classmethod
    def fit(cls, days: Sequence[Sequence[Row]], open_ats: Sequence[datetime], day_minutes: int = 630) -> CorridorProfile:
        prof = cls(days=len(days), n_buckets=max(1, day_minutes // 30))
        cor: dict = {}
        snd: dict = {}
        tod: dict = {}
        bursts: dict = {}
        values: dict = {}
        fans: dict = {}
        for rows, open_at in zip(days, open_ats):
            per_sender: dict = {}
            per_recv: dict = {}
            for r in rows:
                c = cls._cls(r.rail)
                la = math.log(r.amount_minor)
                cor.setdefault((r.sender, r.receiver, c), []).append(la)
                snd.setdefault((r.sender, c), []).append(la)
                b = min(prof.n_buckets - 1, max(0, int((r.at - open_at).total_seconds() // 1800)))
                tod.setdefault((r.sender, c), [0] * prof.n_buckets)[b] += 1
                per_sender.setdefault((r.sender, c), []).append((r.at, r.amount_minor))
                if c == "instant":
                    per_recv.setdefault(r.receiver, []).append((r.at, r.sender))
            for key, evs in per_sender.items():
                evs.sort()
                ts = [e[0] for e in evs]
                for i, (at, _) in enumerate(evs):
                    j = bisect_left(ts, at - timedelta(minutes=5))
                    bursts.setdefault(key, []).append(i - j + 1)
                    values.setdefault(key, []).append(sum(e[1] for e in evs[j:i + 1]))
            for recv, evs in per_recv.items():
                evs.sort()
                ts = [e[0] for e in evs]
                for i, (at, _) in enumerate(evs):
                    j = bisect_left(ts, at - timedelta(minutes=30))
                    fans.setdefault(recv, []).append(len({e[1] for e in evs[j:i + 1]}))
        prof.corridor = {k: (*_robust(v), len(v)) for k, v in cor.items()}
        prof.sender = {k: (*_robust(v), len(v)) for k, v in snd.items()}
        prof.tod = {k: [(x + 0.5) / (sum(v) + 0.5 * len(v)) for x in v] for k, v in tod.items()}
        q = lambda xs: sorted(xs)[min(len(xs) - 1, int(0.99 * len(xs)))]
        prof.burst_p99 = {k: q(v) for k, v in bursts.items()}
        prof.value_p99 = {k: q(v) for k, v in values.items()}
        prof.fan_in_p99 = {k: q(v) for k, v in fans.items()}
        return prof


def featurize(rows: Sequence[Row], profile: CorridorProfile, open_at: datetime, limits: dict[str, int] | None = None) -> np.ndarray:
    """One feature vector per payment, using only that day's payments up to and including it (causal)."""
    limits = limits or {"fednow": 10_000_000_00, "rtp": 10_000_000_00}
    order = sorted(range(len(rows)), key=lambda i: (rows[i].at, rows[i].payment_id))
    by_sender: dict = {}
    by_recv: dict = {}
    by_corr: dict = {}
    X = np.zeros((len(rows), len(FEATURES)))
    for i in order:
        r = rows[i]
        c = CorridorProfile._cls(r.rail)
        la = math.log(r.amount_minor)
        sm, ss, _ = profile.sender.get((r.sender, c), (la, 1.5, 0))
        cm, cs, cn = profile.corridor.get((r.sender, r.receiver, c), (sm, max(ss, 1.0), 0))
        b = min(profile.n_buckets - 1, max(0, int((r.at - open_at).total_seconds() // 1800)))
        p_tod = profile.tod.get((r.sender, c), [1.0 / profile.n_buckets] * profile.n_buckets)[b]
        s_ev = by_sender.setdefault((r.sender, c), ([], []))
        s_ev[0].append(r.at)
        s_ev[1].append(r.amount_minor)
        j = bisect_left(s_ev[0], r.at - timedelta(minutes=5))
        burst, value = len(s_ev[0]) - j, sum(s_ev[1][j:])
        fan = 0
        if c == "instant":
            r_ev = by_recv.setdefault(r.receiver, ([], []))
            r_ev[0].append(r.at)
            r_ev[1].append(r.sender)
            k = bisect_left(r_ev[0], r.at - timedelta(minutes=30))
            fan = len(set(r_ev[1][k:]))
        c_ev = by_corr.setdefault((r.sender, r.receiver, r.amount_minor), [])
        repeat = len(c_ev) - bisect_right(c_ev, r.at - timedelta(seconds=60))
        c_ev.append(r.at)
        lim = limits.get(r.rail)
        X[i] = (la, (la - cm) / cs, (la - sm) / ss, 1.0 / (1.0 + cn), -math.log(p_tod * profile.n_buckets),
                burst / max(1, profile.burst_p99.get((r.sender, c), 3)), value / max(1, profile.value_p99.get((r.sender, c), r.amount_minor)),
                fan / max(1, profile.fan_in_p99.get(r.receiver, 2)), (r.amount_minor / lim) if lim else 0.0, float(repeat),
                1.0 if c == "instant" else 0.0)
    return X


def inject_anomalies(rows: Sequence[Row], profile: CorridorProfile, open_at: datetime, close_at: datetime, seed: int,
                     incidents_per_type: int = 3, types: Sequence[str] = tuple(TYPOLOGIES)) -> list[Row]:
    """Return a new list: the day's real rows plus labelled injected incidents."""
    rng = random.Random(seed)
    out = [Row(r.payment_id, r.rail, r.sender, r.receiver, r.amount_minor, r.at) for r in rows]
    senders = sorted({r.sender for r in rows})
    seconds = int((close_at - open_at).total_seconds())
    inst_rows = [r for r in rows if r.rail in INSTANT]
    lv_rows = [r for r in rows if r.rail not in INSTANT]
    n = 0

    def add(rail, s, r, amt, at, typ):
        nonlocal n
        n += 1
        out.append(Row(f"inj-{seed}-{n:04d}", rail, s, r, max(1, int(amt)), at, 1, typ))

    rand_at = lambda: open_at + timedelta(seconds=rng.randrange(600, max(601, seconds - 600)))
    for typ in types:
        for _ in range(incidents_per_type):
            if typ == "amount_spike":
                base = rng.choice(lv_rows or rows)
                med = math.exp(profile.corridor.get((base.sender, base.receiver, CorridorProfile._cls(base.rail)), (math.log(base.amount_minor), 1, 0))[0])
                add(base.rail, base.sender, base.receiver, med * rng.uniform(8, 30), rand_at(), typ)
            elif typ == "new_corridor":
                for _try in range(200):
                    s, r = rng.sample(senders, 2)
                    rail = rng.choice(("rtgs", "fednow"))
                    c = CorridorProfile._cls(rail)
                    if (s, r, c) not in profile.corridor and (s, c) in profile.sender:
                        break
                med = math.exp(profile.sender.get((s, c), (math.log(1_000_000_00), 1, 0))[0])
                lim = 10_000_000_00 if c == "instant" else None
                amt = med * rng.uniform(3, 10)
                add(rail, s, r, min(amt, lim * 0.9) if lim else amt, rand_at(), typ)
            elif typ == "off_hours_burst":
                base = rng.choice(inst_rows or rows)
                c = "instant"
                tod = profile.tod.get((base.sender, c))
                b = min(range(len(tod)), key=lambda i: tod[i]) if tod else 0
                t0 = open_at + timedelta(seconds=b * 1800 + rng.randrange(0, 1500))
                med = math.exp(profile.sender.get((base.sender, c), (math.log(base.amount_minor), 1, 0))[0])
                for _k in range(rng.randrange(6, 13)):
                    add(base.rail, base.sender, rng.choice([x for x in senders if x != base.sender]), med * rng.uniform(0.6, 1.8),
                        t0 + timedelta(seconds=rng.randrange(0, 120)), typ)
            elif typ == "structuring":
                base = rng.choice(inst_rows or rows)
                t0 = rand_at()
                for k in range(rng.randrange(4, 9)):
                    add(base.rail, base.sender, base.receiver, 10_000_000_00 * rng.uniform(0.95, 0.999), t0 + timedelta(seconds=k * rng.randrange(20, 240)), typ)
            elif typ == "fan_in":
                vol: dict = {}
                for r in inst_rows:
                    vol[r.receiver] = vol.get(r.receiver, 0) + 1
                target = min(vol, key=lambda k: (vol[k], k)) if vol else rng.choice(senders)
                t0 = rand_at()
                srcs = rng.sample([x for x in senders if x != target], min(len(senders) - 1, rng.randrange(6, 11)))
                for s in srcs:
                    med = math.exp(profile.sender.get((s, "instant"), (math.log(15_000_00), 1, 0))[0])
                    add("fednow", s, target, med * rng.uniform(0.8, 2.5), t0 + timedelta(seconds=rng.randrange(0, 1200)), typ)
            elif typ == "duplicate":
                base = rng.choice(rows)
                add(base.rail, base.sender, base.receiver, base.amount_minor, base.at + timedelta(seconds=rng.randrange(2, 45)), typ)
    out.sort(key=lambda r: (r.at, r.payment_id))
    return out


def _robust_z_score(X: np.ndarray) -> np.ndarray:
    f = {n: i for i, n in enumerate(FEATURES)}
    parts = np.stack([np.abs(X[:, f["corridor_z"]]) / 2.5, X[:, f["corridor_novelty"]] * np.clip(X[:, f["sender_z"]], 0, None),
                      X[:, f["sender_burst_5m"]], X[:, f["receiver_fan_in_30m"]],
                      np.where(X[:, f["limit_proximity"]] > 0.9, 3.0, 0.0), X[:, f["repeat_60s"]] * 3.0], axis=1)
    return parts.max(axis=1)


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(-score, kind="stable")
    y = y[order]
    tp = np.cumsum(y)
    precision = tp / np.arange(1, len(y) + 1)
    return float((precision * y).sum() / max(1, y.sum()))


def _metrics(y: np.ndarray, score: np.ndarray, typ: np.ndarray, alert_rate: float = 0.005) -> dict:
    k = max(1, int(round(alert_rate * len(y))))
    top = np.argsort(-score, kind="stable")[:k]
    flagged = np.zeros(len(y), bool)
    flagged[top] = True
    out = {"pr_auc": round(average_precision(y, score), 4), "alert_rate": alert_rate, "alerts": int(k),
           "recall_at_alert_rate": round(float(y[flagged].sum() / max(1, y.sum())), 4),
           "precision_at_alert_rate": round(float(y[flagged].mean()), 4), "base_rate": round(float(y.mean()), 5), "by_typology": {}}
    for t in sorted({str(x) for x in typ[y == 1]}):
        m = (typ == t) & (y == 1)
        out["by_typology"][t] = {"n": int(m.sum()), "recall_at_alert_rate": round(float(flagged[m].mean()), 4)}
    order = np.argsort(-score, kind="stable")
    tp = np.cumsum(y[order])
    pts = sorted({min(len(y) - 1, int(round(f * len(y)))) for f in (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1)})
    out["curve"] = [{"alert_rate": round((i + 1) / len(y), 5), "recall": round(float(tp[i] / max(1, y.sum())), 4),
                     "precision": round(float(tp[i] / (i + 1)), 4)} for i in pts]
    return out


def _panel(config: NexusPayConfig, seeds: Sequence[int], topology_seed: int):
    days, opens, closes = [], [], []
    for s in seeds:
        sc = generate_scenario(config, seed=s, topology_seed=topology_seed)
        days.append(rows_from_scenario(sc))
        opens.append(sc.open_at)
        closes.append(sc.close_at)
    return days, opens, closes


def run_detection_experiment(config: NexusPayConfig = NexusPayConfig(), *, history_seeds: Sequence[int] = tuple(range(300, 312)),
                             train_seeds: Sequence[int] = tuple(range(312, 320)), test_seeds: Sequence[int] = tuple(range(320, 326)),
                             topology_seed: int = 2026, incidents_per_type: int = 1, alert_rate: float = 0.01) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest

    hist, h_open, _ = _panel(config, history_seeds, topology_seed)
    profile = CorridorProfile.fit(hist, h_open)

    def build(seeds, types=tuple(TYPOLOGIES)):
        Xs, ys, ts = [], [], []
        days, opens, closes = _panel(config, seeds, topology_seed)
        for rows, o, c, s in zip(days, opens, closes, seeds):
            mixed = inject_anomalies(rows, profile, o, c, seed=10_000 + s, incidents_per_type=incidents_per_type, types=types)
            Xs.append(featurize(mixed, profile, o))
            ys.append(np.array([r.label for r in mixed]))
            ts.append(np.array([r.typology for r in mixed]))
        return np.vstack(Xs), np.concatenate(ys), np.concatenate(ts)

    X_clean = np.vstack([featurize(rows, profile, o) for rows, o in zip(hist[-4:], h_open[-4:])])
    X_tr, y_tr, t_tr = build(train_seeds)
    X_te, y_te, t_te = build(test_seeds)

    results = {"robust_z": _metrics(y_te, _robust_z_score(X_te), t_te, alert_rate)}
    iso = IsolationForest(n_estimators=200, random_state=0, contamination="auto").fit(X_clean)
    results["iforest"] = _metrics(y_te, -iso.score_samples(X_te), t_te, alert_rate)
    gbt = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_leaf_nodes=15, class_weight="balanced", random_state=0).fit(X_tr, y_tr)
    results["gbt"] = _metrics(y_te, gbt.predict_proba(X_te)[:, 1], t_te, alert_rate)

    # Explainability and robustness for the supervised model (what a model validator asks first).
    from sklearn.inspection import permutation_importance
    imp = permutation_importance(gbt, X_te, y_te, scoring="average_precision", n_repeats=5, random_state=0)
    importance = sorted(({"feature": f, "drop_in_pr_auc": round(float(m), 4), "sd": round(float(sd), 4)}
                         for f, m, sd in zip(FEATURES, imp.importances_mean, imp.importances_std)), key=lambda r: -r["drop_in_pr_auc"])
    rng = np.random.default_rng(0)
    robustness = []
    for noise in (0.0, 0.05, 0.1, 0.2):
        Xn = X_te * (1 + rng.normal(0, noise, X_te.shape)) if noise else X_te
        robustness.append({"feature_noise_sd": noise, "pr_auc": round(average_precision(y_te, gbt.predict_proba(Xn)[:, 1]), 4)})

    loto = {}
    for held in TYPOLOGIES:
        keep = (t_tr != held)
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_leaf_nodes=15, class_weight="balanced", random_state=0).fit(X_tr[keep], y_tr[keep])
        score = m.predict_proba(X_te)[:, 1]
        mask = (y_te == 0) | (t_te == held)
        k = max(1, int(round(alert_rate * mask.sum())))
        top = np.argsort(-score[mask], kind="stable")[:k]
        yy = y_te[mask]
        loto[held] = {"n": int(yy.sum()), "gbt_unseen_recall": round(float(yy[top].sum() / max(1, yy.sum())), 4),
                      "iforest_recall": results["iforest"]["by_typology"].get(held, {}).get("recall_at_alert_rate"),
                      "robust_z_recall": results["robust_z"]["by_typology"].get(held, {}).get("recall_at_alert_rate")}
    return {
        "version": DETECT_VERSION, "data_origin": "synthetic", "labels": "injected anomalies (six typologies); not observed fraud",
        "features": list(FEATURES), "typologies": TYPOLOGIES,
        "design": {"history_days": len(history_seeds), "train_days": len(train_seeds), "test_days": len(test_seeds),
                   "incidents_per_type_per_day": incidents_per_type, "test_payments": int(len(y_te)), "test_anomalies": int(y_te.sum()),
                   "alert_rate": alert_rate},
        "detectors": results, "leave_one_typology_out": loto,
        "explainability": {"method": "permutation importance on held-out days (drop in PR-AUC when one feature is shuffled)", "gbt": importance},
        "robustness": {"method": "multiplicative Gaussian noise on every feature at scoring time", "gbt": robustness},
    }


def score_payments(payments: Sequence[dict], history: Sequence[Sequence[dict]] | None = None, top: int = 25) -> dict:
    """Score one day of payments (dict rows as in ``SimulationResult.payments``) with the training-free detector.

    Without ``history`` the day is profiled against itself, which still surfaces bursts, fan-in, limit-hugging and
    duplicates but weakens the amount features; the result says which mode was used.
    """
    rows = rows_from_dicts(payments)
    if not rows:
        return {"version": DETECT_VERSION, "alerts": [], "mode": "empty"}
    open_at = min(r.at for r in rows)
    if history:
        days = [rows_from_dicts(h) for h in history]
        profile = CorridorProfile.fit(days, [min(r.at for r in d) for d in days])
        mode = f"profile from {len(days)} prior day(s)"
    else:
        profile = CorridorProfile.fit([rows], [open_at])
        mode = "self-profile (no history supplied)"
    X = featurize(rows, profile, open_at)
    score = _robust_z_score(X)
    order = np.argsort(-score, kind="stable")[:top]
    names = ("amount vs corridor", "new corridor + large", "sender burst", "receiver fan-in", "near network limit", "repeat within 60s")
    f = {n: i for i, n in enumerate(FEATURES)}
    alerts = []
    for i in order:
        if score[i] < 1.0:
            break
        parts = [abs(X[i, f["corridor_z"]]) / 2.5, X[i, f["corridor_novelty"]] * max(0.0, X[i, f["sender_z"]]), X[i, f["sender_burst_5m"]],
                 X[i, f["receiver_fan_in_30m"]], 3.0 if X[i, f["limit_proximity"]] > 0.9 else 0.0, X[i, f["repeat_60s"]] * 3.0]
        r = rows[i]
        alerts.append({"payment_id": r.payment_id, "rail": r.rail, "sender": r.sender, "receiver": r.receiver, "amount_minor": r.amount_minor,
                       "at": r.at.isoformat(), "score": round(float(score[i]), 3), "reason": names[int(np.argmax(parts))]})
    return {"version": DETECT_VERSION, "mode": mode, "payments_scored": len(rows), "alerts": alerts,
            "note": "Scores rank payments for human review; nothing is blocked automatically."}
