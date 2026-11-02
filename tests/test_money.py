from decimal import Decimal

import pytest

from atlas.domain.money import CurrencySpec, Money


def test_exact_major_unit_conversion():
    usd = CurrencySpec("USD", 2)
    assert Money.from_major_units("12.34", usd) == Money("USD", 1234)
    assert Money.from_major_units(Decimal("0.01"), usd) == Money("USD", 1)


def test_conversion_rejects_excess_precision_without_rounding():
    with pytest.raises(ValueError, match="fractional digits"):
        Money.from_major_units("1.001", CurrencySpec("USD", 2))


def test_binary_float_is_not_accepted():
    with pytest.raises(TypeError, match="floating-point"):
        Money.from_major_units(0.1, CurrencySpec("USD", 2))


def test_currency_metadata_requires_explicit_valid_precision():
    with pytest.raises(ValueError, match="exponent"):
        CurrencySpec("USD", -1)
