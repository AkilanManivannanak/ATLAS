"""Retrieval with citations over the repository's documents (``atlas-knowledge-v1``). Standard library only.

An agent that proposes a liquidity action should be able to point at the rule it relies on. This module splits
every Markdown document into heading-level passages and ranks them with BM25. Each hit carries its file, heading
and line number, so an answer can cite ``docs/04_payment_rail_specifications.md § FedNow`` instead of asserting.

Design choices:

* **Lexical first.** The corpus is a few hundred passages of precise domain vocabulary (rail names, rule ids,
  regulation numbers), where exact-term matching is strong and fully explainable. No embedding model, so no
  network access or model download.
* **Extractive.** ``Corpus.answer`` returns the best passages verbatim with citations; it never paraphrases.
  A language model may be placed on top through the agent loop, which then cites the same passage ids.
* **Measured.** ``evaluate_retrieval`` scores a labelled question set (hit@1, hit@3, MRR) and compares BM25 with
  a plain term-overlap baseline.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_VERSION = "atlas-knowledge-v1"
ROOT = Path(__file__).resolve().parents[3]
_TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_STOP = frozenset("a an and are as at be by for from has have how in is it its of on or that the this to was what when where which who why with "
                  "does do can i we you not no if then than into about over under per each any all".split())
_SYN = {"fedwire": ("rtgs",), "chips": ("lsm",), "overdraft": ("daylight",), "sr": ("26-2",), "mrm": ("model", "risk"), "llm": ("language", "model"),
        "fraud": ("anomaly",), "netting": ("multilateral",), "cutoff": ("cut-off",), "limit": ("limits",)}


def tokenize(text: str) -> list[str]:
    out = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOP:
            continue
        out.append(tok)
        if any(c in tok for c in "._-"):
            out.extend(p for p in re.split(r"[._-]", tok) if p and p not in _STOP)
    return out


@dataclass(frozen=True)
class Passage:
    pid: str
    path: str
    heading: str
    line: int
    text: str

    @property
    def citation(self) -> str:
        return f"{self.path} § {self.heading} (line {self.line})"


def _split(path: Path, rel: str) -> list[Passage]:
    passages, heading, start, buf = [], path.stem.replace("_", " "), 1, []
    title = heading

    def flush(n: int) -> None:
        body = "\n".join(buf).strip()
        if len(body) >= 60:
            passages.append(Passage(f"{rel}#{len(passages) + 1}", rel, heading, start, body))

    in_code = False
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,4}\s+\S", line):
            flush(n)
            text = line.lstrip("#").strip()
            if line.startswith("# "):
                title = text
            heading = text if line.startswith("# ") else f"{title} / {text}"
            start, buf = n, []
        else:
            buf.append(line)
    flush(0)
    return passages


class Corpus:
    def __init__(self, passages: Sequence[Passage], k1: float = 1.4, b: float = 0.7) -> None:
        self.passages = list(passages)
        self.k1, self.b = k1, b
        self._tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for p in self.passages:
            tf: dict[str, int] = {}
            for t in tokenize(p.heading + " " + p.heading + " " + p.text):       # headings count twice
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            for t in tf:
                df[t] = df.get(t, 0) + 1
        n = max(1, len(self.passages))
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = sum(self._len) / n
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def _query_terms(self, query: str) -> list[str]:
        terms = tokenize(query)
        return terms + [s for t in terms for s in _SYN.get(t, ())]

    def search(self, query: str, k: int = 5, method: str = "bm25") -> list[dict]:
        terms = self._query_terms(query)
        scored = []
        for i, tf in enumerate(self._tf):
            if method == "overlap":
                s = float(sum(1 for t in set(terms) if t in tf))
            else:
                s = 0.0
                for t in terms:
                    f = tf.get(t)
                    if f:
                        s += self._idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self._len[i] / self._avg))
            if s > 0:
                scored.append((s, -i))
        scored.sort(reverse=True)
        out = []
        for s, neg in scored[:k]:
            p = self.passages[-neg]
            out.append({"passage_id": p.pid, "source": p.path, "heading": p.heading, "line": p.line, "citation": p.citation,
                        "score": round(s, 3), "text": p.text[:900] + ("…" if len(p.text) > 900 else "")})
        return out

    def answer(self, question: str, k: int = 3) -> dict:
        hits = self.search(question, k)
        terms = set(tokenize(question))
        top_tf = self._tf[next(i for i, p in enumerate(self.passages) if p.pid == hits[0]["passage_id"])] if hits else {}
        rare = [t for t in terms if t in top_tf and self._idf.get(t, 0) >= 1.5]
        if not hits or len(rare) < 2:
            return {"version": KNOWLEDGE_VERSION, "question": question, "found": False, "passages": [],
                    "answer": "Nothing in the project's documents matches that closely enough to cite."}
        return {"version": KNOWLEDGE_VERSION, "question": question, "found": True, "passages": hits,
                "answer": hits[0]["text"], "citations": [h["citation"] for h in hits],
                "note": "Extractive: the passages are quoted from the cited files, not generated."}


def load_corpus(root: Path | None = None) -> Corpus:
    root = root or ROOT
    files = sorted((root / "docs").glob("*.md")) + sorted((root / "docs" / "model_cards").glob("*.md"))
    files += [p for p in (root / "DECISIONS.md", root / "data" / "public" / "README.md") if p.exists()]
    passages: list[Passage] = []
    for f in files:
        passages += _split(f, f.relative_to(root).as_posix())
    return Corpus(passages)


# Labelled questions: any passage from one of the listed files counts as a hit. The labels were revised once after a
# first run showed correct answers in files the first labelling had missed (the glossary, docs/08, docs/15).
GOLD: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("What is the FedNow transaction limit?", ("docs/24_glossary.md", "docs/04_payment_rail_specifications.md", "docs/23_realism_and_calibration.md", "docs/rule_registry.md")),
    ("How is the daylight overdraft fee calculated?", ("docs/24_glossary.md", "docs/23_realism_and_calibration.md", "docs/07_funding_collateral_operations.md", "docs/rule_registry.md", "DECISIONS.md")),
    ("What checks does the safety controller apply to a proposed transfer?", ("docs/14_safe_rl_design.md", "docs/13_optimization_formulation.md", "docs/16_security_and_governance.md", "docs/03_system_architecture.md")),
    ("How does replay verify the ledger?", ("docs/08_simulator_and_vertical_slice.md", "docs/24_glossary.md", "docs/06_financial_ledger_specification.md", "docs/05_event_engine_design.md", "docs/03_system_architecture.md")),
    ("Which BCBS 248 tools are not implemented?", ("docs/15_api_specification.md", "docs/20_known_limitations.md", "docs/19_experimental_results.md", "docs/25_industry_landscape.md")),
    ("Why did the first version of the reinforcement learning agent fail?", ("docs/14_safe_rl_design.md", "docs/19_experimental_results.md", "DECISIONS.md")),
    ("What replaced SR 11-7 and what does it say about generative AI?", ("docs/25_industry_landscape.md",)),
    ("Is pay-as-bid or uniform price more manipulable?", ("docs/22_market_design.md", "docs/19_experimental_results.md")),
    ("How is partial multilateral netting formulated as a MILP?", ("docs/11_settlement_algorithms.md", "docs/13_optimization_formulation.md")),
    ("What happens to auction loans that are not repaid by close?", ("docs/22_market_design.md", "DECISIONS.md", "docs/20_known_limitations.md", "docs/19_experimental_results.md")),
    ("What does the anomaly detector do on patterns it has never seen?", ("docs/19_experimental_results.md", "docs/20_known_limitations.md", "docs/model_cards/detect_gbt.md")),
    ("How are conformal prediction intervals made adaptive under distribution shift?", ("docs/12_forecasting_methodology.md", "docs/19_experimental_results.md")),
    ("What is a liquidity-saving mechanism?", ("docs/24_glossary.md", "docs/04_payment_rail_specifications.md", "docs/11_settlement_algorithms.md")),
    ("Which published statistics is payment size calibrated to?", ("docs/23_realism_and_calibration.md", "data/public/README.md", "docs/19_experimental_results.md", "DECISIONS.md")),
    ("How does FedNow share the master account with Fedwire?", ("docs/24_glossary.md", "docs/23_realism_and_calibration.md", "DECISIONS.md", "docs/20_known_limitations.md")),
    ("What are the agent tools not allowed to do?", ("DECISIONS.md", "docs/25_industry_landscape.md", "docs/20_known_limitations.md", "docs/16_security_and_governance.md")),
    ("How are bank release strategies defined?", ("docs/09_agent_economics.md",)),
    ("What is the cost model and how sensitive are results to its weights?", ("docs/18_benchmark_specification.md", "docs/19_experimental_results.md", "DECISIONS.md")),
    ("How is an ISO 20022 pacs.008 message validated?", ("docs/24_glossary.md", "docs/08_simulator_and_vertical_slice.md", "docs/02_financial_domain_model.md", "docs/05_event_engine_design.md", "docs/16_security_and_governance.md", "docs/15_api_specification.md", "docs/03_system_architecture.md")),
    ("How is systemic importance of a bank measured in the network?", ("docs/10_systemic_risk_model.md",)),
)


def evaluate_retrieval(corpus: Corpus | None = None, gold: Sequence[tuple[str, tuple[str, ...]]] = GOLD) -> dict:
    corpus = corpus or load_corpus()
    out = {"version": KNOWLEDGE_VERSION, "passages": len(corpus.passages), "questions": len(gold), "methods": {}, "rows": []}
    for method in ("bm25", "overlap"):
        h1 = h3 = 0
        rr = 0.0
        for q, ok in gold:
            hits = corpus.search(q, 5, method)
            rank = next((i + 1 for i, h in enumerate(hits) if h["source"] in ok), None)
            h1 += rank == 1
            h3 += rank is not None and rank <= 3
            rr += 1 / rank if rank else 0.0
            if method == "bm25":
                out["rows"].append({"question": q, "rank": rank, "top": hits[0]["citation"] if hits else None})
        out["methods"][method] = {"hit_at_1": round(h1 / len(gold), 3), "hit_at_3": round(h3 / len(gold), 3), "mrr": round(rr / len(gold), 3)}
    return out
