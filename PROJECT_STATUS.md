# Project status

**Version:** 0.8.0 · **Stage:** all ten blueprint phases implemented to a research-grade increment, including the previously missing auction mechanism, safe RL, decision center and 100-bank scale. Remaining gaps are listed below and in `docs/20_known_limitations.md`.

## Blueprint coverage

| Phase | Status |
|---|---|
| 1. Domain model | Done |
| 2. Multi-rail simulation | Done: four rails, business-day simulator, customer cutoff, LSM closing-position funding |
| 3. Event infrastructure | Done: hash-chained store, strict replay, ISO 20022 pacs.008/009/004 + camt.053 statements |
| 4. Agents | Done: six strategies; empirical game (16 seeds: recycler profile unstable); learning agents via safe RL |
| 5. Liquidity, collateral, forecasting | Done: PSR fee with collateralized/uncollateralized credit; six forecasters incl. graph-conditioned and neural; adaptive intervals. LSTM/TFT not implemented |
| 6. Network and stress | Done |
| 7. Market design and optimization | Done: liquidity auction (pay-as-bid, uniform) with incentive study; netting MILP + LP rounding + heuristic; CVaR LP; MPC |
| 8. Safe RL | Done: constrained PPO (v2) ties MPC on held-out days with 0% safety rejections; v1 failure documented |
| 9. Product | Done: API (analyst, statements, counterfactuals), 9-screen Command Center, Docker, CI, GitHub Pages explorer |
| 10. Validation | Done: standard (240 runs) and extended (1,320 runs, 11 stresses) benchmarks; headline result replicates in 11/11 stresses and 297/297 stress × cost-model cells; scaling to 669k payments |

## v0.7: usable on real data, and built to bank AI practice
| Area | Status |
|---|---|
| Bring your own data | Done: CSV and ISO 20022 pacs.008/009 ingestion with row-level rejects and a list of assumptions; `atlas` CLI; API upload; counterfactuals on uploaded days |
| Browser lab | Done: the stdlib core runs under Pyodide on GitHub Pages; upload stays on the device |
| Supervisory reporting | Done: BCBS 248 tools A(i)-A(iv), C(i). Correspondent tools B(i)/(ii) not applicable |
| Anomaly detection | Done on injected typologies: rule, isolation forest, gradient boosting, leave-one-pattern-out |
| Model risk | Done: inventory, materiality tiers, automated checks, generated model cards (1 pass, 4 warn, 2 fail) |
| Agents | Done: guarded tool layer, MCP server, OpenAI-compatible loop, evaluation harness with failing controls. No language model evaluated |
| Calibration | Done: mean payment sizes fitted to Fedwire 2025 and FedNow/RTP 2026 published statistics |
| Command Center | Superseded for the v0.7+ views by the Streamlit app; the Next.js app still covers the v0.6 screens |

## v0.8: an app people can use and review, and four closed gaps
| Area | Status |
|---|---|
| Interactive app | Done: Streamlit, seven pages, every v0.7 view, upload, agent chat with grounding badges, tamper demo. Verified locally (headless browser and `AppTest`); **not yet deployed** by the author |
| Reviews from real users | Channel done: in-app form opens a pre-filled public GitHub issue; published reviews are listed in the app. **Zero reviews so far** |
| Retrieval (RAG) | Done: extractive BM25 with citations, measured, exposed as an agent tool |
| Deep learning | Done: GRU and Transformer in PyTorch, trained here on CPU; GRU is the best forecaster at 60 training days |
| Red teaming | Done for the reference agent: injection and budget-flood tasks |
| Kubernetes | Manifests written and schema-tested; never applied to a cluster |
| Language model evaluation | **Still not done**: no model was reachable from the build environment |
| Real fraud data | **Still not available** |

## Verification (2026-11-16, Python 3.13.18, Linux x86_64, torch 2.x CPU)
- `pytest -q`: **191 passed**. `ruff check src tests scripts`: clean. Frontend `tsc --noEmit` and `next build`: pass.
- All benchmark, auction, RL, game and scaling runs replay-verified.
- Not verified here: Docker image builds (no Docker daemon); CI builds them on push.

## Changed since v0.5 (results not comparable)
Generator v2 (realism fixes, D-019), PSR fee (D-020), LSM closing funding, customer cutoff, exact performance work (D-021: ≈3× faster), new arms (auction, MPC + auction), benchmark v2 with cost sensitivity.

## Known gaps
FedNow on its own pool by default (shared-master-account option available; controllers not yet aware of it); instant rails only inside the business day; no defaults, net debit caps or PSR waiver; LSTM/TFT absent; analyst and reference agent are deterministic (no language model evaluated); anomaly labels are injected; no real institution has used the tool; no PostgreSQL/ClickHouse/MLflow (deferred, D-016).

## Next tasks
1. Make MPC and the safe-RL controller aware of the shared FedNow master account (done: the option itself and the re-test, `results/shared_master.md`).
2. 24/7 instant-rail days and weekend liquidity.
3. Auction with collateralized loans and counterparty limits; incentive study for borrowers.
4. Multi-day panels with overnight funding and carry-over positions.
5. LSTM/TFT once a deep-learning framework is added to the dependency set.
