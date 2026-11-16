# Industry landscape: what large US banks are doing with AI, and what they hire for

Research date: 16 November 2026. Sources are linked inline; job postings change or close, so each is cited with what it said on that date. This document explains *why* v0.7 added what it added.

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

## 4. What nine AI/ML postings ask for

| Level | Postings read | Experience | Pay shown |
|---|---|---|---|
| Junior | JPMorgan *Applied AI ML, Payments Machine Learning (Associate)*; Bank of America *AI Engineer, Data Scientist I* (Global Payments Solutions, New York) | 2+ years | $107k-$193k (BofA) |
| Senior | Citi *Machine Learning Engineer, VP*; Goldman Sachs *VP, AI/ML Engineering* (two postings); JPMorgan *Applied AI ML Lead, AI Agents*; Bank of America *Senior AI Engineer* | 5-8 years | $142k-$213k (Citi), $130k-$250k (GS) |
| Principal | JPMorgan *Applied AI ML Executive Director*; Wells Fargo *Principal AI Engineer*; Wells Fargo *Principal Engineer* | 7-12+ years | $159k-$305k (WF) |

Links: [JPM Associate](https://www.oneroadmap.io/jobs/6abd1f8d36c2e1375dc8ec99) · [BofA DS I](https://freehire.me/jobs/ai-engineer-data-scientist-i-bank-of-america-rv3vzgf7) · [Citi VP](https://jobs.citi.com/job/jersey-city/machine-learning-engineer-vice-president/287/89702719056) · [GS VP](https://jobs.wallstreetfriends.org/companies/goldman-sachs/jobs/64776056-engineering-vice-president-ai-ml-engineering) · [GS VP (Richardson)](https://jobs.wallstreetfriends.org/companies/goldman-sachs/jobs/64776396-ai-ml-engineering-dallas-associate) · [JPM Lead](https://zapply.jobs/jobs/bfbe8988-adfe-4454-adaf-fe5ede639e0e/) · [BofA Senior](https://simplify.jobs/p/16fa7177-2344-4201-ad8a-8d4507fd5777/Senior-AI-Engineer) · [JPM ED](https://www.builtinnyc.com/job/applied-ai-ml-executive-director-chief-data-analytics-office/10669590) · [WF Principal AI](https://jobs.anitab.org/companies/wells-fargo/jobs/91419497-principal-ai-engineer) · [WF Principal](https://www.builtinnyc.com/job/principal-engineer/9951411). Several were read on job-board mirrors and some have since closed.

**What separates the levels**

* **Junior:** build and evaluate. Python, statistics, time series, "rigorous evaluation frameworks", deploying and monitoring a model, model cards and audit-ready documentation. Agents and RL are nice-to-have.
* **Senior:** make agents safe in production. Tool-calling agents with guardrails and least-privilege access (Goldman names MCP), evaluation frameworks, validators, fallbacks, circuit breakers, rollbacks, cost and latency, CI/CD, Kubernetes, infrastructure as code.
* **Principal:** make it reusable. Multi-agent platforms, shared frameworks and standards, benchmarks for agents, governance, mentoring, measurable business outcomes.

Nine postings is a sample, not a survey. The matrix in the README (`scripts/make_figures.py`, `HIRING`) is a reading of these nine.

## 5. What v0.7 built in response

| Finding | Built | Where |
|---|---|---|
| Real-time treasury needs intraday visibility in a form supervisors use | BCBS 248 intraday liquidity report for every bank | `atlas.regulatory` |
| Banks' payment AI is forecasting plus fraud/anomaly scoring | Anomaly detection with a rule challenger and leave-one-pattern-out testing | `atlas.detect` |
| SR 26-2: inventory, materiality, effective challenge, monitoring | Model inventory with automated checks and generated model cards | `atlas.governance` |
| Agents with guardrails, least privilege, MCP, evaluation | Read-only tool layer, budgets, hash-chained audit, MCP server, evaluation harness with failing controls | `atlas.agent` |
| Tools must work on a bank's own data | CSV and ISO 20022 ingestion, CLI, API upload, in-browser lab | `atlas.ingest`, `atlas.cli`, `atlas.lab` |
| Synthetic data should be anchored to published facts | Mean payment sizes fitted to Fedwire and FedNow statistics | `atlas.calibration`, `data/public/` |

## 6. Where this goes next (not built)

1. **24/7 days.** Instant rails and tokenized deposits settle on weekends; the twin still runs one business day.
2. **Tokenized-deposit rail** with programmable, atomic settlement, to test whether it reduces intraday liquidity needs.
3. **Agent-to-agent treasury:** a corporate's agent negotiating payment timing with a bank's agent, under limits.
4. **Retrieval over policy documents** (limits, playbooks) so an agent's proposal cites the rule it relies on.
5. **Cloud deployment** of the scoring and tool services (the gap every senior posting names).
