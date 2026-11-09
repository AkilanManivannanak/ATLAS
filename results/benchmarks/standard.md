# NEXUS-PAY benchmark: `standard`

*nexus-pay-bench-v1. 180 runs, all ledger replays verified: **True**. Runtime 189.2s on x86_64 / 2 CPUs / Python 3.13.18 (Linux-6.18.44-fc-v310-x86_64-with-glibc2.39).*

Data: synthetic (NEXUS-PAY generator); not observed financial data. Seeds: [11, 12, 13, 14, 15]. Reference arm: `priority`.

Cells show the mean over seeds; brackets give the 95% bootstrap CI of the paired difference vs the reference arm. Bold = CI excludes zero.

## Stress: `baseline`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `bilateral` | **$14.49M [$-0.01M, $-0.00M]** | 90.96% [+0.00pp, +0.03pp] | 17.1 min [-0.1 min, 0.1 min] | 48.8 [0.0, 0.0] | 100% |
| `fifo` | $14.51M [$-0.21M, $0.24M] | 90.97% [-0.12pp, +0.18pp] | **17.4 min [0.1 min, 0.7 min]** | 48.8 [0.0, 0.0] | 40% |
| `fifo_strict` | $14.21M [$-1.29M, $0.44M] | 91.51% [-0.03pp, +1.31pp] | **23.5 min [4.0 min, 8.3 min]** | 48.8 [0.0, 0.0] | 60% |
| `mpc` | **$7.60M [$-8.48M, $-5.21M]** | **96.04% [+3.76pp, +6.39pp]** | **13.9 min [-5.8 min, -0.7 min]** | **12.6 [-41.0, -32.4]** | 100% |
| `mpc_queue_milp` | **$7.56M [$-8.76M, $-5.00M]** | **96.07% [+3.82pp, +6.58pp]** | **14.2 min [-5.7 min, -0.1 min]** | **12.4 [-41.4, -32.0]** | 100% |
| `multilateral` | **$14.49M [$-0.01M, $-0.00M]** | 90.96% [+0.00pp, +0.03pp] | 17.1 min [-0.1 min, 0.1 min] | 48.8 [0.0, 0.0] | 100% |
| `multilateral_milp` | **$14.22M [$-0.48M, $-0.08M]** | **91.16% [+0.07pp, +0.35pp]** | 17.1 min [-0.2 min, 0.2 min] | 48.8 [0.0, 0.0] | 100% |
| `priority` | $14.50M | 90.95% | 17.1 min | 48.8 | — |
| `rule_rebalancer` | **$7.61M [$-8.64M, $-5.17M]** | **96.02% [+3.68pp, +6.50pp]** | **14.2 min [-5.3 min, -0.7 min]** | **19.0 [-38.8, -20.8]** | 100% |

## Stress: `combined`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `bilateral` | $17.12M [$-0.32M, $0.08M] | 90.03% [-0.06pp, +0.24pp] | 41.6 min [0.0 min, 0.7 min] | 161.4 [0.0, 0.0] | 20% |
| `fifo` | $17.51M [$-0.21M, $0.84M] | 89.76% [-0.58pp, +0.14pp] | 41.4 min [-0.9 min, 0.9 min] | 161.4 [0.0, 0.0] | 40% |
| `fifo_strict` | $17.27M [$-0.93M, $1.04M] | 90.22% [-0.46pp, +1.10pp] | **45.3 min [2.5 min, 5.9 min]** | 161.4 [0.0, 0.0] | 40% |
| `mpc` | **$10.71M [$-7.87M, $-5.08M]** | **94.62% [+3.57pp, +5.73pp]** | **35.3 min [-9.3 min, -3.3 min]** | **109.0 [-65.8, -38.6]** | 100% |
| `mpc_queue_milp` | **$10.22M [$-8.65M, $-5.31M]** | **95.00% [+3.82pp, +6.29pp]** | **35.5 min [-9.3 min, -3.1 min]** | **109.2 [-65.6, -36.8]** | 100% |
| `multilateral` | $17.10M [$-0.32M, $0.03M] | 90.04% [-0.04pp, +0.24pp] | 41.5 min [-0.1 min, 0.6 min] | 161.4 [0.0, 0.0] | 20% |
| `multilateral_milp` | **$16.61M [$-1.59M, $-0.03M]** | **90.43% [+0.02pp, +1.25pp]** | 41.3 min [-1.2 min, 1.4 min] | 161.4 [0.0, 0.0] | 80% |
| `priority` | $17.20M | 89.97% | 41.3 min | 161.4 | — |
| `rule_rebalancer` | **$10.72M [$-8.27M, $-4.84M]** | **94.67% [+3.44pp, +6.09pp]** | **36.3 min [-8.6 min, -2.3 min]** | **123.4 [-48.8, -27.2]** | 100% |

