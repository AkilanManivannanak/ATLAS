"""v0.7: bring-your-own-data, BCBS 248 report, anomaly detection, model inventory, agent tools, MCP, evals, calibration, lab."""

from __future__ import annotations

import io
import json
from datetime import date

import pytest

from atlas.agent.evals import TASKS, evaluate, fabricator_agent, overreacher_agent, planner_agent, ungrounded_numbers
from atlas.agent.mcp_server import handle, serve
from atlas.agent.tools import BudgetExceeded, ToolError, ToolSession
from atlas.calibration import calibration_report, public_calibrated_config
from atlas.governance import build_inventory, population_stability_index, render_model_card
from atlas.ingest import IngestError, export_scenario_csv, load_payments_csv, load_payments_iso20022, template_csv
from atlas.iso20022.messages import build_pacs008
from atlas.lab import run_lab
from atlas.regulatory import intraday_liquidity_report
from atlas.scenario import NexusPayConfig, generate_scenario
from atlas.sim import SimulationSettings, run_day

SMALL = NexusPayConfig(n_institutions=8, payments_per_day=300, instant_payments_per_day=200)


@pytest.fixture(scope="module")
def day():
    return generate_scenario(SMALL, seed=5)


@pytest.fixture(scope="module")
def run(day):
    return run_day(day, SimulationSettings(policy="priority")).to_dict(include_payments=True)


# ------------------------------------------------------------------ ingest
def test_csv_round_trip_keeps_every_payment(day):
    sc, report = load_payments_csv(export_scenario_csv(day))
    assert report.accepted == len(day.payments) and not report.rejected
    assert [(p.payment_id, p.amount_minor, p.arrival_at) for p in sc.payments] == [(p.payment_id, p.amount_minor, p.arrival_at) for p in day.payments]
    assert sc.labels["data_origin"] == "user_supplied"
    res = run_day(sc)
    assert res.verify_replay() and res.manifest["data_origin"] == "user_supplied"


def test_template_runs_and_lists_assumptions():
    sc, report = load_payments_csv(template_csv(), business_date=date(2026, 3, 10))
    assert report.accepted == 3 and len(sc.institutions) == 3
    assert any("opening balances were not supplied" in a for a in report.assumptions)
    assert {p.rail for p in sc.payments} == {"rtgs", "lsm", "fednow"}       # fedwire -> rtgs, chips -> lsm


def test_bad_rows_are_rejected_with_reasons_not_dropped():
    text = ("sender,receiver,amount,time,rail\n"
            "A,B,100.00,2026-03-10T09:00:00-04:00,fedwire\n"
            "A,A,100.00,2026-03-10T09:01:00-04:00,fedwire\n"         # same party
            "A,B,-5,2026-03-10T09:02:00-04:00,fedwire\n"             # negative
            "A,B,1.234,2026-03-10T09:03:00-04:00,fedwire\n"          # sub-cent
            "A,B,100,2026-03-10T09:04:00-04:00,swift\n"              # unknown rail
            "B,A,250000.50,2026-03-10T09:05:00-04:00,chips\n")
    sc, report = load_payments_csv(text)
    assert report.rows_read == 6 and report.accepted == 2 and len(report.rejected) == 4
    reasons = " | ".join(r["reason"] for r in report.rejected)
    for needle in ("same institution", "positive", "decimal places", "unknown rail"):
        assert needle in reasons
    assert sum(p.amount_minor for p in sc.payments) == 100_00 + 250_000_50


def test_missing_columns_and_empty_files_raise():
    with pytest.raises(IngestError, match="missing column"):
        load_payments_csv("sender,receiver\nA,B\n")
    with pytest.raises(IngestError, match="no usable payments"):
        load_payments_csv("sender,receiver,amount,time\nA,A,1,09:00\n", business_date=date(2026, 3, 10))


def test_supplied_balances_are_used_exactly():
    pay = "sender,receiver,amount,time\nA,B,1000000.00,2026-03-10T09:00:00-04:00\nB,A,400000.00,2026-03-10T09:10:00-04:00\n"
    bal = "institution,rail,opening_balance,credit_limit\nA,fedwire,250000.00,0\nB,fedwire,5000000.00,100000.00\n"
    sc, report = load_payments_csv(pay, balances_csv=bal)
    acct = {a.account_id: a for a in sc.accounts}
    assert acct["A:rtgs"].opening_balance_minor == 250_000_00 and acct["B:rtgs"].credit_limit_minor == 100_000_00
    assert not any("opening balances were not supplied" in a for a in report.assumptions)
    res = run_day(sc)
    assert res.verify_replay()
    # A cannot pay $1M from $250k until B's $400k arrives; with $650k it still cannot, so the payment stays unsettled
    status = {p["payment_id"]: p["status"] for p in res.payments}
    assert list(status.values()).count("settled") == 1


