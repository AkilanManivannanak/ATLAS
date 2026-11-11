# FedNow on a shared master account vs a separate pool

Seeds (11, 12, 13, 14, 15), standard scenario, 5 arms x 3 stresses x 2 account models; all ledgers replay-verified: separate=True, shared=True. 95% paired bootstrap CIs.

## Separate FedNow pool: cost vs priority queue / vs rule-based treasury

| Stress | Arm | Cost vs priority | Cost vs rule-based | Instant rejected |
|---|---|---|---|---|
| baseline | priority | ref | $+1.61M [$+0.89M, $+2.55M] | 89.2 |
| baseline | rule_rebalancer | -29% | ref | 6.6 |
| baseline | mpc | -30% | $-0.02M [$-0.18M, $+0.13M] n.s. | 5.2 |
| baseline | auction_uniform | -31% | $-0.09M [$-0.53M, $+0.35M] n.s. | 89.2 |
| baseline | mpc_plus_auction | -61% | $-1.72M [$-2.14M, $-1.30M] | 1.6 |
| liquidity_hoarding | priority | ref | $+1.48M [$+0.73M, $+2.09M] | 89.2 |
| liquidity_hoarding | rule_rebalancer | -26% | ref | 4.6 |
| liquidity_hoarding | mpc | -25% | $+0.05M [$+0.01M, $+0.09M] | 4.6 |
| liquidity_hoarding | auction_uniform | -32% | $-0.35M [$-0.89M, $+0.11M] n.s. | 89.2 |
| liquidity_hoarding | mpc_plus_auction | -56% | $-1.71M [$-2.12M, $-1.34M] | 2.2 |
| combined | priority | ref | $+1.36M [$+0.96M, $+1.69M] | 179.8 |
| combined | rule_rebalancer | -20% | ref | 93.8 |
| combined | mpc | -18% | $+0.10M [$-0.05M, $+0.26M] n.s. | 92.0 |
| combined | auction_uniform | -36% | $-1.16M [$-1.86M, $-0.46M] | 179.8 |
| combined | mpc_plus_auction | -52% | $-2.23M [$-2.87M, $-1.62M] | 88.4 |

## Shared FedNow pool: cost vs priority queue / vs rule-based treasury

| Stress | Arm | Cost vs priority | Cost vs rule-based | Instant rejected |
|---|---|---|---|---|
| baseline | priority | ref | $+1.55M [$+0.97M, $+2.30M] | 30.4 |
| baseline | rule_rebalancer | -29% | ref | 3.8 |
| baseline | mpc | -28% | $+0.05M [$-0.03M, $+0.11M] n.s. | 6.0 |
| baseline | auction_uniform | -30% | $-0.08M [$-0.52M, $+0.38M] n.s. | 47.6 |
| baseline | mpc_plus_auction | -59% | $-1.60M [$-2.02M, $-1.19M] | 12.4 |
| liquidity_hoarding | priority | ref | $+1.46M [$+0.81M, $+2.04M] | 30.2 |
| liquidity_hoarding | rule_rebalancer | -25% | ref | 3.2 |
| liquidity_hoarding | mpc | -24% | $+0.05M [$-0.03M, $+0.16M] n.s. | 6.6 |
| liquidity_hoarding | auction_uniform | -33% | $-0.42M [$-0.94M, $+0.02M] n.s. | 38.4 |
| liquidity_hoarding | mpc_plus_auction | -54% | $-1.63M [$-2.17M, $-1.20M] | 8.6 |
| combined | priority | ref | $+1.41M [$+1.02M, $+1.72M] | 117.6 |
| combined | rule_rebalancer | -20% | ref | 91.6 |
| combined | mpc | -18% | $+0.13M [$+0.07M, $+0.21M] | 93.6 |
| combined | auction_uniform | -37% | $-1.13M [$-1.74M, $-0.50M] | 132.4 |
| combined | mpc_plus_auction | -51% | $-2.11M [$-2.72M, $-1.50M] | 100.4 |

## Effect of switching to the shared master account (same arm, same seeds)

| Stress | Arm | Cost change | Instant rejected: separate -> shared |
|---|---|---|---|
| baseline | priority | $-0.10M [$-0.23M, $-0.02M] | 89.2 -> 30.4 |
| baseline | rule_rebalancer | $-0.04M [$-0.21M, $+0.10M] n.s. | 6.6 -> 3.8 |
| baseline | mpc | $+0.03M [$-0.02M, $+0.09M] n.s. | 5.2 -> 6.0 |
| baseline | auction_uniform | $-0.03M [$-0.04M, $-0.03M] | 89.2 -> 47.6 |
| baseline | mpc_plus_auction | $+0.08M [$+0.01M, $+0.19M] | 1.6 -> 12.4 |
| liquidity_hoarding | priority | $+0.02M [$-0.02M, $+0.09M] n.s. | 89.2 -> 30.2 |
| liquidity_hoarding | rule_rebalancer | $+0.04M [$-0.03M, $+0.10M] n.s. | 4.6 -> 3.2 |
| liquidity_hoarding | mpc | $+0.04M [$-0.02M, $+0.10M] n.s. | 4.6 -> 6.6 |
| liquidity_hoarding | auction_uniform | $-0.04M [$-0.05M, $-0.02M] | 89.2 -> 38.4 |
| liquidity_hoarding | mpc_plus_auction | $+0.12M [$+0.00M, $+0.23M] | 2.2 -> 8.6 |
| combined | priority | $-0.04M [$-0.05M, $-0.02M] | 179.8 -> 117.6 |
| combined | rule_rebalancer | $-0.09M [$-0.16M, $-0.03M] | 93.8 -> 91.6 |
| combined | mpc | $-0.06M [$-0.15M, $+0.03M] n.s. | 92.0 -> 93.6 |
| combined | auction_uniform | $-0.05M [$-0.10M, $-0.02M] | 179.8 -> 132.4 |
| combined | mpc_plus_auction | $+0.03M [$-0.13M, $+0.17M] n.s. | 88.4 -> 100.4 |

Runtime 148.0 s.
