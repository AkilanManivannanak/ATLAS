"""Exact monetary values for authoritative simulated ledger state."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class CurrencySpec:
    """Currency metadata supplied by a versioned, reviewed configuration."""

    code: str
    minor_unit_exponent: int

    def __post_init__(self) -> None:
        if len(self.code) != 3 or not self.code.isalpha() or not self.code.isupper():
            raise ValueError("currency code must be three uppercase letters")
        if not isinstance(self.minor_unit_exponent, int) or isinstance(self.minor_unit_exponent, bool) or self.minor_unit_exponent < 0:
            raise ValueError("minor unit exponent must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class Money:
    """A currency-tagged integer amount; no binary float is accepted."""

    currency: str
    amount_minor: int

    def __post_init__(self) -> None:
        CurrencySpec(self.currency, 0)
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("amount_minor must be an integer")

    @classmethod
    def from_major_units(cls, amount: str | Decimal, currency: CurrencySpec) -> Money:
        """Convert exact decimal input to minor units without rounding."""
        if isinstance(amount, float):
            raise TypeError("binary floating-point input is not accepted")
        try:
            value = amount if isinstance(amount, Decimal) else Decimal(amount)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount must be a valid decimal string") from exc
        if not value.is_finite():
            raise ValueError("amount must be finite")
        scaled = value * (10 ** currency.minor_unit_exponent)
        if scaled != scaled.to_integral_value():
            raise ValueError("amount has more fractional digits than currency precision permits")
        return cls(currency.code, int(scaled))