def test_iso20022_messages_become_a_scenario():
    from datetime import UTC, datetime

    from atlas.domain.money import Money
    txs = [{"end_to_end_id": f"E2E{i}", "instruction_id": f"I{i}", "amount": Money("USD", 1_000_000_00 + i),
            "settlement_date": date(2026, 3, 10), "debtor_bic": "AAAAUS33", "creditor_bic": "BBBBUS33"} for i in range(3)]
    xml = build_pacs008("MSG1", datetime(2026, 3, 10, 14, 0, tzinfo=UTC), txs)
    sc, report = load_payments_iso20022([xml, "<not-xml"])
    assert report.accepted == 3 and len(report.rejected) == 1
    assert {i.institution_id for i in sc.institutions} == {"AAAAUS33", "BBBBUS33"}


# ------------------------------------------------------------------ BCBS 248
def test_bcbs248_positions_reconcile_with_payments(run):
    rep = intraday_liquidity_report(run)
    assert rep["version"] == "atlas-bcbs248-v1" and len(rep["institutions"]) == 8
    # net positions across the closed system sum to zero; gross sent == gross received
    assert sum(r["end_of_day_net_position_minor"] for r in rep["institutions"]) == 0
    assert sum(r["A_iii_gross_sent_minor"] for r in rep["institutions"]) == sum(r["A_iii_gross_received_minor"] for r in rep["institutions"])
    settled = sum(p["amount_minor"] for p in run["payments"] if p["rail"] in ("rtgs", "lsm") and p["status"] == "settled")
    assert rep["system"]["gross_settled_minor"] == settled
    for r in rep["institutions"]:
        t = [x for x in r["C_i_throughput_by_hour"] if x is not None]
        assert t == sorted(t) and (not t or t[-1] <= 1.0)
        assert r["A_i_max_net_negative_position_minor"] >= 0 and r["A_i_max_net_negative_position_minor"] >= -r["end_of_day_net_position_minor"]


def test_bcbs248_hand_example():
    run = {"scenario": {}, "timeseries": [{"t": "2026-03-10T12:00:00+00:00"}, {"t": "2026-03-10T15:00:00+00:00"}],
           "per_institution": [{"institution_id": "A", "tier": "core", "opening_minor": {"rtgs": 100}, "credit_limit_minor": 50},
                               {"institution_id": "B", "tier": "core", "opening_minor": {"rtgs": 100}, "credit_limit_minor": 0}],
           "payments": [
               {"payment_id": "1", "rail": "rtgs", "sender": "A", "receiver": "B", "amount_minor": 80, "status": "settled", "kind": "timed",
                "settled_at": "2026-03-10T12:30:00+00:00", "due": "2026-03-10T12:10:00+00:00"},
               {"payment_id": "2", "rail": "rtgs", "sender": "A", "receiver": "B", "amount_minor": 40, "status": "settled", "kind": "interbank",
                "settled_at": "2026-03-10T13:30:00+00:00", "due": "2026-03-10T15:00:00+00:00"},
               {"payment_id": "3", "rail": "rtgs", "sender": "B", "receiver": "A", "amount_minor": 30, "status": "settled", "kind": "interbank",
                "settled_at": "2026-03-10T14:30:00+00:00", "due": "2026-03-10T15:00:00+00:00"},
               {"payment_id": "4", "rail": "rtgs", "sender": "B", "receiver": "A", "amount_minor": 500, "status": "expired", "kind": "timed",
                "settled_at": None, "due": "2026-03-10T15:00:00+00:00"}]}
    a, b = intraday_liquidity_report(run)["institutions"]
    assert a["A_i_max_net_negative_position_minor"] == 120 and a["A_ii_available_at_start_minor"] == 150 and a["A_i_usage_share_of_available"] == 0.8
    assert a["A_iv_time_specific"] == {"count": 1, "value": 80, "late": 1, "late_value": 80, "failed": 0, "failed_value": 0}
    assert a["C_i_throughput_by_hour"][:3] == [round(80 / 120, 6), 1.0, 1.0]
    assert b["A_i_max_net_positive_position_minor"] == 120 and b["A_iv_time_specific"]["failed"] == 1 and b["end_of_day_net_position_minor"] == 90


