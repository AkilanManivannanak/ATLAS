"""Funding facility draw, repayment, and exact simple-interest operations."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from atlas.domain import AccountStatus, FinancialEvent, FundingFacility, SettlementAccount

from .collateral import CollateralInventory, CollateralRequirement


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_minor_units(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be positive integer minor units")


def _event(
    *, event_id: str, event_type: str, facility: FundingFacility, at: datetime,
    sequence_number: int, simulation_id: str, correlation_id: str,
    payload: dict[str, object], causation_id: str | None,
) -> FinancialEvent:
    return FinancialEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=facility.facility_id,
        aggregate_type="funding_facility",
        event_at=at,
        ingested_at=at,
        sequence_number=sequence_number,
        correlation_id=correlation_id,
        simulation_id=simulation_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        causation_id=causation_id,
    )


@dataclass(frozen=True, slots=True)
class FundingOperation:
    facility: FundingFacility
    account: SettlementAccount
    event: FinancialEvent


@dataclass(frozen=True, slots=True)
class FundingCost:
    principal_minor: int
    annual_rate_basis_points: int
    elapsed_seconds: int
    day_count_basis_seconds: int
    cost_minor: int


def calculate_simple_funding_cost(
    principal_minor: int,
    annual_rate_basis_points: int,
    elapsed_seconds: int,
    *,
    day_count_basis_seconds: int = 365 * 24 * 60 * 60,
) -> FundingCost:
    """Calculate simple interest in minor units, rounding any fraction upward."""
    _positive_minor_units(principal_minor, "principal")
    for value, name in (
        (annual_rate_basis_points, "annual rate"),
        (elapsed_seconds, "elapsed seconds"),
        (day_count_basis_seconds, "day-count basis"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if day_count_basis_seconds == 0:
        raise ValueError("day-count basis must be positive")
    numerator = principal_minor * annual_rate_basis_points * elapsed_seconds
    denominator = 10_000 * day_count_basis_seconds
    cost = (numerator + denominator - 1) // denominator
    return FundingCost(
        principal_minor, annual_rate_basis_points, elapsed_seconds,
        day_count_basis_seconds, cost,
    )


def draw_funding(
    facility: FundingFacility,
    account: SettlementAccount,
    amount_minor: int,
    *,
    at: datetime,
    event_id: str,
    sequence_number: int,
    simulation_id: str,
    correlation_id: str,
    collateral_inventory: CollateralInventory | None = None,
    collateral_requirement: CollateralRequirement | None = None,
    causation_id: str | None = None,
) -> FundingOperation:
    _positive_minor_units(amount_minor, "draw amount")
    _instant(at)
    if not facility.eligibility_status:
        raise ValueError("funding facility is not eligible")
    if account.account_status != AccountStatus.ACTIVE:
        raise ValueError("funding account must be active")
    if account.institution_id != facility.institution_id:
        raise ValueError("funding facility and account institutions must match")
    if account.currency != facility.currency:
        raise ValueError("funding facility and account currencies must match")
    if facility.maturity_at is not None and _instant(at) >= _instant(facility.maturity_at):
        raise ValueError("funding facility is at or past maturity")
    if amount_minor > facility.available_capacity_minor:
        raise ValueError("draw exceeds committed facility capacity")
    if facility.collateral_requirements_id is None:
        if collateral_requirement is not None:
            raise ValueError("facility does not specify a collateral requirement")
    else:
        if not isinstance(collateral_inventory, CollateralInventory):
            raise ValueError("collateralized facility draw requires a collateral inventory")
        if not isinstance(collateral_requirement, CollateralRequirement):
            raise ValueError("collateralized facility draw requires its collateral requirement")
        if collateral_requirement.requirement_id != facility.collateral_requirements_id:
            raise ValueError("collateral requirement does not match facility")
        required = collateral_requirement.required_collateral_minor(amount_minor)
        allocated = collateral_inventory.allocated_value_minor(facility.facility_id, collateral_requirement.requirement_id)
        if allocated < required:
            raise ValueError("allocated eligible collateral does not cover requested draw")

    next_facility = replace(
        facility,
        drawn_amount_minor=facility.drawn_amount_minor + amount_minor,
        repayable_amount_minor=facility.repayable_amount_minor + amount_minor,
    )
    next_account = replace(account, ledger_balance_minor=account.ledger_balance_minor + amount_minor)
    payload = {
        "facility_id": facility.facility_id,
        "institution_id": facility.institution_id,
        "account_id": account.account_id,
        "currency": facility.currency,
        "amount_minor": amount_minor,
        "drawn_before_minor": facility.drawn_amount_minor,
        "drawn_after_minor": next_facility.drawn_amount_minor,
        "repayable_before_minor": facility.repayable_amount_minor,
        "repayable_after_minor": next_facility.repayable_amount_minor,
        "account_ledger_before_minor": account.ledger_balance_minor,
        "account_ledger_after_minor": next_account.ledger_balance_minor,
        "collateral_requirement_id": facility.collateral_requirements_id,
    }
    event = _event(
        event_id=event_id, event_type="FundingDrawn", facility=facility, at=at,
        sequence_number=sequence_number, simulation_id=simulation_id,
        correlation_id=correlation_id, payload=payload, causation_id=causation_id,
    )
    return FundingOperation(next_facility, next_account, event)


def repay_funding(
    facility: FundingFacility,
    account: SettlementAccount,
    amount_minor: int,
    *,
    at: datetime,
    event_id: str,
    sequence_number: int,
    simulation_id: str,
    correlation_id: str,
    causation_id: str | None = None,
) -> FundingOperation:
    _positive_minor_units(amount_minor, "repayment amount")
    _instant(at)
    if account.account_status != AccountStatus.ACTIVE:
        raise ValueError("funding account must be active")
    if account.institution_id != facility.institution_id or account.currency != facility.currency:
        raise ValueError("funding facility and account institution and currency must match")
    if amount_minor > facility.repayable_amount_minor or amount_minor > facility.drawn_amount_minor:
        raise ValueError("repayment exceeds outstanding repayable principal")
    if account.cash_available_minor < amount_minor:
        raise ValueError("insufficient unreserved cash for funding repayment")
    next_facility = replace(
        facility,
        drawn_amount_minor=facility.drawn_amount_minor - amount_minor,
        repayable_amount_minor=facility.repayable_amount_minor - amount_minor,
    )
    next_account = replace(account, ledger_balance_minor=account.ledger_balance_minor - amount_minor)
    payload = {
        "facility_id": facility.facility_id,
        "institution_id": facility.institution_id,
        "account_id": account.account_id,
        "currency": facility.currency,
        "amount_minor": amount_minor,
        "drawn_before_minor": facility.drawn_amount_minor,
        "drawn_after_minor": next_facility.drawn_amount_minor,
        "repayable_before_minor": facility.repayable_amount_minor,
        "repayable_after_minor": next_facility.repayable_amount_minor,
        "account_ledger_before_minor": account.ledger_balance_minor,
        "account_ledger_after_minor": next_account.ledger_balance_minor,
    }
    event = _event(
        event_id=event_id, event_type="FundingRepaid", facility=facility, at=at,
        sequence_number=sequence_number, simulation_id=simulation_id,
        correlation_id=correlation_id, payload=payload, causation_id=causation_id,
    )
    return FundingOperation(next_facility, next_account, event)


__all__ = ["FundingCost", "FundingOperation", "calculate_simple_funding_cost", "draw_funding", "repay_funding"]
