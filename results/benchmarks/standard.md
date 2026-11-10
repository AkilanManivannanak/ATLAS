# NEXUS-PAY benchmark: `standard`

*nexus-pay-bench-v2. 240 runs, all ledger replays verified: **True**. Runtime 180.7s on x86_64 / 2 CPUs / Python 3.13.18 (Linux-6.18.44-fc-v338-x86_64-with-glibc2.39).*

Data: synthetic (NEXUS-PAY generator); not observed financial data. Seeds: [11, 12, 13, 14, 15]. Reference arm: `priority`.

Cells show the mean over seeds; brackets give the 95% bootstrap CI of the paired difference vs the reference arm. Bold = CI excludes zero.

## Stress: `baseline`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `auction_pay_as_bid` | **$3.77M [$-2.20M, $-1.34M]** | **98.57% [+0.99pp, +1.48pp]** | **8.3 min [-1.8 min, -0.5 min]** | 89.2 [0.0, 0.0] | 100% |
| `auction_uniform` | **$3.77M [$-2.20M, $-1.35M]** | **98.57% [+0.99pp, +1.47pp]** | **8.3 min [-1.8 min, -0.5 min]** | 89.2 [0.0, 0.0] | 100% |
| `bilateral` | $5.47M [$0.00M, $0.00M] | 97.33% [+0.00pp, +0.00pp] | 9.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 0% |
| `fifo` | **$5.41M [$-0.16M, $-0.00M]** | **97.40% [+0.00pp, +0.15pp]** | 9.7 min [-0.0 min, 0.5 min] | 89.2 [0.0, 0.0] | 60% |
| `fifo_strict` | $5.50M [$-0.21M, $0.22M] | 97.38% [-0.09pp, +0.25pp] | **10.5 min [0.7 min, 1.4 min]** | 89.2 [0.0, 0.0] | 20% |
| `mpc` | **$3.84M [$-2.52M, $-0.97M]** | **98.37% [+0.49pp, +1.72pp]** | **6.5 min [-4.4 min, -1.3 min]** | **5.2 [-101.6, -66.6]** | 100% |
| `mpc_plus_auction` | **$2.14M [$-4.63M, $-2.50M]** | **99.55% [+1.62pp, +2.93pp]** | **5.0 min [-5.3 min, -3.7 min]** | **1.6 [-108.2, -67.0]** | 100% |
| `mpc_queue_milp` | **$3.86M [$-2.52M, $-0.97M]** | **98.35% [+0.47pp, +1.68pp]** | **6.5 min [-4.2 min, -1.4 min]** | **5.2 [-101.6, -66.6]** | 100% |
| `multilateral` | $5.47M [$0.00M, $0.00M] | 97.33% [+0.00pp, +0.00pp] | 9.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 0% |
| `multilateral_milp` | $5.47M [$0.00M, $0.00M] | 97.33% [+0.00pp, +0.00pp] | 9.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 0% |
| `priority` | $5.47M | 97.33% | 9.5 min | 89.2 | — |
| `rule_rebalancer` | **$3.87M [$-2.55M, $-0.93M]** | **98.36% [+0.46pp, +1.69pp]** | **6.5 min [-4.4 min, -1.3 min]** | **6.6 [-99.6, -66.4]** | 100% |

## Stress: `combined`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `auction_pay_as_bid` | **$4.42M [$-3.17M, $-2.05M]** | **98.87% [+1.66pp, +2.11pp]** | **20.8 min [-2.4 min, -0.1 min]** | 179.8 [0.0, 0.0] | 100% |
| `auction_uniform` | **$4.42M [$-3.18M, $-2.05M]** | **98.87% [+1.66pp, +2.11pp]** | **20.8 min [-2.4 min, -0.1 min]** | 179.8 [0.0, 0.0] | 100% |
| `bilateral` | $6.94M [$0.00M, $0.00M] | 97.03% [+0.00pp, +0.00pp] | 21.9 min [0.0 min, 0.0 min] | 179.8 [0.0, 0.0] | 0% |
| `fifo` | $6.92M [$-0.08M, $0.03M] | **97.06% [+0.00pp, +0.06pp]** | **22.1 min [0.0 min, 0.3 min]** | 179.8 [0.0, 0.0] | 40% |
| `fifo_strict` | **$7.16M [$0.05M, $0.37M]** | 96.95% [-0.22pp, +0.04pp] | **23.0 min [0.5 min, 1.7 min]** | 179.8 [0.0, 0.0] | 20% |
| `mpc` | **$5.68M [$-1.62M, $-0.75M]** | **97.75% [+0.41pp, +1.03pp]** | **18.7 min [-5.8 min, -1.7 min]** | **92.0 [-114.2, -61.4]** | 100% |
| `mpc_plus_auction` | **$3.35M [$-4.36M, $-2.94M]** | **99.39% [+2.04pp, +2.68pp]** | **17.1 min [-7.7 min, -2.2 min]** | **88.4 [-119.8, -63.0]** | 100% |
| `mpc_queue_milp` | **$5.70M [$-1.61M, $-0.76M]** | **97.74% [+0.41pp, +0.98pp]** | **18.6 min [-5.8 min, -1.8 min]** | **91.8 [-114.6, -61.4]** | 100% |
| `multilateral` | $6.94M [$0.00M, $0.00M] | 97.03% [+0.00pp, +0.00pp] | 21.9 min [0.0 min, 0.0 min] | 179.8 [0.0, 0.0] | 0% |
| `multilateral_milp` | $6.94M [$0.00M, $0.00M] | 97.03% [+0.00pp, +0.00pp] | 21.9 min [0.0 min, 0.0 min] | 179.8 [0.0, 0.0] | 0% |
| `priority` | $6.94M | 97.03% | 21.9 min | 179.8 | — |
| `rule_rebalancer` | **$5.58M [$-1.69M, $-0.96M]** | **97.85% [+0.52pp, +1.20pp]** | **18.9 min [-5.6 min, -1.6 min]** | **93.8 [-113.4, -58.6]** | 100% |

