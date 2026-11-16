# Known limitations and risk register

| Risk / limitation | Why it matters | Current treatment / next control |
|---|---|---|
| Synthetic data only | Results describe the model, not real payment systems | Every artifact and UI screen is labeled synthetic; no real data is ingested. |
| Rail archetypes are not replicas | Readers may over-interpret rail names | Archetypes plus a separate evidence/assumption registry (`RAIL_RULES`); no live connectivity. |
| Cost model weights are assumptions | Policy rankings can depend on weights | Documented `CostModel`; next: a sensitivity study across weights. |
| FedNow pool is separate by default | Real FedNow settles in the shared Fed master account | Shared-account option (`fednow_shared_master`) implemented and tested; the headline results hold under it (`results/shared_master.md`). Controllers are not yet aware of the shared account. |
| Instant rails only inside the business day | No weekend/overnight instant liquidity dynamics | Documented; next: 24/7 days. |
| Netting heuristic gap on adversarial queues | Up to ~40% value left vs optimal (LP rounding ~30%) | Exact MILP is fast enough for operational queue sizes (<1 s at 200); a 50 ms anytime MILP is exact to 50 obligations. Gaps published. |
| Seed counts | Standard preset 5 seeds; extended 10 | Both published; claims cite CIs. |
| Game-theoretic results partly inconclusive | Only "recycler is unstable" is established | Verdicts are three-valued and scoped; no Nash claim. |
| Safe RL ties but does not beat MPC | Learned control adds no cost advantage yet | Reported as such; runtime advantage only (no optimisation solve). |
| Auction loans cannot default | Lender incentives ignore credit risk | Unrepaid amounts roll overnight and are reported as exposure. |
| Not implemented: LSTM/TFT, XSD validation, PostgreSQL/ClickHouse/MLflow, generative LLM narration | Blueprint scope remains | Listed in `PROJECT_STATUS.md`; no doc claims them. |
| Cross-rail transfers are instantaneous | Real liquidity transfers have cutoffs and delays | Safety cutoff 15 minutes before close; next: modeled transfer latency. |
| Facility interest accrues to close regardless of early repayment | Slight overstatement of funding cost | Documented simplification. |
| Development-mode API | Open access if exposed | `/health` reports auth mode; set `ATLAS_API_KEYS` for any network deployment. |
| Docker images not built in the authoring environment | Container regressions possible | CI builds both images and health-checks the API on every push. |
| Float use | Analytics and costs use floats | Authoritative ledger state is integer-only and validated; floats appear only in metrics, sampling and solvers, and solver output is re-verified in integers. |
| No real institution has used the tool | "Usable on real data" is a capability, not a track record | Ingest tested by round-trip and malformed-row tests; real formats in, assumptions listed. |
| Uploaded files rarely include opening balances | Results depend on the assumed balances | Optional balances file; otherwise the assumption is printed with the result. |
| Anomaly labels on the twin are injected typologies | Detection figures on the twin do not transfer to real fraud | The detector families are also run on real labelled card fraud (`results/real_fraud.json`); that is a different domain with anonymised features, so the twin's behavioural features remain unvalidated on real labels. |
| No language model evaluated | Agent results cover a deterministic reference and two failing controls only | `atlas evals --llm` and the app's Agent page accept any OpenAI-compatible endpoint; none was reachable when this was built. |
| Grounding check is numeric and refusal check is keyword-based | A model could pass with a wrong non-numeric claim | Documented as heuristics; correctness is checked separately against recomputed truth. |
| Browser lab excludes safe RL, deep forecasters and ML detectors | Those need the Python package or the app | MPC + auction now runs in the lab (scipy on WebAssembly, loaded on demand). |
| BCBS 248 correspondent tools B(i)/(ii) not implemented | No customer-bank view | The twin has direct participants only. |
| Model inventory is not a compliance attestation | Could be misread as regulatory sign-off | Disclaimer in the artifact and model cards. |
| Calibration matches means only | Size distribution shape, network and timing are still assumed | Listed under `not_identified_by_public_data` in `results/calibration.json`. |

| Streamlit app not deployed or load-tested by the author | Behaviour on Streamlit Community Cloud (memory, cold start) is unverified | Verified locally in a headless browser and with `AppTest`; simulations are cached and sized for one CPU. |
| Zero published reviews | "Used by real users" is not yet true | The review channel is public and attributable (GitHub issues); the app shows the real count. |
| Retrieval is lexical and extractive | Paraphrased questions with no shared terms can miss | Measured on labelled questions; a small synonym map; the limitation is stated in the module. |
| Retrieval labels revised once after inspection | Reported hit rates are optimistic | Stated next to the figures. |
| Deep forecasters: one seed, CPU, no shift test | The 6% gain over ridge may not be stable | Stated in the model cards; scored by the same code as every other model. |
| Kubernetes manifests never applied | They may need changes for a given cluster (ingress class, storage) | Structure and hardening are tested; the file says so at the top. |
| Real fraud study is card fraud from 2013 with 75 test frauds | Not evidence about interbank payment fraud; per-model differences of one or two frauds are noise | Scope note in the artifact, figure and README. |
| The trained tool router is a small model on template-generated questions | It knows no wording it has not seen and loses to TF-IDF and keyword rules on hand-written questions | Reported as such; the agent falls back to keyword rules below a confidence threshold; safety does not depend on it. |
| No general-purpose language model evaluated | The agent harness has been exercised by a deterministic planner, two failing controls and the small trained router only | `scripts/eval_local_llm.sh` runs the same tasks against a local model; hosted and local models were unreachable in the build environment. |
| Hosted-inference contract and Kubernetes manifests never deployed | Cloud behaviour (auth, scaling, cold start) is unverified | Contract tested locally; manifests schema-tested. |
| GPU training path untested | `device="auto"` selects CUDA or Apple GPU but has only run on CPU | Stated; CPU is the default for reproducibility. |
