"""Immutable collateral inventory, mobilization, allocation, and stress operations."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from atlas.domain import CollateralAsset, FinancialEvent, FundingFacility


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _positive_minor_units(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be positive integer minor units")


def _financial_event(
    *, event_id: str, event_type: str, aggregate_id: str, aggregate_type: str,
    at: datetime, sequence_number: int, simulation_id: str, correlation_id: str,
    payload: dict[str, object], causation_id: str | None = None,
) -> FinancialEvent:
    return FinancialEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        event_at=at,
        ingested_at=at,
        sequence_number=sequence_number,
        correlation_id=correlation_id,
        simulation_id=simulation_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        causation_id=causation_id,
    )


class MobilizationStatus(StrEnum):
    UNMOBILIZED = "unmobilized"
    PENDING = "pending"
    MOBILIZED = "mobilized"


@dataclass(frozen=True, slots=True)
class CollateralRequirement:
    requirement_id: str
    maximum_advance_rate_basis_points: int
    eligible_profile_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.requirement_id, str) or not self.requirement_id.strip():
            raise ValueError("requirement_id is required")
        if (
            not isinstance(self.maximum_advance_rate_basis_points, int)
            or isinstance(self.maximum_advance_rate_basis_points, bool)
            or not 1 <= self.maximum_advance_rate_basis_points <= 10_000
        ):
            raise ValueError("maximum advance rate must be integer basis points from 1 through 10000")
        if not isinstance(self.eligible_profile_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.eligible_profile_ids
        ):
            raise ValueError("eligible profile identifiers must be non-empty strings in a tuple")
        if len(set(self.eligible_profile_ids)) != len(self.eligible_profile_ids):
            raise ValueError("eligible profile identifiers must be unique")

    def required_collateral_minor(self, draw_minor: int) -> int:
        if not isinstance(draw_minor, int) or isinstance(draw_minor, bool) or draw_minor < 0:
            raise ValueError("draw amount must be a non-negative integer minor-unit amount")
        if draw_minor == 0:
            return 0
        numerator = draw_minor * 10_000
        return (numerator + self.maximum_advance_rate_basis_points - 1) // self.maximum_advance_rate_basis_points


@dataclass(frozen=True, slots=True)
class CollateralPosition:
    asset: CollateralAsset
    mobilization_status: MobilizationStatus = MobilizationStatus.UNMOBILIZED
    mobilization_requested_at: datetime | None = None
    available_at: datetime | None = None
    mobilized_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.asset, CollateralAsset):
            raise TypeError("asset must be a CollateralAsset")
        if not isinstance(self.mobilization_status, MobilizationStatus):
            raise TypeError("mobilization_status must be a MobilizationStatus")
        if self.mobilization_status == MobilizationStatus.UNMOBILIZED:
            if any(value is not None for value in (self.mobilization_requested_at, self.available_at, self.mobilized_at)):
                raise ValueError("unmobilized collateral cannot have mobilization timestamps")
        elif self.mobilization_status == MobilizationStatus.PENDING:
            if self.mobilization_requested_at is None or self.available_at is None or self.mobilized_at is not None:
                raise ValueError("pending collateral requires request and availability timestamps only")
        elif self.mobilization_status == MobilizationStatus.MOBILIZED:
            if self.mobilization_requested_at is None or self.available_at is None or self.mobilized_at is None:
                raise ValueError("mobilized collateral requires request, availability, and completion timestamps")
        for name in ("mobilization_requested_at", "available_at", "mobilized_at"):
            value = getattr(self, name)
            if value is not None:
                _instant(value)
        if self.mobilization_requested_at and self.available_at:
            if _instant(self.available_at) < _instant(self.mobilization_requested_at):
                raise ValueError("collateral availability cannot precede mobilization request")
        if self.available_at and self.mobilized_at:
            if _instant(self.mobilized_at) < _instant(self.available_at):
                raise ValueError("collateral cannot mobilize before its availability time")

    @property
    def available_eligible_value_minor(self) -> int:
        if self.mobilization_status != MobilizationStatus.MOBILIZED:
            return 0
        return self.asset.available_eligible_value_minor

    @property
    def collateral_shortfall_minor(self) -> int:
        return self.asset.collateral_shortfall_minor


@dataclass(frozen=True, slots=True)
class CollateralAllocation:
    allocation_id: str
    asset_id: str
    facility_id: str
    requirement_id: str
    eligible_value_minor: int
    released_value_minor: int
    allocated_at: datetime

    def __post_init__(self) -> None:
        for name in ("allocation_id", "asset_id", "facility_id", "requirement_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        _positive_minor_units(self.eligible_value_minor, "eligible_value_minor")
        if not isinstance(self.released_value_minor, int) or isinstance(self.released_value_minor, bool):
            raise TypeError("released_value_minor must be an integer")
        if not 0 <= self.released_value_minor <= self.eligible_value_minor:
            raise ValueError("released value must be between zero and the allocated value")
        _instant(self.allocated_at)

    @property
    def remaining_value_minor(self) -> int:
        return self.eligible_value_minor - self.released_value_minor


@dataclass(frozen=True, slots=True)
class CollateralStressScenario:
    scenario_id: str
    additional_haircut_basis_points: int = 0
    additional_mobilization_delay_seconds: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ValueError("scenario_id is required")
        for value, name in (
            (self.additional_haircut_basis_points, "additional_haircut_basis_points"),
            (self.additional_mobilization_delay_seconds, "additional_mobilization_delay_seconds"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CollateralOperation:
    inventory: CollateralInventory
    event: FinancialEvent


@dataclass(frozen=True, slots=True)
class CollateralInventory:
    positions: tuple[CollateralPosition, ...] = ()
    allocations: tuple[CollateralAllocation, ...] = ()

    def __post_init__(self) -> None:
        asset_ids = [position.asset.collateral_id for position in self.positions]
        allocation_ids = [allocation.allocation_id for allocation in self.allocations]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("collateral inventory contains duplicate asset identifiers")
        if len(allocation_ids) != len(set(allocation_ids)):
            raise ValueError("collateral inventory contains duplicate allocation identifiers")
        positions = {position.asset.collateral_id: position for position in self.positions}
        totals: dict[str, int] = {}
        for allocation in self.allocations:
            position = positions.get(allocation.asset_id)
            if position is None:
                raise ValueError("collateral allocation references an unknown asset")
            if allocation.remaining_value_minor and position.mobilization_status != MobilizationStatus.MOBILIZED:
                raise ValueError("active collateral allocations require a mobilized asset")
            totals[allocation.asset_id] = totals.get(allocation.asset_id, 0) + allocation.remaining_value_minor
        for asset_id, position in positions.items():
            if position.asset.encumbered_amount_minor != totals.get(asset_id, 0):
                raise ValueError("asset encumbrance must equal the sum of active allocations")

    def add_asset(self, asset: CollateralAsset) -> CollateralInventory:
        if any(position.asset.collateral_id == asset.collateral_id for position in self.positions):
            raise ValueError(f"duplicate collateral asset: {asset.collateral_id}")
        if asset.encumbered_amount_minor:
            raise ValueError("pre-encumbered collateral must be loaded with allocation records")
        return replace(self, positions=(*self.positions, CollateralPosition(asset)))

    def position(self, asset_id: str) -> CollateralPosition:
        for position in self.positions:
            if position.asset.collateral_id == asset_id:
                return position
        raise KeyError(f"unknown collateral asset: {asset_id}")

    def allocated_value_minor(self, facility_id: str, requirement_id: str) -> int:
        value = 0
        for position in self.positions:
            allocations = [item for item in self.allocations if item.asset_id == position.asset.collateral_id]
            total_pledged = sum(item.remaining_value_minor for item in allocations)
            if total_pledged == 0:
                continue
            effective_total = min(total_pledged, position.asset.eligible_value_minor)
            value += sum(
                item.remaining_value_minor * effective_total // total_pledged
                for item in allocations
                if item.facility_id == facility_id and item.requirement_id == requirement_id
            )
        return value

    def _replace_position(self, updated: CollateralPosition) -> CollateralInventory:
        return replace(
            self,
            positions=tuple(updated if item.asset.collateral_id == updated.asset.collateral_id else item for item in self.positions),
        )

    def request_mobilization(
        self, asset_id: str, *, at: datetime, event_id: str, sequence_number: int,
        simulation_id: str, correlation_id: str,
    ) -> CollateralOperation:
        _instant(at)
        position = self.position(asset_id)
        if position.mobilization_status != MobilizationStatus.UNMOBILIZED:
            raise ValueError("collateral must be unmobilized to request mobilization")
        if position.asset.encumbered_amount_minor:
            raise ValueError("encumbered collateral cannot be remobilized")
        if _instant(at) < _instant(position.asset.valuation_at):
            raise ValueError("mobilization cannot precede the current valuation")
        available_at = at + timedelta(seconds=position.asset.mobilization_delay_seconds)
        updated = replace(
            position,
            mobilization_status=MobilizationStatus.PENDING,
            mobilization_requested_at=at,
            available_at=available_at,
        )
        inventory = self._replace_position(updated)
        event = _financial_event(
            event_id=event_id, event_type="CollateralMobilizationRequested", aggregate_id=asset_id,
            aggregate_type="collateral", at=at, sequence_number=sequence_number,
            simulation_id=simulation_id, correlation_id=correlation_id,
            payload={"asset_id": asset_id, "available_at": available_at.isoformat(), "delay_seconds": position.asset.mobilization_delay_seconds},
        )
        return CollateralOperation(inventory, event)

    def complete_mobilization(
        self, asset_id: str, *, at: datetime, event_id: str, sequence_number: int,
        simulation_id: str, correlation_id: str, causation_id: str | None = None,
    ) -> CollateralOperation:
        _instant(at)
        position = self.position(asset_id)
        if position.mobilization_status != MobilizationStatus.PENDING or position.available_at is None:
            raise ValueError("collateral has no pending mobilization")
        if _instant(at) < _instant(position.available_at):
            raise ValueError("collateral mobilization delay has not elapsed")
        updated = replace(position, mobilization_status=MobilizationStatus.MOBILIZED, mobilized_at=at)
        inventory = self._replace_position(updated)
        event = _financial_event(
            event_id=event_id, event_type="CollateralMobilized", aggregate_id=asset_id,
            aggregate_type="collateral", at=at, sequence_number=sequence_number,
            simulation_id=simulation_id, correlation_id=correlation_id,
            payload={"asset_id": asset_id, "eligible_value_minor": position.asset.eligible_value_minor},
            causation_id=causation_id,
        )
        return CollateralOperation(inventory, event)

    def allocate(
        self, asset_id: str, facility: FundingFacility, requirement: CollateralRequirement,
        amount_minor: int, *, allocation_id: str, at: datetime, event_id: str,
        sequence_number: int, simulation_id: str, correlation_id: str,
    ) -> CollateralOperation:
        _positive_minor_units(amount_minor, "allocation amount")
        _instant(at)
        if not isinstance(facility, FundingFacility) or not isinstance(requirement, CollateralRequirement):
            raise TypeError("facility and requirement must use their domain record types")
        if not facility.eligibility_status:
            raise ValueError("funding facility is not eligible")
        if facility.maturity_at is not None and _instant(at) >= _instant(facility.maturity_at):
            raise ValueError("collateral cannot be allocated to a facility at or past maturity")
        if facility.collateral_requirements_id != requirement.requirement_id:
            raise ValueError("collateral requirement does not match facility")
        position = self.position(asset_id)
        asset = position.asset
        if position.mobilization_status != MobilizationStatus.MOBILIZED:
            raise ValueError("collateral must be mobilized before allocation")
        if asset.owner_institution_id != facility.institution_id:
            raise ValueError("collateral owner and facility institution must match")
        if asset.currency != facility.currency:
            raise ValueError("collateral and facility currencies must match")
        if requirement.eligible_profile_ids and asset.eligibility_profile_id not in requirement.eligible_profile_ids:
            raise ValueError("collateral eligibility profile is not allowed by requirement")
        if _instant(at) < _instant(position.mobilized_at):
            raise ValueError("collateral allocation cannot precede mobilization")
        if amount_minor > position.available_eligible_value_minor:
            raise ValueError("allocation exceeds available eligible collateral")
        if any(item.allocation_id == allocation_id for item in self.allocations):
            raise ValueError(f"duplicate collateral allocation: {allocation_id}")
        allocation = CollateralAllocation(
            allocation_id, asset_id, facility.facility_id, requirement.requirement_id,
            amount_minor, 0, at,
        )
        updated_asset = replace(asset, encumbered_amount_minor=asset.encumbered_amount_minor + amount_minor)
        updated_position = replace(position, asset=updated_asset)
        inventory = replace(
            self,
            positions=tuple(updated_position if item.asset.collateral_id == asset_id else item for item in self.positions),
            allocations=(*self.allocations, allocation),
        )
        event = _financial_event(
            event_id=event_id, event_type="CollateralEncumbered", aggregate_id=asset_id,
            aggregate_type="collateral", at=at, sequence_number=sequence_number,
            simulation_id=simulation_id, correlation_id=correlation_id,
            payload={"allocation_id": allocation_id, "asset_id": asset_id, "facility_id": facility.facility_id, "eligible_value_minor": amount_minor, "requirement_id": requirement.requirement_id},
        )
        return CollateralOperation(inventory, event)

    def release(
        self, allocation_id: str, amount_minor: int, *, facility: FundingFacility,
        requirement: CollateralRequirement, at: datetime, event_id: str,
        sequence_number: int, simulation_id: str, correlation_id: str,
    ) -> CollateralOperation:
        _positive_minor_units(amount_minor, "release amount")
        _instant(at)
        if not isinstance(facility, FundingFacility) or not isinstance(requirement, CollateralRequirement):
            raise TypeError("facility and requirement must use their domain record types")
        allocation_index = next((i for i, item in enumerate(self.allocations) if item.allocation_id == allocation_id), None)
        if allocation_index is None:
            raise KeyError(f"unknown collateral allocation: {allocation_id}")
        allocation = self.allocations[allocation_index]
        if facility.facility_id != allocation.facility_id or requirement.requirement_id != allocation.requirement_id:
            raise ValueError("facility and collateral requirement must match allocation")
        if amount_minor > allocation.remaining_value_minor:
            raise ValueError("release exceeds remaining allocation")
        position = self.position(allocation.asset_id)
        if position.mobilization_status != MobilizationStatus.MOBILIZED:
            raise ValueError("collateral must remain mobilized while encumbered")
        updated_asset = replace(
            position.asset,
            encumbered_amount_minor=position.asset.encumbered_amount_minor - amount_minor,
        )
        updated_allocation = replace(
            allocation, released_value_minor=allocation.released_value_minor + amount_minor
        )
        allocations = list(self.allocations)
        allocations[allocation_index] = updated_allocation
        updated_position = replace(position, asset=updated_asset)
        inventory = replace(
            self,
            positions=tuple(updated_position if item.asset.collateral_id == allocation.asset_id else item for item in self.positions),
            allocations=tuple(allocations),
        )
        required = requirement.required_collateral_minor(facility.drawn_amount_minor)
        remaining_coverage = inventory.allocated_value_minor(facility.facility_id, requirement.requirement_id)
        if remaining_coverage < required:
            raise ValueError("release would leave the outstanding facility draw undercollateralized")
        event = _financial_event(
            event_id=event_id, event_type="CollateralReleased", aggregate_id=allocation.asset_id,
            aggregate_type="collateral", at=at, sequence_number=sequence_number,
            simulation_id=simulation_id, correlation_id=correlation_id,
            payload={"allocation_id": allocation_id, "asset_id": allocation.asset_id, "facility_id": allocation.facility_id, "released_value_minor": amount_minor, "remaining_value_minor": updated_allocation.remaining_value_minor},
        )
        return CollateralOperation(inventory, event)

    def revalue(
        self, asset_id: str, market_value_minor: int, *, at: datetime, event_id: str,
        sequence_number: int, simulation_id: str, correlation_id: str,
    ) -> CollateralOperation:
        if not isinstance(market_value_minor, int) or isinstance(market_value_minor, bool) or market_value_minor < 0:
            raise ValueError("market value must be a non-negative integer minor-unit amount")
        _instant(at)
        position = self.position(asset_id)
        if _instant(at) < _instant(position.asset.valuation_at):
            raise ValueError("collateral valuation timestamp cannot move backward")
        updated_asset = replace(position.asset, market_value_minor=market_value_minor, valuation_at=at)
        updated_position = replace(position, asset=updated_asset)
        inventory = self._replace_position(updated_position)
        event = _financial_event(
            event_id=event_id, event_type="CollateralRevalued", aggregate_id=asset_id,
            aggregate_type="collateral", at=at, sequence_number=sequence_number,
            simulation_id=simulation_id, correlation_id=correlation_id,
            payload={"asset_id": asset_id, "market_value_before_minor": position.asset.market_value_minor, "market_value_after_minor": market_value_minor, "eligible_value_before_minor": position.asset.eligible_value_minor, "eligible_value_after_minor": updated_asset.eligible_value_minor, "collateral_shortfall_minor": updated_position.collateral_shortfall_minor},
        )
        return CollateralOperation(inventory, event)

    def apply_stress(
        self, asset_id: str, scenario: CollateralStressScenario, *, at: datetime,
        event_id: str, sequence_number: int, simulation_id: str, correlation_id: str,
    ) -> CollateralOperation:
        if not isinstance(scenario, CollateralStressScenario):
            raise TypeError("scenario must be a CollateralStressScenario")
        _instant(at)
        position = self.position(asset_id)
        if _instant(at) < _instant(position.asset.valuation_at):
            raise ValueError("collateral stress cannot precede the current valuation")
        old_haircut = position.asset.haircut_basis_points
        new_haircut = min(10_000, old_haircut + scenario.additional_haircut_basis_points)
        updated_asset = replace(
            position.asset,
            haircut_basis_points=new_haircut,
            mobilization_delay_seconds=position.asset.mobilization_delay_seconds + scenario.additional_mobilization_delay_seconds,
        )
        available_at = position.available_at
        if position.mobilization_status == MobilizationStatus.PENDING and scenario.additional_mobilization_delay_seconds:
            available_at = available_at + timedelta(seconds=scenario.additional_mobilization_delay_seconds)
        updated_position = replace(position, asset=updated_asset, available_at=available_at)
        inventory = self._replace_position(updated_position)
        event = _financial_event(
            event_id=event_id, event_type="CollateralStressApplied", aggregate_id=asset_id,
            aggregate_type="collateral", at=at, sequence_number=sequence_number,
            simulation_id=simulation_id, correlation_id=correlation_id,
            payload={"asset_id": asset_id, "scenario_id": scenario.scenario_id, "haircut_before_basis_points": old_haircut, "haircut_after_basis_points": new_haircut, "available_at": available_at.isoformat() if available_at else None, "collateral_shortfall_minor": updated_position.collateral_shortfall_minor},
        )
        return CollateralOperation(inventory, event)


__all__ = [
    "CollateralAllocation", "CollateralInventory", "CollateralOperation", "CollateralPosition",
    "CollateralRequirement", "CollateralStressScenario", "MobilizationStatus",
]
