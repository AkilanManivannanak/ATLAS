from datetime import UTC, date, datetime

import pytest

from atlas.domain import CurrencySpec, Money, PaymentStatus
from atlas.iso20022 import MessageValidationError, build_pacs004, build_pacs008, build_pacs009, normalize, to_payment_instruction

USD = CurrencySpec("USD", 2)
T = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)


def tx(e2e="E2E-1", amount="100.25", dbtr="ALPHUS33XXX", cdtr="BETAUS33", **kw):
    d = {"end_to_end_id": e2e, "amount": Money.from_major_units(amount, USD), "settlement_date": date(2026, 1, 6),
         "debtor_bic": dbtr, "creditor_bic": cdtr}
    d.update(kw)
    return d


def test_pacs008_round_trip_and_provenance():
    xml = build_pacs008("MSG1", T, [tx(uetr="3f1b2c4d-1a2b-4c3d-8e9f-0a1b2c3d4e5f"), tx("E2E-2", "0.75")])
    msg = normalize(xml)
    assert msg.message_definition == "pacs.008.001.08" and msg.family == "pacs.008"
    assert [t.amount.amount_minor for t in msg.transactions] == [10025, 75]
    assert msg.original_payload == xml.encode()
    assert len(msg.original_sha256) == 64
    p = to_payment_instruction(msg, msg.transactions[0], payment_rail_id="rtgs",
                               institution_for_bic=lambda b: b[:4].lower(), account_for_institution=lambda i, r: f"{i}-{r}")
    assert p.status == PaymentStatus.CREATED and p.amount_minor == 10025
    assert p.source_message_id == "MSG1" and p.message_schema_version == "pacs.008.001.08"


def test_pacs009_and_pacs004():
    assert normalize(build_pacs009("M9", T, [tx()])).family == "pacs.009"
    ret = normalize(build_pacs004("M4", T, [{"return_id": "R1", "original_end_to_end_id": "E2E-1",
                                              "amount": Money.from_major_units("100.25", USD), "settlement_date": date(2026, 1, 6),
                                              "debtor_bic": "BETAUS33", "creditor_bic": "ALPHUS33XXX", "reason_code": "AC04"}]))
    assert ret.transactions[0].return_reason_code == "AC04"
    assert ret.transactions[0].original_end_to_end_id == "E2E-1"
    with pytest.raises(ValueError, match="separate instructions"):
        to_payment_instruction(ret, ret.transactions[0], payment_rail_id="r", institution_for_bic=str, account_for_institution=lambda i, r: i)


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda x: x.replace("<NbOfTxs>1</NbOfTxs>", "<NbOfTxs>2</NbOfTxs>"), "does not match"),
        (lambda x: x.replace("BETAUS33", "bad bic"), "valid BICFI"),
        (lambda x: x.replace(">100.25<", ">100.255<"), "fractional digits"),
        (lambda x: x.replace('Ccy="USD">100.25</IntrBk', 'Ccy="XXX">100.25</IntrBk'), "not in currency registry"),
        (lambda x: x.replace("pacs.008.001.08", "pacs.008.001.02"), "unsupported message"),
        (lambda x: x.replace("<EndToEndId>E2E-1</EndToEndId>", ""), "EndToEndId"),
        (lambda x: x[:-20], "malformed XML"),
        (lambda x: x.replace(">100.25</TtlIntrBkSttlmAmt>", ">99.00</TtlIntrBkSttlmAmt>"), "sum of transaction"),
    ],
)
def test_validation_failures_are_reported(mutate, needle):
    with pytest.raises(MessageValidationError) as err:
        normalize(mutate(build_pacs008("MSG1", T, [tx()])))
    assert needle in str(err.value)


def test_rejects_entity_expansion_and_xxe():
    evil = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"/>'
    with pytest.raises(MessageValidationError, match="DOCTYPE"):
        normalize(evil)


def test_same_agent_rejected():
    with pytest.raises(MessageValidationError, match="must differ"):
        normalize(build_pacs008("M", T, [tx(cdtr="ALPHUS33XXX")]))
