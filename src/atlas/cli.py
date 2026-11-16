"""``atlas`` command line: run the twin on your own payments file, no server needed.

    atlas template > my_day.csv          # the expected CSV header with three example rows
    atlas run --payments my_day.csv --stress combined --controller mpc --auction uniform --out report/
    atlas mcp --payments my_day.csv      # expose the tools to any MCP client
    atlas evals                          # score the bundled agents on the tool-use tasks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _usd(minor: float) -> str:
    v = minor / 100
    return f"${v / 1e9:,.2f}B" if abs(v) >= 1e9 else f"${v / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${v:,.0f}"


def _controller(kind: str):
    if kind == "mpc":
        from atlas.control import MPCController
        return MPCController()
    if kind == "rule":
        from atlas.control import RuleBasedRebalancer
        return RuleBasedRebalancer()
    return None


def cmd_run(a: argparse.Namespace) -> int:
    from atlas.ingest import IngestError, load_payments_csv, load_payments_iso20022
    from atlas.regulatory import intraday_liquidity_report
    from atlas.scenario import generate_scenario
    from atlas.sim import SimulationSettings, run_day
    from atlas.stress import build_scenario

    report = None
    try:
        if a.payments:
            balances = Path(a.balances).read_text() if a.balances else None
            src = Path(a.payments)
            if src.is_dir() or src.suffix.lower() == ".xml":
                files = sorted(src.glob("*.xml")) if src.is_dir() else [src]
                scenario, report = load_payments_iso20022([f.read_bytes() for f in files], rail=a.rail, balances_csv=balances)
            else:
                scenario, report = load_payments_csv(src.read_text(), balances_csv=balances)
        else:
            scenario = generate_scenario(seed=a.seed)
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    settings = SimulationSettings(policy=a.policy, auction=None if a.auction == "none" else a.auction)
    result = run_day(scenario, settings, build_scenario(a.stress), controller=_controller(a.controller))
    d = result.to_dict(include_payments=True)
    replay = result.verify_replay()
    bcbs = intraday_liquidity_report(d)
    m = d["metrics"]
    lv, inst = m["large_value"], m["instant"]
    alerts = None
    try:
        from atlas.detect import score_payments
        alerts = score_payments(d["payments"], top=a.top)
    except ImportError:
        pass

    origin = d["scenario"].get("data_origin")
    print(f"ATLAS  {d['scenario']['institutions']} institutions, {d['scenario']['payments']:,} payments  ({origin} data)")
    if report:
        print(f"  file: {report.accepted:,} rows accepted, {len(report.rejected):,} rejected")
        for line in report.assumptions:
            print(f"  assumed: {line}")
    print(f"  policy {a.policy} | stress {a.stress} | controller {a.controller} | auction {a.auction}")
    print(f"  large-value settled   {lv['settlement_rate_value']:.2%} of {_usd(lv['value_minor'])}   delay {lv['value_weighted_delay_s'] / 60:.1f} min")
    print(f"  instant rejected      {inst['count'] - inst['settled_count']:,} of {inst['count']:,}")
    print(f"  peak intraday credit  {_usd(m['liquidity']['peak_intraday_credit_minor'])}")
    print(f"  modeled cost          {_usd(m['costs_minor']['total'])}")
    s = bcbs["system"]
    print(f"  BCBS 248              max net debit {_usd(s['sum_max_net_negative_minor'])} of {_usd(s['sum_available_at_start_minor'])} available; "
          f"most stretched: {s['most_stretched_institution']}")
    if alerts is not None:
        print(f"  unusual payments      {len(alerts['alerts'])} flagged for review ({alerts['mode']})")
    print(f"  ledger replay         {'VERIFIED' if replay else 'FAILED'}  {result.final_state_hash[:16]}")
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "run.json").write_text(json.dumps(result.to_dict(include_payments=False), indent=1))
        (out / "payments.json").write_text(json.dumps(d["payments"]))
        (out / "intraday_liquidity_bcbs248.json").write_text(json.dumps(bcbs, indent=1))
        if report:
            (out / "ingest_report.json").write_text(json.dumps(report.to_dict(), indent=1))
        if alerts is not None:
            (out / "alerts.json").write_text(json.dumps(alerts, indent=1))
        print(f"  wrote {out}/")
    return 0 if replay else 1


def main(argv: list[str] | None = None) -> int:
    from atlas.agent.tools import AUCTIONS, STRESSES
    from atlas.sim import POLICIES

    ap = argparse.ArgumentParser(prog="atlas", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template", help="print the payments CSV template")
    r = sub.add_parser("run", help="simulate a day (your file, or a synthetic day)")
    r.add_argument("--payments", help="CSV file, one pacs.008/pacs.009 XML file, or a folder of XML files")
    r.add_argument("--balances", help="optional CSV: institution,rail,opening_balance,credit_limit")
    r.add_argument("--rail", default="rtgs", choices=("rtgs", "lsm", "fednow", "rtp"), help="rail for ISO 20022 input")
    r.add_argument("--seed", type=int, default=11, help="synthetic day seed when no file is given")
    r.add_argument("--policy", default="priority", choices=POLICIES)
    r.add_argument("--stress", default="baseline", choices=STRESSES)
    r.add_argument("--controller", default="none", choices=("none", "rule", "mpc"))
    r.add_argument("--auction", default="none", choices=AUCTIONS)
    r.add_argument("--top", type=int, default=25, help="number of unusual payments to list")
    r.add_argument("--out", help="folder for JSON reports")
    m = sub.add_parser("mcp", help="start the MCP server on stdio")
    m.add_argument("--payments")
    m.add_argument("--balances")
    m.add_argument("--seed", type=int, default=11)
    e = sub.add_parser("evals", help="score agents on the tool-use tasks")
    e.add_argument("--llm", action="store_true")
    e.add_argument("--out", default="results/agent_evals.json")
    a = ap.parse_args(argv)
    if a.cmd == "template":
        from atlas.ingest import template_csv
        sys.stdout.write(template_csv())
        return 0
    if a.cmd == "run":
        return cmd_run(a)
    if a.cmd == "mcp":
        from atlas.agent import mcp_server
        sys.argv = ["atlas-mcp", "--seed", str(a.seed)] + (["--payments", a.payments] if a.payments else []) + (["--balances", a.balances] if a.balances else [])
        mcp_server.main()
        return 0
    from atlas.agent import evals
    sys.argv = ["atlas-evals", "--out", a.out] + (["--llm"] if a.llm else [])
    evals.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
