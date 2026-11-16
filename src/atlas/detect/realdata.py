"""Detector evaluation on real, labelled fraud (``atlas-detect-real-v1``).

Dataset: *Credit Card Fraud Detection* from the Machine Learning Group of Université Libre de Bruxelles (ULB):
284,807 card transactions by European cardholders over two days in September 2013, 492 of them confirmed frauds
(0.173%). Features ``V1``-``V28`` are PCA components released in place of the confidential originals, plus
``Time`` (seconds from the first transaction) and ``Amount``. Reference: Dal Pozzolo, Caelen, Johnson and
Bontempi, *Calibrating Probability with Undersampling for Unbalanced Classification*, IEEE SSCI 2015. The data is
distributed under the Open Database License; this repository does not redistribute it, the study script downloads
a public mirror and checks its shape and label count.

What this does and does not show. It is **card** fraud, not interbank payment fraud, and the features are
anonymised, so the twin's behavioural features (corridor, burst, fan-in) cannot be built on it. What transfers is
the *method*: the same detector families, the same alert-budget metrics, and the same validation discipline
(time-ordered split, drift check, importance, noise robustness) applied to labels that are real.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from atlas.detect.anomaly import average_precision
from atlas.governance import population_stability_index

REAL_VERSION = "atlas-detect-real-v1"
MIRROR = "https://raw.githubusercontent.com/nsethi31/Kaggle-Data-Credit-Card-Fraud-Detection/master/creditcard.csv"
EXPECTED = {"rows": 284_807, "frauds": 492, "columns": 31}


def load_creditcard(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Returns (time, X, y, feature_names) sorted by time. Raises if the file is not the expected dataset."""
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip('"') for h in next(reader)]
        data = np.array([[float(v.strip('"')) for v in row] for row in reader if row], dtype=np.float64)
    if len(header) != EXPECTED["columns"] or header[0] != "Time" or header[-1] != "Class":
        raise ValueError("not the ULB credit card fraud file: unexpected columns")
    y = data[:, -1].astype(int)
    if len(y) != EXPECTED["rows"] or int(y.sum()) != EXPECTED["frauds"]:
        raise ValueError(f"unexpected size: {len(y)} rows, {int(y.sum())} frauds")
    order = np.argsort(data[:, 0], kind="stable")
    return data[order, 0], data[order, 1:-1], y[order], header[1:-1]


def alert_metrics(y: np.ndarray, score: np.ndarray, alert_rate: float) -> dict:
    k = max(1, int(round(alert_rate * len(y))))
    top = np.argsort(-score, kind="stable")[:k]
    caught = int(y[top].sum())
    return {"pr_auc": round(average_precision(y, score), 4), "alerts": k, "frauds_caught": caught, "frauds_total": int(y.sum()),
            "recall_at_alert_rate": round(caught / max(1, int(y.sum())), 4), "precision_at_alert_rate": round(caught / k, 4),
            "alerts_per_fraud_caught": round(k / caught, 1) if caught else None}


def run_real_fraud_study(path: str | Path, alert_rate: float = 0.005, seed: int = 0) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    t, X, y, names = load_creditcard(path)
    X = X.copy()
    X[:, -1] = np.log1p(X[:, -1])                                   # Amount is heavy-tailed
    n = len(y)
    a, b = int(0.6 * n), int(0.8 * n)
    Xtr, ytr, Xva, yva, Xte, yte = X[:a], y[:a], X[a:b], y[a:b], X[b:], y[b:]

    def gbt(Xf, yf):
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, class_weight="balanced", early_stopping=False,
                                              random_state=seed).fit(Xf, yf)

    models = {}
    models["amount_only_rule"] = alert_metrics(yte, Xte[:, -1], alert_rate)
    iso = IsolationForest(n_estimators=200, random_state=seed).fit(Xtr[ytr == 0])
    models["isolation_forest"] = alert_metrics(yte, -iso.score_samples(Xte), alert_rate)
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")).fit(Xtr, ytr)
    models["logistic_regression"] = alert_metrics(yte, lr.predict_proba(Xte)[:, 1], alert_rate)
    g = gbt(np.vstack([Xtr, Xva]), np.concatenate([ytr, yva]))
    g_score = g.predict_proba(Xte)[:, 1]
    models["gradient_boosting"] = alert_metrics(yte, g_score, alert_rate)

    # Validation discipline: how optimistic is a shuffled split compared with the time-ordered one?
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    tr_i, te_i = perm[:b], perm[b:]
    shuffled = alert_metrics(y[te_i], gbt(X[tr_i], y[tr_i]).predict_proba(X[te_i])[:, 1], alert_rate)

    imp = permutation_importance(g, Xte, yte, scoring="average_precision", n_repeats=3, random_state=seed)
    importance = sorted(({"feature": f, "drop_in_pr_auc": round(float(m), 4)} for f, m in zip(names, imp.importances_mean)), key=lambda r: -r["drop_in_pr_auc"])[:8]
    sd = Xtr.std(axis=0)
    robustness = [{"noise_in_feature_sds": s, "pr_auc": round(average_precision(yte, g.predict_proba(Xte + rng.normal(0, 1, Xte.shape) * sd * s)[:, 1]), 4)}
                  for s in (0.0, 0.1, 0.25, 0.5)]
    top_feats = [names.index(r["feature"]) for r in importance[:6]]
    drift = sorted(({"feature": names[j], "psi_train_vs_test": round(population_stability_index(Xtr[:, j].tolist(), Xte[:, j].tolist()), 4)} for j in top_feats),
                   key=lambda r: -r["psi_train_vs_test"])
    return {
        "version": REAL_VERSION, "data_origin": "observed (public, anonymised)",
        "dataset": {"name": "ULB Credit Card Fraud Detection", "rows": n, "frauds": int(y.sum()), "fraud_rate": round(float(y.mean()), 5),
                    "features": len(names), "period": "two days, September 2013", "license": "Open Database License (not redistributed here)",
                    "citation": "Dal Pozzolo, Caelen, Johnson, Bontempi (2015), IEEE SSCI", "mirror": MIRROR},
        "design": {"split": "time-ordered 60% train / 20% validation / 20% test; final models fit on train+validation",
                   "test_rows": int(len(yte)), "test_frauds": int(yte.sum()), "test_fraud_rate": round(float(yte.mean()), 5), "alert_rate": alert_rate},
        "models": models,
        "shuffled_split_gradient_boosting": shuffled,
        "split_optimism_pr_auc": round(shuffled["pr_auc"] - models["gradient_boosting"]["pr_auc"], 4),
        "importance": importance, "robustness": robustness, "drift": drift,
        "scope_note": "Card fraud with anonymised features, not interbank payments. It validates the detector families and the evaluation method on real labels.",
    }
