"""Score rulebook retrieval on the labelled question set -> results/retrieval_eval.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.knowledge import evaluate_retrieval  # noqa: E402

if __name__ == "__main__":
    out = evaluate_retrieval()
    (ROOT / "results" / "retrieval_eval.json").write_text(json.dumps(out, indent=1))
    print(out["passages"], "passages", out["methods"])
