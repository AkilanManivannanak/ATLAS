"""Calibration against public aggregates (``atlas-calibration-v1``). Standard library only.

What published data can and cannot pin down:

* **Can:** the *mean* payment size on Fedwire Funds and FedNow, and the system's daily volume and value.
* **Cannot:** the shape of the size distribution, who pays whom, or intraday timing. Operators publish none of
  these at payment level. The twin's lognormal shape, network and timing therefore remain modelling choices.

``public_calibrated_config`` moves the two size parameters so the generator's mean payment matches the published
means, and reports the twin's scale relative to the real system. Everything else is left as it was.
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import replace
from pathlib import Path

from atlas.scenario import NexusPayConfig, generate_scenario

CALIBRATION_VERSION = "atlas-calibration-v1"
DATA = Path(__file__).resolve().parents[3] / "data" / "public"
RTP_Q1_2026 = {"payments": 128_000_000, "value_usd": 480_000_000_000, "average_usd": 3_750,
               "source": "Federal Reserve Bank of Richmond, Economic Brief 26-28 (Aug 2026)"}
# Embedded copy of the rows used, so calibration also works from an installed wheel or in the browser.
FEDWIRE_2025 = {"year": 2025, "average_value_per_transfer_usd": 5_280_000, "average_daily_volume": 869_187, "average_daily_value_usd": 4_593_069_000_000}
FEDNOW_2026Q3 = {"quarter": "2026Q3", "average_value_per_payment_usd": 58_161, "average_daily_volume": 69_309, "average_daily_value_usd": 4_031_100_000}


def load_public(data_dir: Path | None = None) -> dict:
    d = data_dir or DATA
    out = {"fedwire_annual": [], "fednow_quarterly": [], "rtp": RTP_Q1_2026}
    for key, name in (("fedwire_annual", "fedwire_funds_annual.csv"), ("fednow_quarterly", "fednow_quarterly.csv")):
        p = d / name
        if p.exists():
            with p.open() as fh:
                out[key] = [{k: (float(v) if k not in ("quarter",) else v) for k, v in row.items()} for row in csv.DictReader(fh)]
    return out


def _generated_means(config: NexusPayConfig, seeds=(1, 2, 3)) -> dict:
    lv, inst = [], []
    for s in seeds:
        sc = generate_scenario(config, seed=s)
        lv += [p.amount_minor for p in sc.payments if p.rail in ("rtgs", "lsm")]
        inst += [p.amount_minor for p in sc.payments if p.rail in ("fednow", "rtp")]
    return {"large_value_mean_usd": statistics.fmean(lv) / 100, "large_value_median_usd": statistics.median(lv) / 100,
            "instant_mean_usd": statistics.fmean(inst) / 100 if inst else 0.0, "instant_median_usd": statistics.median(inst) / 100 if inst else 0.0,
            "large_value_per_day": len(lv) / len(seeds), "instant_per_day": len(inst) / len(seeds)}


def instant_target_usd(config: NexusPayConfig) -> float:
    """The twin draws FedNow and RTP sizes from one distribution, so its target is the share-weighted mean."""
    rtp = config.rtp_share_bp / 10_000
    return (1 - rtp) * FEDNOW_2026Q3["average_value_per_payment_usd"] + rtp * RTP_Q1_2026["average_usd"]


def public_calibrated_config(base: NexusPayConfig = NexusPayConfig(), iterations: int = 3) -> NexusPayConfig:
    """Fixed-point fit of the two median parameters to the published means (the generator rounds and caps amounts,
    so the analytic lognormal mean is only the starting point)."""
    lv_target, inst_target = FEDWIRE_2025["average_value_per_transfer_usd"], instant_target_usd(base)
    cfg = replace(base,
                  large_value_median_minor=int(lv_target * 100 / math.exp((base.large_value_sigma_milli / 1000) ** 2 / 2)),
                  instant_median_minor=int(inst_target * 100 / math.exp((base.instant_sigma_milli / 1000) ** 2 / 2)))
    for _ in range(iterations):
        g = _generated_means(cfg)
        cfg = replace(cfg, large_value_median_minor=int(cfg.large_value_median_minor * lv_target / g["large_value_mean_usd"]),
                      instant_median_minor=int(cfg.instant_median_minor * inst_target / g["instant_mean_usd"]))
    return cfg


def calibration_report(default: NexusPayConfig = NexusPayConfig()) -> dict:
    cal = public_calibrated_config(default)
    g0, g1 = _generated_means(default, seeds=(11, 12, 13, 14, 15)), _generated_means(cal, seeds=(11, 12, 13, 14, 15))
    lv_t, in_t = FEDWIRE_2025["average_value_per_transfer_usd"], instant_target_usd(default)
    err = lambda got, want: round((got / want - 1) * 100, 1)
    return {
        "version": CALIBRATION_VERSION,
        "targets": {"fedwire_mean_usd": lv_t, "fedwire_source_year": 2025, "instant_blended_mean_usd": round(in_t),
                    "fednow_mean_usd": FEDNOW_2026Q3["average_value_per_payment_usd"], "rtp_mean_usd": RTP_Q1_2026["average_usd"]},
        "default": {"large_value_mean_usd": round(g0["large_value_mean_usd"]), "large_value_error_pct": err(g0["large_value_mean_usd"], lv_t),
                    "instant_mean_usd": round(g0["instant_mean_usd"]), "instant_error_pct": err(g0["instant_mean_usd"], in_t)},
        "calibrated": {"large_value_median_minor": cal.large_value_median_minor, "instant_median_minor": cal.instant_median_minor,
                       "large_value_mean_usd": round(g1["large_value_mean_usd"]), "large_value_error_pct": err(g1["large_value_mean_usd"], lv_t),
                       "instant_mean_usd": round(g1["instant_mean_usd"]), "instant_error_pct": err(g1["instant_mean_usd"], in_t)},
        "scale": {"twin_large_value_payments_per_day": round(g1["large_value_per_day"]), "fedwire_transfers_per_day": FEDWIRE_2025["average_daily_volume"],
                  "one_twin_payment_represents": round(FEDWIRE_2025["average_daily_volume"] / g1["large_value_per_day"]),
                  "twin_institutions": default.n_institutions},
        "not_identified_by_public_data": ["payment-size distribution shape (only the mean is published)", "bilateral network (who pays whom)",
                                          "intraday timing of submissions", "bank-level opening balances and credit lines",
                                          "separate FedNow and RTP size distributions (the twin uses one)"],
    }
