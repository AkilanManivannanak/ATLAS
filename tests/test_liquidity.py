from datetime import datetime, timedelta, timezone

import pytest

from atlas.domain import AccountStatus, CollateralAsset, FundingFacility, SettlementAccount
from atlas.liquidity import (
    CollateralInventory,
    CollateralRequirement,
    CollateralStressScenario,
    MobilizationStatus,
    calculate_simple_funding_cost,
    draw_funding,
    repay_funding,
)


NOW = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)


def asset(**changes):
    fields = dict(
        collateral_id="security-1",
        owner_institution_id="bank-a",
        asset_type="government_security",
        nominal_value_minor=10_000,
        market_value_minor=10_000,
        haircut_basis_points=1_000,
        currency="USD",
        encumbered_amount_minor=0,
        eligibility_profile_id="treasury-v1",
        mobilization_delay_seconds=60,
        valuation_at=NOW,
    )
    fields.update(changes)
    return CollateralAsset(**fields)


def facility(**changes):
    fields = dict(
        facility_id="facility-1",
        institution_id="bank-a",
        facility_type="secured_intraday",
        currency="USD",
        maximum_capacity_minor=10_000,
        committed_capacity_minor=10_000,
        drawn_amount_minor=0,
        repayable_amount_minor=0,
        annual_rate_basis_points=500,
        collateral_requirements_id="collateral-rule-v1",
        operating_hours_id="hours-test-v1",
        maturity_at=NOW + timedelta(days=2),
        eligibility_status=True,
    )
    fields.update(changes)
    return FundingFacility(**fields)


def account(**changes):
    fields = dict(
        account_id="settlement-a",
        institution_id="bank-a",
        payment_rail_id="rtgs-model",
        currency="USD",
        ledger_balance_minor=100,
        account_status=AccountStatus.ACTIVE,
    )
    fields.update(changes)
    return SettlementAccount(**fields)


def mobilized_inventory(collateral_asset=None):
    inventory = CollateralInventory().add_asset(collateral_asset or asset())
    pending = inventory.request_mobilization(
        "security-1", at=NOW, event_id="mobilization-requested", sequence_number=0,
        simulation_id="sim-1", correlation_id="corr-1",
    )
    ready_at = NOW + timedelta(seconds=60)
    completed = pending.inventory.complete_mobilization(
        "security-1", at=ready_at, event_id="mobilized", sequence_number=1,
        simulation_id="sim-1", correlation_id="corr-1", causation_id="mobilization-requested",
    )
    return completed.inventory


def test_collateral_mobilization_waits_for_configured_delay_then_emits_transition_events():
    inventory = CollateralInventory().add_asset(asset())
    request = inventory.request_mobilization(
        "security-1", at=NOW, event_id="request", sequence_number=0,
        simulation_id="sim-1", correlation_id="corr-1",
    )
    assert request.inventory.position("security-1").mobilization_status == MobilizationStatus.PENDING
    assert request.inventory.position("security-1").available_eligible_value_minor == 0
    assert request.event.event_type == "CollateralMobilizationRequested"
    with pytest.raises(ValueError, match="delay has not elapsed"):
        request.inventory.complete_mobilization(
            "security-1", at=NOW + timedelta(seconds=59), event_id="early", sequence_number=1,
            simulation_id="sim-1", correlation_id="corr-1",
        )
    completed = request.inventory.complete_mobilization(
        "security-1", at=NOW + timedelta(seconds=60), event_id="complete", sequence_number=1,
        simulation_id="sim-1", correlation_id="corr-1", causation_id="request",
    )
    assert completed.inventory.position("security-1").available_eligible_value_minor == 9_000
    assert completed.event.causation_id == "request"


def test_collateral_allocation_prevents_double_pledging_and_release_is_partial():
    inventory = mobilized_inventory()
    requirement = CollateralRequirement("collateral-rule-v1", 7_500, ("treasury-v1",))
    allocated = inventory.allocate(
        "security-1", facility(), requirement, 9_000, allocation_id="allocation-1",
        at=NOW + timedelta(seconds=60), event_id="encumbered", sequence_number=2,
        simulation_id="sim-1", correlation_id="corr-1",
    )
    assert allocated.event.event_type == "CollateralEncumbered"
    assert allocated.inventory.position("security-1").asset.available_eligible_value_minor == 0
    with pytest.raises(ValueError, match="exceeds available eligible"):
        allocated.inventory.allocate(
            "security-1", facility(), requirement, 1, allocation_id="allocation-2",
            at=NOW + timedelta(seconds=60), event_id="encumbered-again", sequence_number=3,
            simulation_id="sim-1", correlation_id="corr-1",
        )
    released = allocated.inventory.release(
        "allocation-1", 2_000, facility=facility(), requirement=requirement,
        at=NOW + timedelta(seconds=61), event_id="released",
        sequence_number=3, simulation_id="sim-1", correlation_id="corr-1",
    )
    assert released.inventory.position("security-1").asset.encumbered_amount_minor == 7_000
    assert released.inventory.allocated_value_minor("facility-1", "collateral-rule-v1") == 7_000

    third_party = mobilized_inventory(asset(owner_institution_id="bank-b"))
    with pytest.raises(ValueError, match="owner and facility institution"):
        third_party.allocate(
            "security-1", facility(), requirement, 1, allocation_id="third-party-allocation",
            at=NOW + timedelta(seconds=60), event_id="third-party-pledge", sequence_number=4,
            simulation_id="sim-1", correlation_id="corr-1",
        )


