import json

from atlas.live import fetch_markets, freshness, indicators, load_snapshot, to_simulation
from atlas.live.markets import _parse_live


def test_snapshot_loads_and_validates():
    md = load_snapshot()
    assert all(len(md.series[k]) > 80 for k in ("sofr", "effr", "rrp", "tga"))
    assert md.series["sofr"][0]["date"] < md.series["sofr"][-1]["date"]


def test_offline_falls_back_and_says_so():
    md = fetch_markets(allow_network=False)
    assert set(md.origin.values()) == {"snapshot"} and md.errors["sofr"] == "network disabled"


def test_live_parser_and_bad_rows_dropped():
    payload = {"refRates": [{"effectiveDate": "2026-11-13", "percentRate": 3.9, "percentPercentile1": 3.85, "percentPercentile99": 3.97, "volumeInBillions": 3092},
                            {"effectiveDate": "not-a-date", "percentRate": 3.9, "percentPercentile1": 1, "percentPercentile99": 1, "volumeInBillions": 1},
                            {"effectiveDate": "2026-11-12", "percentRate": 99, "percentPercentile1": 1, "percentPercentile99": 1, "volumeInBillions": 1}]}
    assert len(_parse_live("sofr", payload)) == 1


def test_failed_source_uses_snapshot_others_live():
    sofr = {"refRates": [{"effectiveDate": f"2026-11-{d:02d}", "percentRate": 4.0, "percentPercentile1": 3.9, "percentPercentile99": 4.2, "volumeInBillions": 3000} for d in range(2, 14)]}

    def opener(url):
        if "secured/sofr" in url:
            return json.dumps(sofr).encode()
        raise OSError("blocked")
    md = fetch_markets(opener=opener)
    assert md.origin["sofr"] == "live" and md.origin["tga"] == "snapshot" and "blocked" in md.errors["tga"]


def test_indicators_and_mapping_monotone():
    md = load_snapshot()
    ind = indicators(md)
    assert 0 <= ind["score"] <= 100 and ind["regime"] in ("calm", "firm", "tight")
    calm, tight = dict(ind, score=10, regime="calm", month_end_near=False), dict(ind, score=90, regime="tight")
    assert to_simulation(calm)["liq"] > to_simulation(tight)["liq"]
    assert to_simulation(tight)["stress"] == "liquidity_hoarding"
    past = indicators(md, as_of="2026-09-30")
    assert past["as_of"] <= "2026-09-30"
    assert {f["key"] for f in freshness(md)} == {"sofr", "effr", "rrp", "tga"}