## Stress: `counterparty_delay`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `auction_pay_as_bid` | **$4.08M [$-2.20M, $-1.35M]** | **98.57% [+0.99pp, +1.47pp]** | **10.9 min [-1.9 min, -0.6 min]** | 164.4 [0.0, 0.0] | 100% |
| `auction_uniform` | **$4.08M [$-2.20M, $-1.35M]** | **98.57% [+1.00pp, +1.47pp]** | **10.9 min [-1.9 min, -0.6 min]** | 164.4 [0.0, 0.0] | 100% |
| `bilateral` | $5.79M [$0.00M, $0.00M] | 97.33% [+0.00pp, +0.00pp] | 12.1 min [0.0 min, 0.0 min] | 164.4 [0.0, 0.0] | 0% |
| `fifo` | **$5.73M [$-0.14M, $-0.00M]** | **97.40% [+0.00pp, +0.15pp]** | 12.3 min [-0.0 min, 0.5 min] | 164.4 [0.0, 0.0] | 60% |
| `fifo_strict` | $5.82M [$-0.20M, $0.22M] | 97.38% [-0.09pp, +0.26pp] | **13.1 min [0.7 min, 1.4 min]** | 164.4 [0.0, 0.0] | 20% |
| `mpc` | **$4.18M [$-2.45M, $-0.97M]** | **98.34% [+0.47pp, +1.69pp]** | **9.0 min [-4.4 min, -1.4 min]** | **77.2 [-113.0, -61.4]** | 100% |
| `mpc_plus_auction` | **$2.46M [$-4.54M, $-2.51M]** | **99.54% [+1.62pp, +2.92pp]** | **7.6 min [-5.3 min, -3.8 min]** | **74.0 [-119.0, -61.8]** | 100% |
| `mpc_queue_milp` | **$4.22M [$-2.54M, $-0.95M]** | **98.32% [+0.47pp, +1.66pp]** | **9.1 min [-4.3 min, -1.5 min]** | **77.2 [-113.0, -61.4]** | 100% |
| `multilateral` | $5.79M [$0.00M, $0.00M] | 97.33% [+0.00pp, +0.00pp] | 12.1 min [0.0 min, 0.0 min] | 164.4 [0.0, 0.0] | 0% |
| `multilateral_milp` | $5.79M [$0.00M, $0.00M] | 97.33% [+0.00pp, +0.00pp] | 12.1 min [0.0 min, 0.0 min] | 164.4 [0.0, 0.0] | 0% |
| `priority` | $5.79M | 97.33% | 12.1 min | 164.4 | — |
| `rule_rebalancer` | **$4.23M [$-2.48M, $-0.86M]** | **98.32% [+0.39pp, +1.66pp]** | **9.0 min [-4.4 min, -1.5 min]** | **78.6 [-110.8, -61.4]** | 100% |

## Stress: `liquidity_hoarding`

| arm | total cost | LV settled (value) | LV delay (value-wtd) | instant rejected | win rate (cost) |
|---|---|---|---|---|---|
| `auction_pay_as_bid` | **$3.91M [$-2.24M, $-1.51M]** | **98.83% [+1.13pp, +1.53pp]** | 18.9 min [-1.9 min, 0.4 min] | 89.2 [0.0, 0.0] | 100% |
| `auction_uniform` | **$3.91M [$-2.24M, $-1.51M]** | **98.83% [+1.14pp, +1.53pp]** | 18.9 min [-1.9 min, 0.4 min] | 89.2 [0.0, 0.0] | 100% |
| `bilateral` | $5.74M [$0.00M, $0.00M] | 97.49% [+0.00pp, +0.00pp] | 19.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 0% |
| `fifo` | **$5.79M [$0.00M, $0.16M]** | 97.45% [-0.10pp, +0.00pp] | 19.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 20% |
| `fifo_strict` | $5.81M [$-0.10M, $0.24M] | 97.50% [-0.12pp, +0.14pp] | **20.3 min [0.4 min, 1.1 min]** | 89.2 [0.0, 0.0] | 40% |
| `mpc` | **$4.31M [$-2.01M, $-0.71M]** | **98.31% [+0.33pp, +1.27pp]** | **15.8 min [-7.7 min, -1.4 min]** | **4.6 [-102.8, -66.8]** | 100% |
| `mpc_plus_auction` | **$2.55M [$-4.19M, $-2.34M]** | **99.56% [+1.56pp, +2.56pp]** | **15.0 min [-8.3 min, -1.5 min]** | **2.2 [-106.8, -67.2]** | 100% |
| `mpc_queue_milp` | **$4.32M [$-2.02M, $-0.70M]** | **98.31% [+0.36pp, +1.28pp]** | **15.9 min [-7.3 min, -1.4 min]** | **4.6 [-102.8, -66.8]** | 100% |
| `multilateral` | $5.74M [$0.00M, $0.00M] | 97.49% [+0.00pp, +0.00pp] | 19.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 0% |
| `multilateral_milp` | $5.74M [$0.00M, $0.00M] | 97.49% [+0.00pp, +0.00pp] | 19.5 min [0.0 min, 0.0 min] | 89.2 [0.0, 0.0] | 0% |
| `priority` | $5.74M | 97.49% | 19.5 min | 89.2 | — |
| `rule_rebalancer` | **$4.26M [$-2.10M, $-0.73M]** | **98.34% [+0.30pp, +1.31pp]** | **15.9 min [-7.5 min, -1.2 min]** | **4.6 [-104.2, -67.0]** | 100% |