def test_stress_increases_haircut_and_delay_and_revaluation_reports_collateral_shortfall():
    inventory = CollateralInventory().add_asset(asset())
    request = inventory.request_mobilization(
        "security-1", at=NOW, event_id="request", sequence_number=0,
        simulation_id="sim-1", correlation_id="corr-1",
    )
    stressed = request.inventory.apply_stress(
        "security-1", CollateralStressScenario("severe", 2_000, 3_600), at=NOW,
        event_id="stress", sequence_number=1, simulation_id="sim-1", correlation_id="corr-1",
    )
    position = stressed.inventory.position("security-1")
    assert position.asset.haircut_basis_points == 3_000
    assert position.available_at == NOW + timedelta(seconds=3_660)
    assert stressed.event.event_type == "CollateralStressApplied"

    pledged = mobilized_inventory().allocate(
        "security-1", facility(), CollateralRequirement("collateral-rule-v1", 10_000), 9_000,
        allocation_id="allocation-1", at=NOW + timedelta(seconds=60), event_id="encumbered",
        sequence_number=2, simulation_id="sim-1", correlation_id="corr-1",
    )
    revalued = pledged.inventory.revalue(
        "security-1", 5_000, at=NOW + timedelta(minutes=1), event_id="revalued",
        sequence_number=3, simulation_id="sim-1", correlation_id="corr-1",
    )
    assert revalued.inventory.position("security-1").collateral_shortfall_minor == 4_500


def test_secured_facility_draw_checks_collateral_capacity_and_updates_cash_and_principal():
    requirement = CollateralRequirement("collateral-rule-v1", 7_500, ("treasury-v1",))
    inventory = mobilized_inventory().allocate(
        "security-1", facility(), requirement, 9_000, allocation_id="allocation-1",
        at=NOW + timedelta(seconds=60), event_id="encumbered", sequence_number=2,
        simulation_id="sim-1", correlation_id="corr-1",
    ).inventory
    drawn = draw_funding(
        facility(), account(), 6_000, at=NOW + timedelta(minutes=2), event_id="draw-1",
        sequence_number=3, simulation_id="sim-1", correlation_id="corr-1",
        collateral_inventory=inventory, collateral_requirement=requirement,
    )
    assert drawn.facility.drawn_amount_minor == 6_000
    assert drawn.facility.repayable_amount_minor == 6_000
    assert drawn.account.ledger_balance_minor == 6_100
    assert drawn.event.event_type == "FundingDrawn"

    with pytest.raises(ValueError, match="undercollateralized"):
        inventory.release(
            "allocation-1", 2_000, facility=drawn.facility, requirement=requirement,
            at=NOW + timedelta(minutes=2), event_id="invalid-release", sequence_number=4,
            simulation_id="sim-1", correlation_id="corr-1",
        )

    reduced = inventory.revalue(
        "security-1", 5_000, at=NOW + timedelta(minutes=3), event_id="revalue",
        sequence_number=4, simulation_id="sim-1", correlation_id="corr-1",
    ).inventory
    with pytest.raises(ValueError, match="does not cover"):
        draw_funding(
            drawn.facility, drawn.account, 4_000, at=NOW + timedelta(minutes=4), event_id="draw-2",
            sequence_number=5, simulation_id="sim-1", correlation_id="corr-1",
            collateral_inventory=reduced, collateral_requirement=requirement,
        )

    repaid = repay_funding(
        drawn.facility, drawn.account, 2_500, at=NOW + timedelta(minutes=5), event_id="repay-1",
        sequence_number=5, simulation_id="sim-1", correlation_id="corr-1", causation_id="draw-1",
    )
    assert repaid.facility.drawn_amount_minor == 3_500
    assert repaid.facility.repayable_amount_minor == 3_500
    assert repaid.account.ledger_balance_minor == 3_600
    assert repaid.event.causation_id == "draw-1"


def test_funding_rejects_ineligible_mismatched_matured_or_unfunded_operations():
    with pytest.raises(ValueError, match="not eligible"):
        draw_funding(facility(eligibility_status=False), account(), 1, at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")
    with pytest.raises(ValueError, match="institutions must match"):
        draw_funding(facility(), account(institution_id="bank-b"), 1, at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")
    with pytest.raises(ValueError, match="maturity"):
        draw_funding(facility(maturity_at=NOW), account(), 1, at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")
    with pytest.raises(ValueError, match="committed facility capacity"):
        draw_funding(facility(), account(), 10_001, at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c", collateral_inventory=CollateralInventory(), collateral_requirement=CollateralRequirement("collateral-rule-v1", 10_000))
    with pytest.raises(ValueError, match="insufficient unreserved cash"):
        repay_funding(facility(drawn_amount_minor=100, repayable_amount_minor=100), account(ledger_balance_minor=10, reserved_balance_minor=10), 1, at=NOW, event_id="e", sequence_number=0, simulation_id="s", correlation_id="c")


def test_simple_funding_cost_uses_integer_math_and_rounds_fraction_up():
    full_year = calculate_simple_funding_cost(100_000, 500, 365 * 24 * 60 * 60)
    assert full_year.cost_minor == 5_000
    fractional = calculate_simple_funding_cost(100, 1, 1)
    assert fractional.cost_minor == 1
