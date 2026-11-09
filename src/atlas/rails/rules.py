"""Evidence registry for modeled rail facts and explicit simulator assumptions."""

from datetime import date

from atlas.domain import FinancialRule, FinancialRuleRegistry, RuleBasis, RuleSource

RETRIEVED_ON = date(2026, 11, 1)

FEDWIRE_SOURCE = RuleSource(
    "fedwire-operating-hours",
    "Fedwire Funds Service and National Settlement Service Operating Hours",
    "https://www.frbservices.org/resources/financial-services/wires/fedwire-funds-service-national-settlement-service-operating-hours/",
    RETRIEVED_ON,
)
FEDWIRE_EXPANSION_SOURCE = RuleSource(
    "fedwire-operating-days-expansion",
    "Fedwire Funds Service and National Settlement Service Resource Center",
    "https://www.frbservices.org/resources/financial-services/wires/fedwire-funds-service-national-settlement-service-resource-center/",
    RETRIEVED_ON,
)
CHIPS_SOURCE = RuleSource(
    "chips-overview",
    "CHIPS payment system overview",
    "https://www.theclearinghouse.org/payment-systems/chips",
    RETRIEVED_ON,
)
FEDNOW_SOURCE = RuleSource(
    "fednow-operating-hours",
    "FedNow Service Operating Hours",
    "https://www.frbservices.org/resources/financial-services/fednow-service-resources/fednow-service-operating-hours/",
    RETRIEVED_ON,
)
RTP_SOURCE = RuleSource(
    "rtp-overview",
    "Real Time Payments Network overview",
    "https://www.theclearinghouse.org/payment-systems/rtp",
    RETRIEVED_ON,
)

RAIL_RULES = FinancialRuleRegistry(
    "atlas-rail-rules-v1",
    (
        FinancialRule(
            "atlas.rail.rtgs.public_window_source", 1,
            "The referenced public schedule describes Fedwire service hours from 9 p.m. ET on the preceding calendar day to 7 p.m. ET on a funds-transfer business day.",
            "Public operating-hours fact used to inform an RTGS archetype; calendar and exception handling remain configurable.",
            RuleBasis.OFFICIAL_SOURCE, source=FEDWIRE_SOURCE,
        ),
        FinancialRule(
            "atlas.rail.rtgs.schedule_model", 1,
            "The model uses a configurable overnight local-time window, weekday set, and explicit holiday dates.",
            "This does not encode Federal Reserve holiday calendars, extensions, cutoff distinctions, or future operating-day changes.",
            RuleBasis.SIMULATOR_ASSUMPTION,
            assumption_rationale="A small deterministic calendar interface avoids silently claiming production schedule coverage.",
        ),
        FinancialRule(
            "atlas.rail.rtgs.announced_operating_day_expansion", 1,
            "The Federal Reserve has announced an intended expansion of Fedwire Funds Service and National Settlement Service operating days to Sunday through Friday, including weekday holidays, targeted for 2028 or 2029; participant use is expected to be voluntary.",
            "The implementation timing and participant adoption are future events. This reference model leaves days and holidays configurable and does not assume the expansion is active.",
            RuleBasis.OFFICIAL_SOURCE, source=FEDWIRE_EXPANSION_SOURCE,
        ),
        FinancialRule(
            "atlas.rail.lsm.public_principle_source", 1,
            "The referenced CHIPS overview describes continuous intraday settlement and liquidity-saving matching and offsetting.",
            "Public high-level description only; proprietary mechanisms are not reproduced.",
            RuleBasis.OFFICIAL_SOURCE, source=CHIPS_SOURCE,
        ),
        FinancialRule(
            "atlas.rail.lsm.atomic_net_cycle", 1,
            "A submitted cycle settles atomically only when each participant account can cover its positive net debit in unreserved cash.",
            "All-or-nothing cycle-level netting; no bilateral algorithm, liquidity contribution, or proprietary optimization is modeled.",
            RuleBasis.SIMULATOR_ASSUMPTION,
            assumption_rationale="A transparent conservation-preserving baseline provides a testable liquidity-saving mechanism.",
        ),
        FinancialRule(
            "atlas.rail.fednow.continuous_cycle_source", 1,
            "The service operates continuously, with an accounting funds-transfer business-day rollover at approximately 7:01 p.m. ET.",
            "The model uses a configurable local rollover clock; it does not model all LMT windows or Federal Reserve exception procedures.",
            RuleBasis.OFFICIAL_SOURCE, source=FEDNOW_SOURCE,
        ),
        FinancialRule(
            "atlas.rail.fednow.instant_cash_model", 1,
            "Instant settlement is available at all times unless a scenario injects an outage; the cycle date is accounting metadata only.",
            "Participant availability, liquidity management transfers, and exact service procedures are simplified.",
            RuleBasis.SIMULATOR_ASSUMPTION,
            assumption_rationale="A continuous clock and explicit outage switch support reproducible scenario tests without implying network connectivity.",
        ),
        FinancialRule(
            "atlas.rail.rtp.continuous_source", 1,
            "The referenced RTP overview describes around-the-clock instant payment availability, including weekends and holidays.",
            "The model does not encode proprietary service rules or assert participant connectivity.",
            RuleBasis.OFFICIAL_SOURCE, source=RTP_SOURCE,
        ),
        FinancialRule(
            "atlas.rail.rtp.participant_limits", 1,
            "RTP-model participant eligibility and transaction limits are explicit local configuration, independently set for each participant.",
            "No network transaction limit or participant list is hard-coded from a changing public page.",
            RuleBasis.SIMULATOR_ASSUMPTION,
            assumption_rationale="Versioned local inputs keep the model reproducible and distinguish configurable constraints from sourced facts.",
        ),
    ),
)


__all__ = ["FEDNOW_SOURCE", "FEDWIRE_EXPANSION_SOURCE", "FEDWIRE_SOURCE", "CHIPS_SOURCE", "RAIL_RULES", "RETRIEVED_ON", "RTP_SOURCE"]
