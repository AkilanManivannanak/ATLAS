"""Train the GRU and Transformer forecasters and compare them with ridge and gradient boosting at two data sizes.

Usage: python scripts/deep_forecast_study.py   ->  results/deep_forecasting.json, results/models/*.pt
"""

from __future__ import annotations

import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from atlas.forecast.deep import DEEP_VERSION, GRUForecaster, TransformerForecaster  # noqa: E402
from atlas.forecast.models import GradientBoostingForecaster, RidgeForecaster, SeasonalNaiveForecaster, build_panel, evaluate  # noqa: E402
from atlas.scenario import NexusPayConfig  # noqa: E402

CONFIG = NexusPayConfig(n_institutions=12, payments_per_day=2_000, instant_payments_per_day=0)
SIZES = (12, 60)
HORIZONS = {"15m": 1, "1h": 4}
VAL, TEST = tuple(range(2000, 2006)), tuple(range(3000, 3008))


def main() -> None:
    t0 = time.perf_counter()
    rows, curves = [], {}
    for n_train in SIZES:
        seeds = list(range(1000, 1000 + n_train)) + list(VAL) + list(TEST)
        panel = build_panel(CONFIG, seeds, 2026, "gross_outflow")
        tr = list(range(n_train))
        va = list(range(n_train, n_train + len(VAL)))
        te = list(range(n_train + len(VAL), len(seeds)))
        days = panel["days"][tr]
        mase_scale = float(np.mean(np.abs(days[1:] - days[:-1])))
        for label, h in HORIZONS.items():
            for cls in (SeasonalNaiveForecaster, RidgeForecaster, GradientBoostingForecaster, GRUForecaster, TransformerForecaster):
                t = time.perf_counter()
                model = cls()
                r = evaluate(model, panel, tr, va, te, h, mase_scale=mase_scale)
                r |= {"horizon": label, "train_days": n_train, "fit_predict_s": round(time.perf_counter() - t, 2)}
                if hasattr(model, "history"):
                    r |= {"parameters": model.n_params, "train_samples": model.train_samples, "epochs_run": len(model.history)}
                    curves[f"{model.name}|{n_train}|{label}"] = model.history
                    if n_train == max(SIZES) and h == 1:
                        out = ROOT / "results" / "models"
                        out.mkdir(parents=True, exist_ok=True)
                        model.save(out / f"{model.name}_gross_outflow_15m.pt")
                rows.append(r)
                print(f"{n_train:3d} days  {label:4s} {r['model']:18s} MASE {r['mase']:.3f}  cover {r['interval_coverage']:.3f}  {r['fit_predict_s']:.1f}s")
    out = {"version": DEEP_VERSION, "target": "large-value gross outflow per bank per 15 minutes", "train_sizes_days": list(SIZES),
           "val_days": len(VAL), "test_days": len(TEST), "results": rows, "training_curves": curves,
           "manifest": {"created_at": datetime.now(UTC).isoformat(), "runtime_s": round(time.perf_counter() - t0, 1), "torch": torch.__version__,
                        "device": "cpu", "python": platform.python_version(), "data_origin": "synthetic"}}
    (ROOT / "results" / "deep_forecasting.json").write_text(json.dumps(out, indent=1))
    print("wrote results/deep_forecasting.json")


if __name__ == "__main__":
    main()