## Stress: `counterparty_delay`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `bilateral` | **$14.73M [$-0.02M, $-0.00M]** | 91.01% [+0.00pp, +0.03pp] | 21.0 min [-0.1 min, 0.1 min] | 129.8 [0.0, 0.0] | 100% |
| `fifo` | $14.73M [$-0.22M, $0.20M] | 91.02% [-0.12pp, +0.19pp] | 21.2 min [-0.2 min, 0.6 min] | 129.8 [0.0, 0.0] | 60% |
| `fifo_strict` | $14.38M [$-1.32M, $0.25M] | **91.61% [+0.08pp, +1.35pp]** | **27.1 min [3.7 min, 8.4 min]** | 129.8 [0.0, 0.0] | 60% |
| `mpc` | **$7.36M [$-9.03M, $-6.04M]** | **96.45% [+4.33pp, +6.67pp]** | **18.1 min [-6.3 min, -0.1 min]** | **86.2 [-50.8, -32.6]** | 100% |
| `mpc_queue_milp` | **$7.49M [$-8.49M, $-6.04M]** | **96.34% [+4.32pp, +6.53pp]** | **17.9 min [-6.3 min, -0.5 min]** | **85.0 [-54.0, -32.2]** | 100% |
| `multilateral` | **$14.72M [$-0.02M, $-0.00M]** | 91.01% [+0.00pp, +0.03pp] | 21.0 min [-0.2 min, 0.1 min] | 129.8 [0.0, 0.0] | 100% |
| `multilateral_milp` | **$14.47M [$-0.46M, $-0.08M]** | **91.19% [+0.04pp, +0.34pp]** | 21.0 min [-0.2 min, 0.1 min] | 129.8 [0.0, 0.0] | 100% |
| `priority` | $14.74M | 91.00% | 21.1 min | 129.8 | — |
| `rule_rebalancer` | **$7.73M [$-8.60M, $-5.72M]** | **96.18% [+4.17pp, +6.51pp]** | **18.2 min [-6.2 min, -0.3 min]** | **95.2 [-42.8, -25.4]** | 100% |

## Stress: `liquidity_hoarding`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `bilateral` | $15.03M [$-0.21M, $0.00M] | 91.39% [+0.00pp, +0.20pp] | 37.6 min [-0.0 min, 0.5 min] | 48.8 [0.0, 0.0] | 40% |
| `fifo` | $15.31M [$-0.09M, $0.60M] | 91.17% [-0.41pp, +0.04pp] | 37.8 min [-0.4 min, 1.4 min] | 48.8 [0.0, 0.0] | 40% |
| `fifo_strict` | $15.39M [$-0.09M, $0.68M] | 91.34% [-0.25pp, +0.28pp] | **41.2 min [2.1 min, 5.6 min]** | 48.8 [0.0, 0.0] | 40% |
| `mpc` | **$9.96M [$-7.01M, $-3.19M]** | **94.83% [+2.18pp, +4.87pp]** | **30.6 min [-10.6 min, -4.0 min]** | **8.0 [-53.4, -30.6]** | 100% |
| `mpc_queue_milp` | **$9.41M [$-7.44M, $-3.63M]** | **95.23% [+2.57pp, +5.16pp]** | **30.5 min [-10.6 min, -4.0 min]** | **8.2 [-54.4, -30.4]** | 100% |
| `multilateral` | **$15.03M [$-0.20M, $-0.00M]** | 91.39% [+0.00pp, +0.20pp] | 37.6 min [-0.0 min, 0.5 min] | 48.8 [0.0, 0.0] | 60% |
| `multilateral_milp` | $15.11M [$-0.56M, $0.75M] | 91.32% [-0.54pp, +0.44pp] | 37.5 min [-0.5 min, 0.6 min] | 48.8 [0.0, 0.0] | 60% |
| `priority` | $15.12M | 91.31% | 37.4 min | 48.8 | — |
| `rule_rebalancer` | **$9.52M [$-7.66M, $-3.44M]** | **95.16% [+2.38pp, +5.25pp]** | **31.1 min [-10.7 min, -2.9 min]** | **16.8 [-43.6, -20.4]** | 100% |
