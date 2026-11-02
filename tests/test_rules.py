from datetime import date

import pytest

from atlas.domain.rules import (
    ACCOUNT_AVAILABILITY_RULE,
    DEFAULT_RULE_REGISTRY,
    FinancialRule,
    FinancialRuleRegistry,
    RuleBasis,
    RuleSource,
)


def test_default_registry_is_versioned_and_labels_available_balance_as_assumption():
    item = DEFAULT_RULE_REGISTRY.get("atlas.account.available_resources")
    assert DEFAULT_RULE_REGISTRY.registry_version == "atlas-rules-v1"
    assert item == ACCOUNT_AVAILABILITY_RULE
    assert item.basis is RuleBasis.SIMULATOR_ASSUMPTION


def test_registry_adds_monotonic_versions_without_mutating_old_version():
    v2 = FinancialRule(
        rule_id=ACCOUNT_AVAILABILITY_RULE.rule_id,
        version=2,
        summary="Future explicit version.",
        scope="Test only.",
        basis=RuleBasis.SIMULATOR_ASSUMPTION,
        assumption_rationale="A test entry.",
    )
    updated = DEFAULT_RULE_REGISTRY.add(v2)
    assert DEFAULT_RULE_REGISTRY.get(v2.rule_id).version == 1
    assert updated.get(v2.rule_id).version == 2
    assert updated.get(v2.rule_id, 1).version == 1


def test_duplicate_and_nonincreasing_rule_versions_are_rejected():
    with pytest.raises(ValueError, match="already exists"):
        DEFAULT_RULE_REGISTRY.add(ACCOUNT_AVAILABILITY_RULE)
    old = FinancialRule("r", 2, "v2", "scope", RuleBasis.SIMULATOR_ASSUMPTION, assumption_rationale="reason")
    registry = FinancialRuleRegistry("v1", (old,))
    with pytest.raises(ValueError, match="increase monotonically"):
        registry.add(FinancialRule("r", 1, "v1", "scope", RuleBasis.SIMULATOR_ASSUMPTION, assumption_rationale="reason"))


def test_official_rule_requires_source_with_https_url():
    with pytest.raises(ValueError, match="source reference"):
        FinancialRule("official", 1, "summary", "scope", RuleBasis.OFFICIAL_SOURCE)
    source = RuleSource("src-1", "Official rule page", "https://example.org/rule", date(2026, 1, 1))
    rule = FinancialRule("official", 1, "summary", "scope", RuleBasis.OFFICIAL_SOURCE, source=source)
    assert rule.source.url.startswith("https://")
    with pytest.raises(ValueError, match="HTTPS"):
        RuleSource("src-2", "Bad source", "http://example.org/rule", date(2026, 1, 1))


def test_assumption_requires_rationale_and_cannot_masquerade_as_source_backed():
    with pytest.raises(ValueError, match="rationale"):
        FinancialRule("a", 1, "summary", "scope", RuleBasis.SIMULATOR_ASSUMPTION)
    source = RuleSource("src", "Source", "https://example.org", date(2026, 1, 1))
    with pytest.raises(ValueError, match="must not be presented"):
        FinancialRule("a", 1, "summary", "scope", RuleBasis.SIMULATOR_ASSUMPTION, source=source, assumption_rationale="reason")
