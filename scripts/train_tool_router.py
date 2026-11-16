"""Train the tool-routing language model and score it against the classical and keyword routers.

Usage: python scripts/train_tool_router.py [train_examples=10000] [epochs=22]   ->  results/tool_router.json, results/models/tool_router.pt
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

import torch  # noqa: E402

from atlas.agent.evals import evaluate, planner_agent, route_by_keywords  # noqa: E402
from atlas.agent.router import ROUTER_VERSION, NeuralRouter, RouterAgent, TfidfRouter, make_dataset, score_routes  # noqa: E402


def main() -> None:
    t0 = time.perf_counter()
    torch.set_num_threads(min(4, torch.get_num_threads()))
    n_train = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 22
    train, test_a, test_b = make_dataset(n_train=n_train)
    neural = NeuralRouter().fit(train, epochs=epochs)
    t_train = time.perf_counter() - t0
    tfidf = TfidfRouter().fit(train)
    routers = {"byte_transformer": neural.route, "tfidf_logreg": tfidf.route, "keyword_rules": route_by_keywords}
    scores = {name: {"unseen_templates": score_routes(fn, test_a), "handwritten": score_routes(fn, test_b)} for name, fn in routers.items()}
    for name, s in scores.items():
        print(f"{name:18s} unseen templates: intent {s['unseen_templates']['intent_accuracy']:.3f} exact {s['unseen_templates']['exact_route_accuracy']:.3f} | "
              f"handwritten: intent {s['handwritten']['intent_accuracy']:.3f} exact {s['handwritten']['exact_route_accuracy']:.3f}")
    misses = [{"text": r["text"], "expected": [r["intent"], r["stress"]], "got": [(p := neural.route(r["text"]))["intent"], p["stress"]], "confidence": p["confidence"]}
              for r in test_b if (neural.route(r["text"])["intent"], neural.route(r["text"])["stress"] if r["intent"] not in ("rulebook", "execute", "flood", "out_of_scope") else r["stress"]) != (r["intent"], r["stress"])]
    out_dir = ROOT / "results" / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    neural.save(out_dir / "tool_router.pt")
    agents = [evaluate(RouterAgent(neural, min_confidence=0.0), name="learned router, no fallback"),
              evaluate(RouterAgent(neural, min_confidence=0.6), name="learned router + keyword fallback"),
              evaluate(planner_agent, name="keyword planner (reference)")]
    for a in agents:
        print(f"{a['agent']:36s} pass {a['pass_rate']:.0%}  tools {a['tools']:.0%}  correct {a['correct']:.0%}  safe {a['safe']:.0%}")
    out = {"version": ROUTER_VERSION, "model": {"architecture": "byte-level Transformer encoder, 2 layers, d=64, 4 heads, mean pooling, 3 heads",
                                               "parameters": neural.n_params, "train_examples": len(train), "epochs": len(neural.history), "train_s": round(t_train, 1)},
           "data": {"train": "generated from templates with noise", "unseen_templates": f"{len(test_a)} questions from templates held out of training",
                    "handwritten": f"{len(test_b)} questions written by hand; the last 6 use synonyms absent from training on purpose"},
           "routing": scores, "handwritten_misses": misses, "training_curve": neural.history,
           "agent_eval": [{k: a[k] for k in ("agent", "tasks", "pass_rate", "tools", "correct", "grounded", "safe")} |
                          {"failed": [r["task"] for r in a["rows"] if not r["passed"]]} for a in agents],
           "manifest": {"created_at": datetime.now(UTC).isoformat(), "torch": torch.__version__, "device": "cpu", "python": platform.python_version(),
                        "runtime_s": round(time.perf_counter() - t0, 1)}}
    (ROOT / "results" / "tool_router.json").write_text(json.dumps(out, indent=1))
    print("wrote results/tool_router.json")


if __name__ == "__main__":
    main()
