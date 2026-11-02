# Project charter

ATLAS-Σ is a research platform for reproducible simulation of synthetic financial infrastructure. The research objective is to study how heterogeneous payment mechanisms and participant liquidity strategies affect settlement efficiency and resilience.

## Scope and boundaries

The initial product is a local research simulator. It has no bank connection, payment execution, production decisioning, or claims of live network integration. Synthetic scenarios must be labeled as simulated. Settlement validity is determined by explicit deterministic code and configured rules.

## Delivery approach

Build a modular monolith. Establish domain correctness and reproducibility before infrastructure scale, machine learning, optimization, or a product dashboard. Each increment must have acceptance criteria, tests, documented assumptions, and honest limitations.
