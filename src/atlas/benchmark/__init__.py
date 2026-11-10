"""NEXUS-PAY benchmark: reproducible policy x stress x seed experiments with paired statistics."""

from .runner import BENCHMARK_VERSION, POLICY_ARMS, PRESETS, BenchmarkConfig, paired_comparison, run_benchmark, write_report

__all__ = ["BENCHMARK_VERSION", "POLICY_ARMS", "PRESETS", "BenchmarkConfig", "cost_sensitivity", "paired_comparison", "reweight_cost", "run_benchmark", "write_report"]
