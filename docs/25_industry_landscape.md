# Industry landscape: what large US banks are doing with AI, and what they hire for

Research date: 16 November 2026. Sources are linked inline; job postings change or close, so each is cited with what it said on that date. This document explains *why* v0.7 and v0.8 added what they added.

## 1. Where the banks are

| Bank | What is public | Source |
|---|---|---|
| **JPMorgan Chase** | 2026 technology budget $19.8B (+≈$2B); 450 generative-AI use cases in production at end of 2025; LLM Suite open to 230,000+ staff; management names corporate treasury as ripe for agents | [beri.net](https://www.beri.net/article/jpmorgan-reclassifies-ai-core-infrastructure-2026), [InvestmentNews](https://www.investmentnews.com/fintech/wall-street-banks-promoting-ai-agents-from-research-aids-into-digital-coworkers/267388) |
| **Bank of America** | CashPro processed 213M payments in H1 2026; CashPro Data Intelligence does cash forecasting and fraud scoring; Payments Insights launched 28 Sep 2026 | [Fortune](https://fortune.com/2026/09/28/bank-of-america-wants-ai-to-do-treasurys-grunt-work-cfo/) |
| **Citi** | Stylus Workspaces rolled out to 180,000+ people; Arc agent platform (Apr 2026); automated controls across the AI lifecycle with "a human always in the loop"; building for agent-to-agent business | [Citi](https://www.citigroup.com/global/news/perspectives/2026/competitive-differentiator-david-griffiths-building-worlds-most-ai-empowered-financial-institution) |
| **Goldman Sachs** | Agents for trade and transaction accounting, client vetting and onboarding | [InvestmentNews](https://www.investmentnews.com/fintech/wall-street-banks-promoting-ai-agents-from-research-aids-into-digital-coworkers/267388) |
| **Morgan Stanley** | Opened stock-plan platforms to clients' own AI agents through the Model Context Protocol; "agents will not have autonomy over portfolio decisions" | same |
| **BNY** | "Digital employees" with their own logins and a human manager each, including one for payments | same |

**The pattern:** agents are moving from assistants to doing process work, but always with human approval on anything that moves money, and with controls built into the platform.

## 2. What is changing underneath payments

* **Always-on settlement.** FedNow settled 6.4M payments worth $371B in Q3 2026, up from 2.5M a year earlier ([FRB Services](https://www.frbservices.org/wp-content/uploads/20261020-quarterly-3q2026-fednow-ascii.txt)). FedNow and RTP both raised limits to $10M in 2025. FedNow has 1,725 participants and RTP 1,193 ([Richmond Fed EB 26-28](https://www.richmondfed.org/publications/research/economic_brief/2026/eb_26-28)).
* **End-of-day treasury is ending.** Treasurers need intraday visibility and real-time forecasting; regulators are paying more attention to intraday liquidity risk ([Global Finance / BNY](https://gfmag.com/transaction-banking/the-end-of-end-of-day-treasury-preparing-for-a-world-of-continuous-liquidity-management/), sponsored content).
* **Tokenized deposits.** The Clearing House, owned by JPMorgan, Bank of America, Citi, Wells Fargo and others, plans a tokenized-deposit network with 24/7 settlement as soon as H1 2027 ([The Block, citing WSJ](https://www.theblock.co/amp/post/403701/jpmorgan-citi-major-banks-tokenized-deposit-network)).
* **Fedwire still dominates value:** 869,187 transfers and $4.59 trillion per day in 2025, $5.28M on average ([FRB Services](https://www.frbservices.org/resources/financial-services/wires/volume-value-stats/fedwire-funds-service-annual-statistics/)).

## 3. The rulebook changed in 2026

On 17 April 2026 the Federal Reserve, OCC and FDIC replaced SR 11-7 with **SR 26-2**. As summarised by [Lumenova](https://www.lumenova.ai/blog/sr-26-2-model-risk-management-banking/) (a vendor; check the agencies' text before relying on it):

* Materiality = model **exposure** × model **purpose**; aggregate risk across linked models.
* Inventories cover statistical and quantitative models; deterministic rule tools move out of the formal inventory but still need controls.
* Stronger effective challenge and continuous monitoring for drift.
* Generative and agentic AI are **outside** the guidance for now and are to be governed through enterprise AI, data, cyber and operational risk frameworks.

## 4. What fourteen AI/ML postings ask for

| Level | Postings read | Experience | Pay shown |
|---|---|---|---|
| Entry / junior | JPMorgan *Data & AI Program* (2027 graduates); JPMorgan *Applied AI ML, Payments Machine Learning (Associate)*; JPMorgan *Intraday Liquidity Management, Data Analytics and Forecasting (Associate)*; Bank of America *AI Engineer, Data Scientist I* (Global Payments Solutions) | 0-3 years | $95k-$115k (JPM program), $107k-$193k (BofA) |
| Senior | Citi *Machine Learning Engineer, VP*; Goldman Sachs *VP, AI/ML Engineering* (two postings); Goldman Sachs *Risk, AI Model Validation, VP*; JPMorgan *Applied AI ML Lead, AI Agents*; Bank of America *Senior AI Engineer* | 5-8 years | $142k-$213k (Citi), $130k-$250k (GS) |
| Director and above | Citi *Director, Applied AI Engineering*; Citi *Director, AI Risk Monitoring Lead*; JPMorgan *Applied AI ML Executive Director*; JPMorgan *Applied ML and Generative AI Leader, Executive Director*; Wells Fargo *Principal AI Engineer*; Wells Fargo *Principal Engineer* | 7-15 years | $159k-$305k (WF) |

Links: [JPM Data & AI Program](https://simplify.jobs/p/2f5f6d1a-1591-4d2b-9eea-c4a0fbe02433/Data--AI-Program) · [JPM Payments ML Associate](https://www.oneroadmap.io/jobs/6abd1f8d36c2e1375dc8ec99) · [JPM Intraday Liquidity Associate](https://www.dice.com/job-detail/3dde72f5-24fe-45e2-a7e3-3a094d4844d2) · [BofA DS I](https://freehire.me/jobs/ai-engineer-data-scientist-i-bank-of-america-rv3vzgf7) · [Citi VP](https://jobs.citi.com/job/jersey-city/machine-learning-engineer-vice-president/287/89702719056) · [GS VP](https://jobs.wallstreetfriends.org/companies/goldman-sachs/jobs/64776056-engineering-vice-president-ai-ml-engineering) · [GS VP (Richardson)](https://jobs.wallstreetfriends.org/companies/goldman-sachs/jobs/64776396-ai-ml-engineering-dallas-associate) · [GS AI Model Validation](https://higher.gs.com/roles/137676) · [JPM Lead, Agents](https://zapply.jobs/jobs/bfbe8988-adfe-4454-adaf-fe5ede639e0e/) · [BofA Senior](https://simplify.jobs/p/16fa7177-2344-4201-ad8a-8d4507fd5777/Senior-AI-Engineer) · [Citi Director, Applied AI](https://jobs.citi.com/job/jersey-city/director-applied-artificial-intelligence-engineering/287/96344791488) · [Citi Director, AI Risk Monitoring](https://jobs.technyc.org/companies/citi-2-db90f7f6-7bfb-4128-83f9-bb534f36fcb7/jobs/68240034-director-ai-risk-monitoring-lead) · [JPM ED](https://www.builtinnyc.com/job/applied-ai-ml-executive-director-chief-data-analytics-office/10669590) · [JPM ED, GenAI Leader](https://zapply.jobs/jobs/f75f702a-0c4b-4d45-9726-fc4f3e9a88d3/) · [WF Principal AI](https://jobs.anitab.org/companies/wells-fargo/jobs/91419497-principal-ai-engineer) · [WF Principal](https://www.builtinnyc.com/job/principal-engineer/9951411). Several were read on job-board mirrors and some have since closed. Sixteen links are listed; fourteen had enough detail to code into the matrix (`data/hiring_map.json`). No managing-director posting with a public description was found.

**What separates the levels**

* **Entry / junior:** build, measure, document. Python and SQL, statistics, time series, experiment design (KPIs, uplift), deploying and monitoring a model, model cards and audit-ready documentation. The JPMorgan intraday-liquidity role asks for exactly this project's subject: forecasting intraday liquidity and turning it into decisions.
* **Senior:** make AI safe in production. Tool-calling agents with guardrails and least privilege (Goldman names MCP), retrieval, deep-learning frameworks, evaluation frameworks, validators, fallbacks and rollbacks, CI/CD, Kubernetes. Model validators are asked for benchmark models, explainability and robustness tests.
* **Director and above:** make it governable and reusable. Multi-agent platforms and shared standards, red teaming, tracing and observability, risk indicators with thresholds and escalation, MLOps pipelines, fine-tuning, mentoring, measurable business outcomes.

Fourteen postings is a sample, not a survey.

## 5. What v0.7 built in response

| Finding | Built | Where |
|---|---|---|
| Real-time treasury needs intraday visibility in a form supervisors use | BCBS 248 intraday liquidity report for every bank | `atlas.regulatory` |
| Banks' payment AI is forecasting plus fraud/anomaly scoring | Anomaly detection with a rule challenger and leave-one-pattern-out testing | `atlas.detect` |
| SR 26-2: inventory, materiality, effective challenge, monitoring | Model inventory with automated checks and generated model cards | `atlas.governance` |
| Agents with guardrails, least privilege, MCP, evaluation | Read-only tool layer, budgets, hash-chained audit, MCP server, evaluation harness with failing controls | `atlas.agent` |
| Tools must work on a bank's own data | CSV and ISO 20022 ingestion, CLI, API upload, in-browser lab | `atlas.ingest`, `atlas.cli`, `atlas.lab` |
| Synthetic data should be anchored to published facts | Mean payment sizes fitted to Fedwire and FedNow statistics | `atlas.calibration`, `data/public/` |

## 6. What v0.8 added after the director-level postings

| Asked for | Built | Where |
|---|---|---|
| An interface people can actually use and review | Streamlit app: animated day, what-if, upload, risk views, agent chat, public reviews | `streamlit_app.py`, `atlas.insight` |
| Retrieval with citations | BM25 over the project's own rulebook, measured on labelled questions, exposed as an agent tool | `atlas.knowledge` |
| Deep-learning frameworks, training | GRU and Transformer forecasters trained in PyTorch with early stopping and saved checkpoints | `atlas.forecast.deep` |
| Red teaming, guardrails | Prompt-injection and budget-flood tasks in the agent evaluation | `atlas.agent.evals` |
| Explainability and robustness in validation | Permutation importance and input-noise test for the anomaly model | `atlas.detect` |
| Tracing | Per-call latency on the hash-chained tool audit | `atlas.agent.tools` |
| Kubernetes | Hardened manifests for the API and the app (schema-tested, not applied to a cluster) | `deploy/k8s/` |

## 7. Still open

1. **A language model run.** The harness scores any OpenAI-compatible endpoint (`atlas evals --llm`); the build environment had no model to call.
2. **Real fraud labels.** Anomaly incidents are injected; no public interbank fraud data exists.
3. **Cloud ML platforms, LLM fine-tuning, GPUs.** Not present.
4. **24/7 days, a tokenized-deposit rail, agent-to-agent treasury.** The direction the industry is moving; not modeled yet.
