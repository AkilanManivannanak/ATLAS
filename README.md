<div align="center">

# ATLAS-Σ

### A working model of how US banks settle payments with each other, and what AI can safely do about it

[![ci](https://github.com/AkilanManivannanak/ATLAS/actions/workflows/ci.yml/badge.svg)](https://github.com/AkilanManivannanak/ATLAS/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.12%20%7C%203.13-2a78d6)
![tests](https://img.shields.io/badge/tests-216%20passing-1baf7a)
![replay](https://img.shields.io/badge/every%20run-replay--verified-1baf7a)
![deps](https://img.shields.io/badge/simulator%20core-zero%20dependencies-2a78d6)

## [🚀 Open the live app](https://atlas-sigma.streamlit.app) &nbsp;·&nbsp; [▶ Browser lab](https://akilanmanivannanak.github.io/ATLAS/lab.html) &nbsp;·&nbsp; [📊 Explore the results](https://akilanmanivannanak.github.io/ATLAS/) &nbsp;·&nbsp; [⭐ Review it](https://github.com/AkilanManivannanak/ATLAS/issues/new?template=review.yml)

<img src="docs/assets/app.gif" alt="ATLAS app: payments flowing between twelve banks as particles, banks turning amber and red as payments queue, then the day re-run on today's real funding-market readings" width="100%">

<sub>Payments travel between banks as particles; a bank turns red when more is waiting to leave than it has liquidity. <a href="docs/assets/atlas_demo.mp4">▶ Full 2.5-minute tour (mp4)</a></sub>

</div>

## 👥 Real users

| Who | Role | ★ | What they said |
|---|---|---|---|
| *first reviews arriving this week* | | | [watch it live on the Team page →](https://atlas-sigma.streamlit.app/team) |

<sub>Every name here used the live app themselves; their actions are in the app's hash-chained activity log.</sub>

> Simulated banks on real market conditions. SOFR, EFFR, reverse-repo take-up and the Treasury General Account come live from the New York Fed and the US Treasury. The rails are models of Fedwire, CHIPS, FedNow and RTP; they are not connected to those systems and cannot move money.

<table>
<tr>
<td width="25%" align="center"><h2>−61%</h2>cost of a settlement day<br><sub>treasury optimiser + liquidity auction vs a plain queue</sub></td>
<td width="25%" align="center"><h2>4 live feeds</h2>set the day's liquidity<br><sub>NY Fed + US Treasury, freshness checked on every load</sub></td>
<td width="25%" align="center"><h2>63 / 75</h2>real frauds caught<br><sub>reviewing 0.5% of 284,807 real card transactions</sub></td>
<td width="25%" align="center"><h2>0</h2>tools that can execute anything<br><sub>agents analyse and propose; people decide</sub></td>
</tr>
</table>

---

## Ten pages, one bank-operations desk

<table>
<tr>
<td width="50%"><img src="docs/assets/app_market.png" alt="Live funding market page"><br><b>📈 Live market</b> · today's SOFR, EFFR, RRP and TGA, a reserve-tightness gauge, and a slider that replays any past market day (quarter-end included) through the simulator.</td>
<td width="50%"><img src="docs/assets/app_stress.png" alt="Stress lab page"><br><b>🧪 Stress lab</b> · eleven things that go wrong, two responses on the same payments, a liquidity sweep, and a <b>reverse stress test</b> that bisects for the breaking point.</td>
</tr>
<tr>
<td><img src="docs/assets/app_alerts.png" alt="Alerts and cases page"><br><b>🗂️ Alerts & cases</b> · ranked unusual payments, a case file with evidence and a narrative built only from ledger figures, and Clear / Escalate / File report decisions saved for the whole team.</td>
<td><img src="docs/assets/app_team.png" alt="Team page"><br><b>👥 Team</b> · everyone on the deployment shares a hash-chained activity log, case decisions and reviews. Export it as JSON at any time.</td>
</tr>
</table>

| Page | What you do there | What it shows a hiring manager |
|---|---|---|
| 🏛️ Command center | Pick a day or press **⚡ Today's market**, watch it settle (pause, replay, 1×/3×/10×, click a bank) | Event-sourced simulation, replay-verified ledger |
| 📈 Live market | Read four public feeds, replay any past day | Data engineering: schema checks, freshness SLOs, fallback with provenance |
| 🧪 Stress lab | Break it, compare fixes, find the breaking point | Stress and reverse stress testing, MPC, auctions |
| 📄 Your payments | Upload a CSV, see every rejected row and assumption | Ingestion that never silently repairs data |
| 🗂️ Alerts & cases | Triage, read evidence, decide | Human-in-the-loop AML/fraud operations |
| 🛡️ Controls | BCBS 248 report, tamper with the ledger | Supervisory reporting, tamper evidence |
| ⚖️ Model risk | Filter models by pass / warn / fail | SR 26-2 inventory, challengers, validation checks |
| 🤖 Agent | Watch the router pick read-only tools, ask your own question | Tool-using agent, grounding checks, refusal, audit chain, optional LLM |
| 📊 Evidence | 1,320 simulated days, real fraud data, deep learning | Paired statistics, honest splits, failing controls |
| 👥 Team | See who did what, leave a review | Multi-user product, tamper-evident activity |

Three colour schemes (navy & crimson, ocean & bronze, crimson & gold) sit at the bottom of the sidebar.

---

## Try it with your team, then tell me what broke

1. Open **[atlas-sigma.streamlit.app](https://atlas-sigma.streamlit.app)**, put your name in the sidebar.
2. Press **⚡ Today's market** on the Command center and watch the day.
3. On **Alerts & cases**, decide three cases. Your teammates see your decisions.
4. On **Team → Reviews**, leave stars and one thing that broke.

| | |
|---|---|
| **Live app** | [atlas-sigma.streamlit.app](https://atlas-sigma.streamlit.app) |
| **Run locally** | `pip install -r requirements.txt && streamlit run streamlit_app.py` |
| **No install** | [browser lab](https://akilanmanivannanak.github.io/ATLAS/lab.html) |
| **Public review** | [open the review form](https://github.com/AkilanManivannanak/ATLAS/issues/new?template=review.yml) · [read the reviews](https://github.com/AkilanManivannanak/ATLAS/issues?q=label%3Areview) |

<details>
<summary><b>Put the app online (Streamlit Community Cloud, free)</b></summary>

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
2. *Create app* → repository `AkilanManivannanak/ATLAS`, branch `main`, main file `streamlit_app.py`.
3. *Advanced settings* → Python 3.12 → *Deploy*.

No secrets needed to run. To make the team workspace survive redeploys (so returning users are remembered), create a free Supabase project, copy its **Session pooler** connection string, and add it in the app's *Settings → Secrets* as `ATLAS_DB_URL = "postgresql://..."`. Without it the workspace is a local SQLite file that a redeploy resets.
</details>

---

## Use it on your own payments

<table>
<tr>
<td width="33%" valign="top">

**🌐 In the browser**

Open the [live lab](https://akilanmanivannanak.github.io/ATLAS/lab.html) → *My payments* → drop a CSV.

Needs four columns: `sender, receiver, amount, time`.

</td>
<td width="33%" valign="top">

**⌨️ From a terminal**

```bash
pip install -e ".[ml]"
atlas template > day.csv
atlas run --payments day.csv \
  --stress combined --out report/
```
Also reads ISO 20022 `pacs.008` / `pacs.009`.

</td>
<td width="33%" valign="top">

**🤖 From an AI agent (MCP)**

```json
{"mcpServers": {"atlas": {
  "command": "atlas",
  "args": ["mcp", "--payments", "day.csv"]
}}}
```
Nine read-only tools. Every call is logged to a hash chain.

</td>
</tr>
</table>

You get back: what settled and what did not, each bank's intraday liquidity in the form supervisors monitor (BCBS 248), unusual payments ranked for review, and a ledger you can replay. Anything the tool had to assume about your data is listed, and bad rows are rejected with a reason, never silently fixed.

---

## How it works

```mermaid
flowchart LR
    IN["Your payments file<br/>or a synthetic day"] --> DAY
    ST["11 stress scenarios"] --> DAY
    subgraph DAY["One business day, four rails"]
        direction TB
        R1["RTGS"] ~~~ R2["Liquidity-saving"] ~~~ R3["FedNow"] ~~~ R4["RTP"]
    end
    subgraph AI["Decision layer"]
        direction TB
        F["Forecasts"] --> C["Treasury controller<br/>rules · MPC · safe RL"]
        AU["Liquidity auction"]
        AG["AI agent tools · MCP"]
    end
    C --> SAFE{"Safety check<br/>fail-closed"} --> DAY
    AU --> DAY
    DAY --> L["Ledger<br/>SHA-256 hash chain"] --> RP["Replay = same state hash"]
    L --> OUT["BCBS 248 report · alerts · statements"]
    L --> AG
    MRM["Model inventory<br/>automated validation"] -.checks.-> F & C
```

---

## What it found

### Two liquidity problems, two fixes

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/policy-cost-dark.svg">
  <img alt="Modeled daily cost by policy on normal and stressed days" src="docs/assets/policy-cost-light.svg" width="100%">
</picture>

Cash sits on the **wrong rail** and at the **wrong bank**. Fixing either helps; fixing both cuts cost 61%. A clever optimiser alone only ties a simple rule.

### It holds on every kind of bad day

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/replication-dark.svg">
  <img alt="Cost change versus the priority queue for five policies across eleven stress scenarios" src="docs/assets/replication-light.svg" width="100%">
</picture>

### Liquidity, the way a supervisor reads it

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/intraday-liquidity-dark.svg">
  <img alt="Each bank's peak intraday liquidity usage on a normal and a stressed day, and payment throughput by hour" src="docs/assets/intraday-liquidity-light.svg" width="100%">
</picture>

### Catching unusual payments

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/anomaly-detection-dark.svg">
  <img alt="Share of injected incidents caught by a hand-written rule, an isolation forest and a supervised model, by incident type" src="docs/assets/anomaly-detection-light.svg" width="100%">
</picture>

On the twin, incidents are injected: a trained model catches 77% of the patterns it has seen and at most 13% of ones it has not, so rules stay in place next to it.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/real-fraud-dark.svg">
  <img alt="Real frauds caught by four detectors on the ULB credit card dataset, and the same model scored on a time-ordered versus a shuffled split" src="docs/assets/real-fraud-light.svg" width="100%">
</picture>

On real labels (card fraud, a different domain), the same method catches 63 of 75 frauds while reviewing 0.5% of transactions. Testing on a shuffled split instead of the future would have flattered the model.

### Every model gets checked, and some fail

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/model-risk-dark.svg">
  <img alt="Model inventory with validation checks: three models pass, four warn, three fail" src="docs/assets/model-risk-light.svg" width="100%">
</picture>

The inventory follows the 2026 US model-risk guidance (SR 26-2). The failures are real and left visible: [model cards](docs/model_cards/README.md).

### An agent evaluation that can say no

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/agent-evals-dark.svg">
  <img alt="Three agents scored on tool use, correctness, grounding and safety; the two broken control agents fail" src="docs/assets/agent-evals-light.svg" width="100%">
</picture>

Fifteen tasks, including prompt injection and a request far beyond the budget. No language model is bundled: point `atlas evals --llm`, or the app's Agent page, at any OpenAI-compatible endpoint.

### Deep learning, held to the same test

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/deep-forecasting-dark.svg">
  <img alt="Forecast error of a GRU and a Transformer against ridge and gradient boosting, and their training curves" src="docs/assets/deep-forecasting-light.svg" width="100%">
</picture>

A GRU trained in PyTorch is the best forecaster here, about 6% ahead of ridge. A modest gain, reported as one.

<details>
<summary><b>More results: safe RL · auction incentives · forecasting · scaling · calibration · netting</b></summary>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/safe-rl-dark.svg">
  <img alt="Safety rejections during training fall to zero; held-out cost matches MPC" src="docs/assets/safe-rl-light.svg" width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/auction-incentives-dark.svg">
  <img alt="A lender's profit change when it inflates its ask: pay-as-bid rewards it, uniform price does not" src="docs/assets/auction-incentives-light.svg" width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/calibration-dark.svg">
  <img alt="Mean payment size in the twin against published Fedwire and FedNow figures" src="docs/assets/calibration-light.svg" width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/forecasting-dark.svg">
  <img alt="Forecast accuracy by model and interval coverage under distribution shift" src="docs/assets/forecasting-light.svg" width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/scaling-dark.svg">
  <img alt="Simulation and replay time versus number of payments, up to 100 banks" src="docs/assets/scaling-light.svg" width="80%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/netting-gap-dark.svg">
  <img alt="Gap to the optimal netting solution by queue size" src="docs/assets/netting-gap-light.svg" width="80%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/intraday-dark.svg">
  <img alt="Value waiting to settle during a stressed day under two treasuries" src="docs/assets/intraday-light.svg" width="100%">
</picture>

</details>

---

## Built against what banks are hiring for

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hiring-map-dark.svg">
  <img alt="Skills asked for in nine bank AI/ML job postings by level, and where the project shows each one" src="docs/assets/hiring-map-light.svg" width="100%">
</picture>

Based on fourteen current postings, from graduate programme to director, and the banks' own AI announcements: [industry landscape and sources](docs/25_industry_landscape.md).

---

## The Command Center

<img src="docs/assets/demo.gif" alt="Command Center walkthrough: network graph, rails, stress lab, optimisation, decision center and audit replay" width="100%">

<details>
<summary><b>Run everything locally</b></summary>

```bash
python3 -m venv .venv && source .venv/bin/activate          # Python 3.12+
pip install -r requirements-lock.txt && pip install --no-deps -e .
pytest -q                                                   # 199 tests
streamlit run streamlit_app.py                              # app  → http://localhost:8501
atlas run --stress combined --controller mpc --auction uniform
uvicorn atlas.api.app:app --port 8000                       # API  → http://localhost:8000/docs
cd frontend && npm ci && npm run dev                        # UI   → http://localhost:3000
```
Or `docker compose up --build`.
</details>

<details>
<summary><b>Reproduce every number</b></summary>

```bash
python -m atlas.benchmark --preset standard     # policy comparison, 240 runs
python -m atlas.benchmark --preset extended     # 11 stresses, 1,320 runs
python scripts/anomaly_study.py                 # anomaly detection
python -m atlas.agent.evals                     # agent evaluation
python scripts/deep_forecast_study.py           # GRU and Transformer training (needs torch)
python scripts/retrieval_study.py               # rulebook retrieval
python scripts/real_fraud_study.py              # detectors on real card fraud (downloads about 100 MB)
python scripts/train_tool_router.py             # tool-routing language model (needs torch)
./scripts/eval_local_llm.sh                     # score a real LLM through a local Ollama
python scripts/calibration_study.py             # published-statistics calibration
python scripts/build_model_inventory.py         # model inventory + cards
python scripts/auction_study.py && python scripts/train_safe_rl.py && python scripts/generate_research_artifacts.py && python scripts/scaling_study.py
python scripts/make_figures.py && python scripts/build_site.py
```
</details>

<details>
<summary><b>What is real and what is not</b></summary>

| Real | Modeled or assumed |
|---|---|
| FedNow and RTP $10M limits, the Fed daylight-overdraft fee formula, ISO 20022 message formats, BCBS 248 definitions | Who pays whom, payment timing and the shape of payment sizes (operators publish none of these) |
| Mean payment size matched to published Fedwire and FedNow statistics | Cost weights (checked under 27 alternatives) |
| 492 confirmed card frauds in 284,807 transactions (detector validation only) | Fraud typologies on the twin's own payments |
| Your own file, if you supply one | Opening balances and credit lines when your file does not include them |

- No bank has used this, and there are no published reviews yet. The [review form](https://github.com/AkilanManivannanak/ATLAS/issues/new?template=review.yml) is how that changes.
- On the twin, anomaly labels are injected. Real labelled fraud is used only in the card-fraud study, which is a different domain.
- No general-purpose language model has been evaluated: none was reachable where this was built. `./scripts/eval_local_llm.sh` scores one with a local Ollama. A small language model trained here routes questions, and it loses to simpler baselines.
- Kubernetes manifests and the hosted-inference contract exist but have not been deployed to a cluster or a cloud account. Training ran on CPU; the GPU path is untested.

Full list: [limitations](docs/20_known_limitations.md) · [realism and sources](docs/23_realism_and_calibration.md)
</details>

<details>
<summary><b>Repository map</b></summary>

```text
streamlit_app.py   the interactive app
src/atlas/   sim · rails · ledger · store · iso20022 · scenario · settlement · market · stress · network
             control (safety, MPC, safe RL) · forecast (classical + PyTorch) · detect · regulatory · governance
             agent (tools, MCP, evals) · knowledge (retrieval) · ingest · calibration · insight · lab · cli · api
deploy/k8s/  Kubernetes manifests
frontend/    Next.js Command Center          site/  results explorer + live lab (built by CI)
results/     every artifact behind every figure    docs/  specifications 01-25, model cards
data/public/ published Fed statistics used for calibration
```
</details>

---

<sub>Docs: [results](docs/19_experimental_results.md) · [architecture](docs/03_system_architecture.md) · [glossary](docs/24_glossary.md) · [decisions](DECISIONS.md) · Cite via [`CITATION.cff`](CITATION.cff) · © Akilan Manivannan. All rights reserved.</sub>
