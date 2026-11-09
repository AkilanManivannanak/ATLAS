from decimal import Decimal

import pytest

from atlas.domain.money import CurrencyRegistry, CurrencySpec, Money


def test_exact_major_unit_conversion_and_versioned_registry():
    usd = CurrencySpec("USD", 2)
    registry = CurrencyRegistry("test-currencies-v1").with_currency(usd)
    assert registry.get("USD") == usd
    assert Money.from_major_units("12.34", registry.get("USD")) == Money("USD", 1234)
    assert Money.from_major_units(Decimal("0.01"), usd) == Money("USD", 1)


def test_currency_registry_is_immutable_and_rejects_duplicate_code():
    registry = CurrencyRegistry("currencies-v1")
    updated = registry.with_currency(CurrencySpec("USD", 2))
    assert registry.currencies == ()
    assert len(updated.currencies) == 1
    with pytest.raises(ValueError, match="already exists"):
        updated.with_currency(CurrencySpec("USD", 2))


def test_conversion_rejects_excess_precision_without_rounding():
    with pytest.raises(ValueError, match="fractional digits"):
        Money.from_major_units("1.001", CurrencySpec("USD", 2))


def test_binary_float_and_integer_inputs_are_not_accepted():
    with pytest.raises(TypeError, match="floating-point"):
        Money.from_major_units(0.1, CurrencySpec("USD", 2))
    with pytest.raises(TypeError, match="decimal string or Decimal"):
        Money.from_major_units(1, CurrencySpec("USD", 2))


def test_currency_metadata_requires_explicit_valid_precision():
    with pytest.raises(ValueError, match="exponent"):
        CurrencySpec("USD", -1)


def test_currency_registry_rejects_mutable_collection_input():
    with pytest.raises(TypeError, match="immutable tuple"):
        CurrencyRegistry("mutable", [CurrencySpec("USD", 2)])
