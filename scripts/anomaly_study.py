"""Payment anomaly detection study -> results/anomaly_detection.json. Usage: python scripts/anomaly_study.py"""

from __future__ import annotations

import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.detect import run_detection_experiment  # noqa: E402


def main() -> None:
    t0 = time.perf_counter()
    out = run_detection_experiment()
    out["manifest"] = {"created_at": datetime.now(UTC).isoformat(), "runtime_s": round(time.perf_counter() - t0, 2),
                       "python": platform.python_version(), "platform": platform.platform(), "data_origin": "synthetic"}
    path = Path(__file__).resolve().parents[1] / "results" / "anomaly_detection.json"
    path.write_text(json.dumps(out, indent=1))
    for k, v in out["detectors"].items():
        print(f"{k:10s} PR-AUC {v['pr_auc']:.3f}  recall@{v['alert_rate']:.1%} {v['recall_at_alert_rate']:.3f}")
    print("wrote", path)


if __name__ == "__main__":
    main()
