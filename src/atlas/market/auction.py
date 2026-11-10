"""Sealed-bid intraday liquidity auction (``atlas-liquidity-auction-v1``).

Setting. When the RTGS queue is backed up, institutions holding idle settlement
cash (lenders) submit *asks*: a quantity they are willing to lend until close and a
minimum flat rate in basis points of principal. Institutions whose released
payments cannot settle (borrowers) submit *bids*: the shortfall quantity and the
maximum flat rate they would pay. A sealed-bid double auction matches them.

Mechanisms
----------
* ``pay_as_bid`` (discriminatory): asks sorted ascending, bids descending; each
  matched unit trades at the lender's own ask. Lenders have an incentive to shade
  asks upward (well-known for discriminatory multi-unit auctions; Krishna, 2009,
  *Auction Theory*, ch. 12-13).
* ``uniform``: all matched units trade at one clearing price: the highest
  accepted ask (a "k=1" double-auction price rule). A lender whose ask is not
  marginal cannot move the price, but a marginal lender can (demand/supply
  reduction), so the rule is **not** strategy-proof in general.

Neither rule is assumed incentive compatible; ``scripts/auction_study.py``
measures the gain from ask shading empirically on paired seeds.

Clearing is computed in exact integer arithmetic (minor units, integer bp). The
result is a list of bilateral trades with quantities that sum, per lender, to at
most the offered quantity and, per borrower, to at most the demanded quantity.
"""

from __future__ import annotations

from dataclasses import dataclass

AUCTION_VERSION = "atlas-liquidity-auction-v1"
MECHANISMS = ("pay_as_bid", "uniform")


@dataclass(frozen=True, slots=True)
class Ask:
    lender: str
    quantity_minor: int
    min_rate_cbp: int
    true_cost_cbp: int | None = None   # simulator-only knowledge, used for welfare accounting


@dataclass(frozen=True, slots=True)
class Bid:
    borrower: str
    quantity_minor: int
    max_rate_cbp: int


@dataclass(frozen=True, slots=True)
class Trade:
    lender: str
    borrower: str
    quantity_minor: int
    rate_cbp: int

    @property
    def interest_minor(self) -> int:
        return -(-self.quantity_minor * self.rate_cbp // 1_000_000)   # rate in hundredths of a bp; rounded up


@dataclass(frozen=True, slots=True)
class ClearingResult:
    mechanism: str
    trades: tuple[Trade, ...]
    clearing_rate_cbp: int | None
    matched_quantity_minor: int
    offered_quantity_minor: int
    demanded_quantity_minor: int

    @property
    def fill_ratio(self) -> float:
        return self.matched_quantity_minor / self.demanded_quantity_minor if self.demanded_quantity_minor else 0.0


def _validate(asks: list[Ask], bids: list[Bid]) -> None:
    for a in asks:
        if a.quantity_minor <= 0 or a.min_rate_cbp < 0:
            raise ValueError(f"invalid ask from {a.lender}")
    for b in bids:
        if b.quantity_minor <= 0 or b.max_rate_cbp < 0:
            raise ValueError(f"invalid bid from {b.borrower}")
    if {a.lender for a in asks} & {b.borrower for b in bids}:
        raise ValueError("an institution cannot be lender and borrower in the same auction")
    if len({a.lender for a in asks}) != len(asks) or len({b.borrower for b in bids}) != len(bids):
        raise ValueError("one ask per lender and one bid per borrower")


def clear_auction(asks: list[Ask], bids: list[Bid], mechanism: str = "uniform") -> ClearingResult:
    """Match asks and bids; deterministic tie-breaking by rate, then institution id."""
    if mechanism not in MECHANISMS:
        raise ValueError(f"unknown mechanism {mechanism!r}")
    _validate(asks, bids)
    supply = sorted(asks, key=lambda a: (a.min_rate_cbp, a.lender))
    demand = sorted(bids, key=lambda b: (-b.max_rate_cbp, b.borrower))
    offered = sum(a.quantity_minor for a in supply)
    demanded = sum(b.quantity_minor for b in demand)
    raw: list[tuple[str, str, int, int]] = []     # lender, borrower, qty, lender ask
    si = di = 0
    s_left = supply[0].quantity_minor if supply else 0
    d_left = demand[0].quantity_minor if demand else 0
    while si < len(supply) and di < len(demand) and supply[si].min_rate_cbp <= demand[di].max_rate_cbp:
        q = min(s_left, d_left)
        raw.append((supply[si].lender, demand[di].borrower, q, supply[si].min_rate_cbp))
        s_left -= q
        d_left -= q
        if s_left == 0:
            si += 1
            s_left = supply[si].quantity_minor if si < len(supply) else 0
        if d_left == 0:
            di += 1
            d_left = demand[di].quantity_minor if di < len(demand) else 0
    if not raw:
        return ClearingResult(mechanism, (), None, 0, offered, demanded)
    clearing = max(r[3] for r in raw)
    trades = tuple(Trade(lender, b, q, clearing if mechanism == "uniform" else ask) for lender, b, q, ask in raw)
    matched = sum(t.quantity_minor for t in trades)
    # Individual rationality is guaranteed by construction; assert it in integers.
    bid_rate = {b.borrower: b.max_rate_cbp for b in bids}
    ask_rate = {a.lender: a.min_rate_cbp for a in asks}
    for t in trades:
        assert ask_rate[t.lender] <= t.rate_cbp <= bid_rate[t.borrower]
    return ClearingResult(mechanism, trades, clearing, matched, offered, demanded)