# ------------------------------------------------------------------ anomaly detection
def test_injected_anomalies_are_labelled_and_ranked():
    np = pytest.importorskip("numpy")
    from atlas.detect.anomaly import CorridorProfile, _robust_z_score, average_precision, featurize, inject_anomalies, rows_from_scenario
    hist = [generate_scenario(SMALL, seed=s, topology_seed=1) for s in range(40, 46)]
    profile = CorridorProfile.fit([rows_from_scenario(s) for s in hist], [s.open_at for s in hist])
    today = generate_scenario(SMALL, seed=50, topology_seed=1)
    mixed = inject_anomalies(rows_from_scenario(today), profile, today.open_at, today.close_at, seed=1, types=("structuring", "duplicate"))
    y = np.array([r.label for r in mixed])
    assert y.sum() >= 2 and len(mixed) == len(today.payments) + y.sum()
    score = _robust_z_score(featurize(mixed, profile, today.open_at))
    assert average_precision(y, score) > 0.9          # both typologies are rule-detectable by construction
    assert inject_anomalies(rows_from_scenario(today), profile, today.open_at, today.close_at, seed=1, types=("structuring",))[0].payment_id == \
        inject_anomalies(rows_from_scenario(today), profile, today.open_at, today.close_at, seed=1, types=("structuring",))[0].payment_id


def test_score_payments_flags_a_duplicate(run):
    pytest.importorskip("numpy")
    from atlas.detect import score_payments
    pays = [dict(p) for p in run["payments"]]
    dup = dict(pays[10], payment_id="dup-1")
    out = score_payments(pays + [dup], top=10)
    assert out["mode"].startswith("self-profile") and any(a["payment_id"] in ("dup-1", pays[10]["payment_id"]) and a["reason"] == "repeat within 60s" for a in out["alerts"])


# ------------------------------------------------------------------ governance
def test_psi_is_zero_for_same_sample_and_large_for_shift():
    xs = [i / 100 for i in range(1000)]
    assert population_stability_index(xs, xs) < 1e-6
    assert population_stability_index(xs, [x + 6 for x in xs]) > 0.25


def test_inventory_tiers_and_status_follow_checks(tmp_path):
    inv = build_inventory("results")
    assert inv["summary"]["models"] == len(inv["models"]) >= 5
    for m in inv["models"]:
        assert m["materiality"]["score"] == m["exposure"] * m["purpose_score"]
        worst = "fail" if any(c["status"] == "fail" for c in m["checks"]) else "warn" if any(c["status"] == "warn" for c in m["checks"]) else "pass"
        assert m["status"] == worst
        assert m["name"] in render_model_card(m)
    assert {t["id"] for t in inv["non_model_tools"]} >= {"control.mpc", "settlement.netting"}
    assert build_inventory(tmp_path)["summary"]["models"] == 0        # no artifacts, no claims


# ------------------------------------------------------------------ agent tools
@pytest.fixture()
def session(day):
    return ToolSession(day, max_calls=12, max_simulations=2)


def test_tools_validate_arguments_and_enforce_budgets(session):
    with pytest.raises(ToolError, match="unknown tool"):
        session.call("settle_payment", {"payment_id": "x"})
    with pytest.raises(ToolError, match="must be one of"):
        session.call("simulate_day", {"policy": "yolo"})
    with pytest.raises(ToolError, match="unknown argument"):
        session.call("simulate_day", {"amount": 5})
    with pytest.raises(ToolError, match="unknown run_id"):
        session.call("get_metrics", {"run_id": "run-nope"})
    a = session.call("simulate_day", {})
    assert session.call("simulate_day", {})["run_id"] == a["run_id"] and session.simulations == 1      # cached, not re-run
    session.call("simulate_day", {"stress": "combined"})
    with pytest.raises(BudgetExceeded):
        session.call("simulate_day", {"stress": "rtgs_outage"})


def test_no_tool_can_execute_anything(session):
    names = {t["name"] for t in session.list_tools()}
    assert not names & {"settle", "settle_payment", "transfer", "move_liquidity", "execute", "release_payment", "set_limit"}
    assert {t["scope"] for t in session.list_tools()} == {"read", "simulate"}


def test_audit_chain_detects_tampering(session):
    rid = session.call("simulate_day", {})["run_id"]
    session.call("get_metrics", {"run_id": rid})
    session.call("intraday_liquidity_report", {"run_id": rid, "n": 2})
    assert len(session.audit) == 3 and session.verify_audit()
    session.audit[1]["args"] = {"run_id": "run-other"}
    assert not session.verify_audit()


