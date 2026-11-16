"""Live funding-market data from two public sources, with an honest fallback.

* Federal Reserve Bank of New York Markets API: SOFR (with its 1st/99th percentiles and volume), EFFR, and the
  overnight reverse repo facility (RRP) take-up.
* US Treasury Fiscal Data API, Daily Treasury Statement: the Treasury General Account (TGA) balance.

Neither needs a key. When a source cannot be reached (offline, rate-limited, blocked), the series falls back to the
snapshot in ``data/live/snapshot.json`` and is labelled ``snapshot`` everywhere it is shown, with the snapshot's own
timestamp. Nothing is interpolated or invented.

Why these four: they are what a bank treasury desk reads each morning about reserve conditions. SOFR printing
above EFFR means secured overnight cash is dearer than unsecured, a classic sign that reserves are getting less
abundant; a wide SOFR tail (99th minus 1st percentile) means some borrowers pay up; RRP take-up near zero means the
cash buffer that used to absorb drains is gone; a rising TGA drains reserves from the banking system.

``to_simulation`` turns those readings into a starting point for the simulator. That mapping is a documented
heuristic, not an estimated model, and the app says so.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "live" / "snapshot.json"
_NYF = "https://markets.newyorkfed.org/api"
_TSY = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"

SERIES = {
    "sofr": {"name": "SOFR", "publisher": "Federal Reserve Bank of New York", "unit": "%", "target_lag_days": 1,
             "url": f"{_NYF}/rates/secured/sofr/last/{{n}}.json"},
    "effr": {"name": "EFFR", "publisher": "Federal Reserve Bank of New York", "unit": "%", "target_lag_days": 1,
             "url": f"{_NYF}/rates/unsecured/effr/last/{{n}}.json"},
    "rrp": {"name": "Overnight RRP take-up", "publisher": "Federal Reserve Bank of New York", "unit": "$bn", "target_lag_days": 1,
            "url": f"{_NYF}/rp/reverserepo/all/results/last/{{n}}.json"},
    "tga": {"name": "Treasury General Account", "publisher": "US Treasury, Daily Treasury Statement", "unit": "$bn", "target_lag_days": 2,
            "url": f"{_TSY}?filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Closing%20Balance&fields=record_date,open_today_bal"
                   "&sort=-record_date&page[size]={n}"},
}


@dataclass
class MarketData:
    series: dict[str, list[dict]] = field(default_factory=dict)       # ascending by date
    origin: dict[str, str] = field(default_factory=dict)              # "live" or "snapshot"
    errors: dict[str, str] = field(default_factory=dict)
    fetched_at: str = ""
    snapshot_at: str = ""

    def latest(self, key: str) -> dict | None:
        rows = self.series.get(key) or []
        return rows[-1] if rows else None

    def to_dict(self) -> dict:
        return {"series": self.series, "origin": self.origin, "errors": self.errors, "fetched_at": self.fetched_at, "snapshot_at": self.snapshot_at}


# ------------------------------------------------------------------ parsing (live JSON and the compact snapshot)
def _parse_live(key: str, payload: dict) -> list[dict]:
    if key == "sofr":
        rows = [{"date": r["effectiveDate"], "rate": float(r["percentRate"]), "p1": float(r["percentPercentile1"]), "p99": float(r["percentPercentile99"]),
                 "volume_bn": float(r["volumeInBillions"])} for r in payload["refRates"]]
    elif key == "effr":
        rows = [{"date": r["effectiveDate"], "rate": float(r["percentRate"]), "volume_bn": float(r["volumeInBillions"])} for r in payload["refRates"]]
    elif key == "rrp":
        by_day: dict[str, float] = {}
        for o in payload["repo"]["operations"]:
            by_day[o["operationDate"]] = by_day.get(o["operationDate"], 0.0) + float(o.get("totalAmtAccepted") or 0) / 1e9
        rows = [{"date": d, "value_bn": v} for d, v in by_day.items()]
    elif key == "tga":
        rows = [{"date": r["record_date"], "value_bn": float(r["open_today_bal"]) / 1e3} for r in payload["data"] if r.get("open_today_bal") not in (None, "null")]
    else:
        raise KeyError(key)
    return _validate(key, rows)


def _parse_snapshot(key: str, text: str) -> list[dict]:
    rows = []
    by_day: dict[str, float] = {}
    for line in text.split(";"):
        p = line.split(",")
        if key == "sofr":
            rows.append({"date": p[0], "rate": float(p[1]), "p1": float(p[2]), "p99": float(p[3]), "volume_bn": float(p[4])})
        elif key == "effr":
            rows.append({"date": p[0], "rate": float(p[1]), "volume_bn": float(p[2])})
        elif key == "rrp":
            by_day[p[0]] = by_day.get(p[0], 0.0) + float(p[1]) / 1e9
        elif key == "tga":
            rows.append({"date": p[0], "value_bn": float(p[1]) / 1e3})
    if key == "rrp":
        rows = [{"date": d, "value_bn": v} for d, v in by_day.items()]
    return _validate(key, rows)


def _validate(key: str, rows: list[dict]) -> list[dict]:
    """Schema and range checks. A row that fails is dropped and counted, never repaired."""
    ok = []
    for r in rows:
        try:
            date.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        if key in ("sofr", "effr") and not (-1.0 < r["rate"] < 25.0):
            continue
        if key in ("rrp", "tga") and not (0.0 <= r["value_bn"] < 10_000):
            continue
        ok.append(r)
    ok.sort(key=lambda r: r["date"])
    return ok


def load_snapshot(path: Path | str = SNAPSHOT) -> MarketData:
    d = json.loads(Path(path).read_text())
    md = MarketData(fetched_at=d["fetched_at"], snapshot_at=d["fetched_at"])
    for k in SERIES:
        md.series[k] = _parse_snapshot(k, d[k])
        md.origin[k] = "snapshot"
    return md


def fetch_markets(n: int = 130, timeout: float = 6.0, allow_network: bool = True, opener=None) -> MarketData:
    """Each series is fetched independently; any that fails falls back to the snapshot on its own."""
    snap = load_snapshot()
    md = MarketData(fetched_at=datetime.now(UTC).isoformat(timespec="seconds"), snapshot_at=snap.snapshot_at)
    get = opener or (lambda url: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "atlas-sigma", "Accept": "application/json"}),  # noqa: S310
                                                        timeout=timeout).read())
    for k, spec in SERIES.items():
        rows = None
        if allow_network:
            try:
                rows = _parse_live(k, json.loads(get(spec["url"].format(n=n))))
                if len(rows) < 5:
                    raise ValueError(f"only {len(rows)} valid rows")
            except Exception as exc:  # noqa: BLE001 - recorded and shown, then the snapshot is used
                md.errors[k] = f"{type(exc).__name__}: {str(exc)[:120]}"
                rows = None
        else:
            md.errors[k] = "network disabled"
        md.series[k], md.origin[k] = (rows, "live") if rows else (snap.series[k], "snapshot")
    return md


# ------------------------------------------------------------------ what a desk reads off it
def _business_days_between(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def freshness(md: MarketData, today: date | None = None) -> list[dict]:
    """Per series: last observation, its age in business days, and whether that meets the publication lag target."""
    today = today or datetime.now(UTC).date()
    out = []
    for k, spec in SERIES.items():
        last = md.latest(k)
        age = _business_days_between(date.fromisoformat(last["date"]), today) if last else None
        out.append({"key": k, "series": spec["name"], "publisher": spec["publisher"], "origin": md.origin.get(k), "last": last["date"] if last else None,
                    "age_business_days": age, "target_lag_days": spec["target_lag_days"], "fresh": age is not None and age <= spec["target_lag_days"],
                    "rows": len(md.series.get(k) or []), "error": md.errors.get(k)})
    return out


def _join(a: list[dict], b: list[dict], fa: str, fb: str) -> list[tuple[str, float, float]]:
    bm = {r["date"]: r[fb] for r in b}
    return [(r["date"], r[fa], bm[r["date"]]) for r in a if r["date"] in bm]


def indicators(md: MarketData, as_of: str | None = None) -> dict:
    """Reserve-conditions readings and a 0-100 tightness score (documented heuristic weights). ``as_of`` replays a past day
    using only data published up to it."""
    sofr, effr, rrp, tga = ([r for r in (md.series.get(k) or []) if as_of is None or r["date"] <= as_of] for k in ("sofr", "effr", "rrp", "tga"))
    pairs = _join(sofr, effr, "rate", "rate")
    spread = [(d, round((s - e) * 100, 1)) for d, s, e in pairs]
    last20 = [x for _, x in spread[-20:]] or [0.0]
    tail = [(r["date"], round((r["p99"] - r["p1"]) * 100, 1)) for r in sofr]
    tga_now = tga[-1]["value_bn"] if tga else 0.0
    tga_5 = tga[-6]["value_bn"] if len(tga) >= 6 else tga_now
    rrp_now = rrp[-1]["value_bn"] if rrp else 0.0
    rrp_20 = mean(r["value_bn"] for r in rrp[-20:]) if rrp else 0.0
    s_now = spread[-1][1] if spread else 0.0
    tail_now = tail[-1][1] if tail else 0.0
    drain = tga_now - tga_5
    parts = {
        "SOFR above EFFR": min(max(s_now, 0.0), 15.0) / 15.0 * 40,
        "Wide SOFR tail": min(max(tail_now - 8.0, 0.0), 12.0) / 12.0 * 20,
        "TGA draining reserves": min(max(drain, 0.0), 100.0) / 100.0 * 20,
        "RRP buffer used up": 20.0 * (1.0 - min(rrp_20, 500.0) / 500.0),
    }
    score = round(sum(parts.values()), 1)
    regime = "calm" if score < 35 else "firm" if score < 65 else "tight"
    last_day = date.fromisoformat(sofr[-1]["date"]) if sofr else datetime.now(UTC).date()
    nxt = last_day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    month_end_near = (nxt + timedelta(days=3)).month != nxt.month
    return {
        "as_of": sofr[-1]["date"] if sofr else None, "sofr_pct": sofr[-1]["rate"] if sofr else None, "effr_pct": effr[-1]["rate"] if effr else None,
        "sofr_volume_bn": sofr[-1]["volume_bn"] if sofr else None, "spread_bp": s_now, "spread_20d_avg_bp": round(mean(last20), 1),
        "days_sofr_above_effr_20d": sum(1 for x in last20 if x > 0), "sofr_tail_bp": tail_now, "rrp_bn": round(rrp_now, 2), "rrp_20d_avg_bn": round(rrp_20, 2),
        "tga_bn": round(tga_now, 1), "tga_5d_change_bn": round(drain, 1), "month_end_near": month_end_near, "score": score, "regime": regime,
        "score_parts": {k: round(v, 1) for k, v in parts.items()}, "spread_series": spread, "tail_series": tail,
        "method": "Heuristic weights, not an estimated model: 40 SOFR-EFFR spread (0-15bp), 20 SOFR 99th-1st percentile tail above 8bp, "
                  "20 five-day TGA increase (0-$100bn), 20 RRP 20-day average below $500bn.",
    }


def to_simulation(ind: dict) -> dict:
    """A starting day for the simulator that reflects today's readings. Tighter market, less opening liquidity."""
    score = ind["score"]
    liq = int(round(max(6, min(26, 24 - score * 0.16))))
    if ind["regime"] == "tight":
        stress, why = "liquidity_hoarding", "readings are tight, so banks are assumed to hold back outgoing payments"
    elif ind["month_end_near"]:
        stress, why = "concentrated_outflows", "month-end is close, so outflows are assumed to bunch"
    elif ind["regime"] == "firm":
        stress, why = "funding_disruption", "readings are firm, so one funding line is assumed to wobble"
    else:
        stress, why = "baseline", "readings are calm"
    return {"liq": liq, "stress": stress,
            "explanation": [f"Tightness score {score:.0f}/100 ({ind['regime']}) sets opening liquidity to {liq}% of each bank's outflow.",
                            f"Stress: {why}.", "This mapping is a transparent rule of thumb, not a fitted model."]}
