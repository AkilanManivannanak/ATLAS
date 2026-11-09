"""NEXUS-PAY synthetic workload generation. All outputs are simulated, never observed data."""

from .nexus_pay import (
    GENERATOR_VERSION,
    RAIL_KINDS,
    NexusPayConfig,
    Scenario,
    ScenarioPayment,
    generate_scenario,
)

__all__ = ["GENERATOR_VERSION", "RAIL_KINDS", "NexusPayConfig", "Scenario", "ScenarioPayment", "generate_scenario"]