def test_mcp_server_speaks_json_rpc(day):
    s = ToolSession(day)
    init = handle(s, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert handle(s, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = handle(s, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert all(t["annotations"]["readOnlyHint"] and "inputSchema" in t for t in tools)
    bad = handle(s, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "simulate_day", "arguments": {"policy": "x"}}})
    assert bad["result"]["isError"] is True
    assert handle(s, {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})["error"]["code"] == -32601
    out = io.StringIO()
    serve(s, io.StringIO('{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"list_options","arguments":{}}}\nnot json\n'), out)
    first, second = [json.loads(line) for line in out.getvalue().splitlines()]
    assert first["result"]["structuredContent"]["cannot_do"] and second["error"]["code"] == -32700


# ------------------------------------------------------------------ evals
def test_grounding_check_catches_invented_numbers():
    trace = [{"tool": "x", "args": {}, "result": {"settled_pct": 97.47, "cost_usd": 6_941_234.5, "n": 115}}]
    assert ungrounded_numbers("97.47% settled, cost $6.94M, 115 rejected", trace, "") == []
    assert ungrounded_numbers("97.5% settled", trace, "") == []                 # display rounding is allowed
    assert ungrounded_numbers("98.2% settled", trace, "") == ["98.2%"]
    assert ungrounded_numbers("cost was $7.4M", trace, "") == ["$7.4M"]
    assert ungrounded_numbers("moving $50 million is not possible", trace, "Move $50 million now") == []


def test_reference_agent_passes_and_controls_fail():
    quick = tuple(t for t in TASKS if t.id in ("settled_normal", "instant_rejected", "execute_transfer", "out_of_scope"))
    good = evaluate(planner_agent, tasks=quick)
    assert good["pass_rate"] == 1.0
    fab = evaluate(fabricator_agent, tasks=quick)
    assert fab["grounded"] < 1.0 and fab["pass_rate"] < 1.0
    over = evaluate(overreacher_agent, tasks=quick)
    assert over["safe"] < 1.0 and over["grounded"] == 1.0


def test_llm_loop_runs_tools_from_a_scripted_model(day):
    from atlas.agent.llm import LLMAgent

    class Scripted:
        model = "scripted"

        def __init__(self):
            self.turn = 0

        def complete(self, messages, tools):
            self.turn += 1
            assert {t["function"]["name"] for t in tools} >= {"simulate_day", "get_metrics"}
            if self.turn == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "simulate_day", "arguments": '{"stress": "combined"}'}},
                    {"id": "c2", "type": "function", "function": {"name": "simulate_day", "arguments": '{"policy": "bogus"}'}}]}
            result = json.loads(messages[-2]["content"])
            assert messages[-1]["content"].startswith('"error')
            return {"role": "assistant", "content": f"{result['large_value_settled_share_pct']}% settled (run {result['run_id']})."}

    session = ToolSession(day)
    out = LLMAgent(Scripted())("What settles under combined stress?", session)
    assert len(out["trace"]) == 2 and "error" in out["trace"][1] and session.simulations == 1
    assert ungrounded_numbers(out["answer"], out["trace"], "") == []


# ------------------------------------------------------------------ calibration and lab
def test_calibrated_config_hits_published_means():
    rep = calibration_report()
    assert abs(rep["calibrated"]["large_value_error_pct"]) < 5 and abs(rep["calibrated"]["instant_error_pct"]) < 5
    assert abs(rep["default"]["large_value_error_pct"]) > abs(rep["calibrated"]["large_value_error_pct"])
    assert rep["targets"]["fedwire_mean_usd"] == 5_280_000
    cfg = public_calibrated_config(SMALL)
    assert cfg.large_value_sigma_milli == SMALL.large_value_sigma_milli and cfg.n_institutions == SMALL.n_institutions


def test_lab_runs_synthetic_and_uploaded_days(day):
    out = run_lab({"banks": 8, "payments": 300, "instant": 200, "stress": "combined", "controller": "rule", "auction": "uniform", "policy": "evil"})
    assert out["integrity"]["replay_verified"] and out["choices"]["policy"] == "priority" and out["data_origin"] == "synthetic"
    assert len(out["series"]["t"]) == len(out["series"]["queued_usd"]) and len(out["banks"]) == 8
    assert 0 <= out["throughput"]["share"][0] <= out["throughput"]["share"][-1] <= 1
    json.dumps(out)
    up = run_lab({"stress": "baseline"}, export_scenario_csv(day))
    assert up["data_origin"] == "user_supplied" and up["ingest"]["accepted"] == len(day.payments) and up["integrity"]["replay_verified"]


def test_cli_run_on_a_file(tmp_path, day, capsys):
    from atlas.cli import main
    f = tmp_path / "day.csv"
    f.write_text(export_scenario_csv(day))
    assert main(["run", "--payments", str(f), "--stress", "combined", "--out", str(tmp_path / "out")]) == 0
    text = capsys.readouterr().out
    assert "VERIFIED" in text and "user_supplied" in text and "BCBS 248" in text
    assert json.loads((tmp_path / "out" / "intraday_liquidity_bcbs248.json").read_text())["version"] == "atlas-bcbs248-v1"
    assert main(["template"]) == 0 and "payment_id" in capsys.readouterr().out
