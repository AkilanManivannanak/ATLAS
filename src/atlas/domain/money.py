"""Exact monetary values and versioned currency precision metadata."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class CurrencySpec:
    """Currency metadata supplied by a versioned, reviewed configuration."""

    code: str
    minor_unit_exponent: int

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or len(self.code) != 3 or not self.code.isalpha() or not self.code.isupper():
            raise ValueError("currency code must be three uppercase letters")
        if not isinstance(self.minor_unit_exponent, int) or isinstance(self.minor_unit_exponent, bool) or self.minor_unit_exponent < 0:
            raise ValueError("minor unit exponent must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CurrencyRegistry:
    """Immutable, explicitly versioned currency metadata; no implicit defaults."""

    version: str
    currencies: tuple[CurrencySpec, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("currency registry version is required")
        if not isinstance(self.currencies, tuple):
            raise TypeError("currency registry currencies must be an immutable tuple")
        codes = [item.code for item in self.currencies]
        if len(codes) != len(set(codes)):
            raise ValueError("currency registry contains duplicate codes")

    def get(self, code: str) -> CurrencySpec:
        for item in self.currencies:
            if item.code == code:
                return item
        raise KeyError(f"currency {code!r} is not in registry {self.version!r}")

    def with_currency(self, spec: CurrencySpec) -> CurrencyRegistry:
        if any(item.code == spec.code for item in self.currencies):
            raise ValueError(f"currency {spec.code} already exists in this registry version")
        return CurrencyRegistry(self.version, (*self.currencies, spec))


@dataclass(frozen=True, slots=True)
class Money:
    """A currency-tagged integer amount; no binary float is accepted."""

    currency: str
    amount_minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string code")
        CurrencySpec(self.currency, 0)
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("amount_minor must be an integer")

    @classmethod
    def from_major_units(cls, amount: str | Decimal, currency: CurrencySpec) -> Money:
        """Convert exact decimal input to minor units without rounding."""
        if isinstance(amount, float):
            raise TypeError("binary floating-point input is not accepted")
        if not isinstance(amount, (str, Decimal)):
            raise TypeError("amount must be a decimal string or Decimal")
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
