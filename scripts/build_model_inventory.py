"""Build the model inventory and model cards from results artifacts.

Usage: python scripts/build_model_inventory.py   ->  results/model_inventory.json, docs/model_cards/*.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.governance import build_inventory, render_model_card  # noqa: E402


def main() -> None:
    inv = build_inventory(ROOT / "results")
    (ROOT / "results" / "model_inventory.json").write_text(json.dumps(inv, indent=1))
    cards = ROOT / "docs" / "model_cards"
    cards.mkdir(exist_ok=True)
    index = ["# Model cards", "", "Generated from `results/model_inventory.json`.", "", "| Model | Tier | Status |", "|---|---|---|"]
    for m in inv["models"]:
        name = m["id"].replace(".", "_") + ".md"
        (cards / name).write_text(render_model_card(m))
        index.append(f"| [{m['name']}]({name}) | {m['materiality']['tier']} | {m['status'].upper()} |")
    (cards / "README.md").write_text("\n".join(index) + "\n")
    print(inv["summary"])
    for m in inv["models"]:
        print(f"{m['status'].upper():5s} {m['materiality']['tier']:9s} {m['id']}")
        for c in m["checks"]:
            if c["status"] != "pass":
                print("        ", c["status"], c["check"], c["value"])


if __name__ == "__main__":
    main()
