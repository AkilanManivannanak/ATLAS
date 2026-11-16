"""Evaluate the detector families on real, labelled card fraud -> results/real_fraud.json.

Usage: python scripts/real_fraud_study.py [path/to/creditcard.csv]
Without a path the public mirror is downloaded to data/cache/ (git-ignored, about 100 MB).
"""

from __future__ import annotations

import json
import platform
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.detect.realdata import MIRROR, run_real_fraud_study  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = ROOT / "data" / "cache" / "creditcard.csv"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            print("downloading", MIRROR)
            urllib.request.urlretrieve(MIRROR, path)  # noqa: S310 - fixed https URL
    t0 = time.perf_counter()
    out = run_real_fraud_study(path)
    out["manifest"] = {"created_at": datetime.now(UTC).isoformat(), "runtime_s": round(time.perf_counter() - t0, 1), "python": platform.python_version()}
    (ROOT / "results" / "real_fraud.json").write_text(json.dumps(out, indent=1))
    for k, v in out["models"].items():
        print(f"{k:22s} PR-AUC {v['pr_auc']:.3f}  caught {v['frauds_caught']}/{v['frauds_total']} in {v['alerts']} alerts")
    print("shuffled-split optimism (PR-AUC):", out["split_optimism_pr_auc"])


if __name__ == "__main__":
    main()
