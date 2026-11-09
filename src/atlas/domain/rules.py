"""Versioned source and assumption registry for simulator rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from urllib.parse import urlparse


class RuleBasis(StrEnum):
    OFFICIAL_SOURCE = "official_source"
    SIMULATOR_ASSUMPTION = "simulator_assumption"


@dataclass(frozen=True, slots=True)
class RuleSource:
    source_id: str
    title: str
    url: str
    retrieved_on: date
    published_on: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not isinstance(self.title, str):
            raise TypeError("source id and title must be strings")
        if not self.source_id.strip() or not self.title.strip():
            raise ValueError("source id and title are required")
        if not isinstance(self.url, str):
            raise TypeError("source URL must be a string")
        if not isinstance(self.retrieved_on, date) or (self.published_on is not None and not isinstance(self.published_on, date)):
            raise TypeError("source publication and retrieval dates must be dates")
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source URL must be an absolute HTTPS URL")


@dataclass(frozen=True, slots=True)
class FinancialRule:
    rule_id: str
    version: int
    summary: str
    scope: str
    basis: RuleBasis
    source: RuleSource | None = None
    assumption_rationale: str | None = None
    effective_from: date | None = None

    def __post_init__(self) -> None:
        for field_name in ("rule_id", "summary", "scope"):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} must be a string")
        if not isinstance(self.basis, RuleBasis):
            raise TypeError("rule basis must be a RuleBasis value")
        if not self.rule_id.strip() or not self.summary.strip() or not self.scope.strip():
            raise ValueError("rule id, summary, and scope are required")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version <= 0:
            raise ValueError("rule version must be a positive integer")
        if self.source is not None and not isinstance(self.source, RuleSource):
            raise TypeError("source must be a RuleSource value")
        if self.effective_from is not None and not isinstance(self.effective_from, date):
            raise TypeError("effective_from must be a date")
        if self.basis == RuleBasis.OFFICIAL_SOURCE and self.source is None:
            raise ValueError("official-source rules require a source reference")
        if self.basis == RuleBasis.SIMULATOR_ASSUMPTION:
            if self.source is not None:
                raise ValueError("simulator assumptions must not be presented as official sources")
            if not self.assumption_rationale or not self.assumption_rationale.strip():
                raise ValueError("simulator assumptions require a rationale")


@dataclass(frozen=True, slots=True)
class FinancialRuleRegistry:
    registry_version: str
    rules: tuple[FinancialRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.registry_version, str) or not self.registry_version.strip():
            raise ValueError("rule registry version is required")
        if not isinstance(self.rules, tuple):
            raise TypeError("rule registry rules must be an immutable tuple")
        keys = [(rule.rule_id, rule.version) for rule in self.rules]
        if len(keys) != len(set(keys)):
            raise ValueError("rule registry contains duplicate rule versions")

    def add(self, rule: FinancialRule) -> FinancialRuleRegistry:
        if any((item.rule_id, item.version) == (rule.rule_id, rule.version) for item in self.rules):
            raise ValueError(f"rule {rule.rule_id} version {rule.version} already exists")
        existing = [item.version for item in self.rules if item.rule_id == rule.rule_id]
        if existing and rule.version <= max(existing):
            raise ValueError("new rule versions must increase monotonically")
        return FinancialRuleRegistry(self.registry_version, (*self.rules, rule))

    def get(self, rule_id: str, version: int | None = None) -> FinancialRule:
        matches = [item for item in self.rules if item.rule_id == rule_id and (version is None or item.version == version)]
        if not matches:
            raise KeyError(f"rule {rule_id!r} version {version!r} is not registered")
        return max(matches, key=lambda item: item.version)


ACCOUNT_AVAILABILITY_RULE = FinancialRule(
    rule_id="atlas.account.available_resources",
    version=1,
    summary="Available resources equal ledger cash less reservations plus undrawn account credit.",
    scope="Simulator account resource calculation; not a payment-system rule.",
    basis=RuleBasis.SIMULATOR_ASSUMPTION,
    assumption_rationale=(
        "A transparent initial accounting convention. Credit becomes available only within a configured account limit; "
        "it is not booked as cash until a separate facility draw is modeled."
    ),
)

DEFAULT_RULE_REGISTRY = FinancialRuleRegistry(
    registry_version="atlas-rules-v1",
    rules=(ACCOUNT_AVAILABILITY_RULE,),
)
