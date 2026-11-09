"""Versioned ISO 20022 normalization layer.

Scope and honesty notes
-----------------------
* ATLAS performs **structural** validation (required elements, identifier formats,
  currency precision, group-header counts, settlement-amount totals). It does not
  bundle or execute the official XSDs, and it does not implement any market
  infrastructure's usage guidelines. A message that passes here is "well-formed
  for the ATLAS simulator", nothing more.
* Message identifiers follow the public ISO 20022 catalogue naming
  (https://www.iso20022.org/iso-20022-message-definitions). The versions listed in
  ``SUPPORTED_MESSAGES`` are the ones this normalizer has mappings and tests for.
* The original payload is never discarded: every ``NormalizedMessage`` keeps the
  SHA-256 of the exact bytes received plus the bytes themselves.
* XML with a DOCTYPE or entity declaration is rejected before parsing to block
  XXE and entity-expansion attacks.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from atlas.domain import CurrencyRegistry, CurrencySpec, Money, PaymentInstruction

CANONICAL_SCHEMA_VERSION = "atlas-canonical-payment-v1"
TRANSFORMATION_VERSION = "atlas-iso20022-normalizer-v1"
_NS_PREFIX = "urn:iso:std:iso:20022:tech:xsd:"

# message family -> (root business element, transaction element)
SUPPORTED_MESSAGES: Mapping[str, tuple[str, str]] = {
    "pacs.008.001.08": ("FIToFICstmrCdtTrf", "CdtTrfTxInf"),
    "pacs.009.001.08": ("FICdtTrf", "CdtTrfTxInf"),
    "pacs.004.001.10": ("PmtRtr", "TxInf"),
}

DEFAULT_CURRENCIES = CurrencyRegistry("atlas-iso-currencies-v1", (CurrencySpec("USD", 2), CurrencySpec("EUR", 2), CurrencySpec("JPY", 0)))

_BIC = re.compile(r"^[A-Z0-9]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_MAX35 = 35
_UETR = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")


class MessageValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    instruction_id: str | None
    end_to_end_id: str
    uetr: str | None
    amount: Money
    settlement_date: date
    debtor_agent_bic: str
    creditor_agent_bic: str
    original_end_to_end_id: str | None = None
    return_reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    message_definition: str
    message_id: str
    created_at: datetime
    settlement_method: str | None
    transactions: tuple[NormalizedTransaction, ...]
    original_sha256: str
    original_payload: bytes = field(repr=False)
    canonical_schema_version: str = CANONICAL_SCHEMA_VERSION
    transformation_version: str = TRANSFORMATION_VERSION
    ingested_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def family(self) -> str:
        return self.message_definition[:8]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: ET.Element, path: str, ns: str) -> ET.Element | None:
    q = "/".join(f"{{{ns}}}{part}" for part in path.split("/"))
    return node.find(q)


def _text(node: ET.Element, path: str, ns: str, errors: list[str], *, required: bool = True, max_len: int | None = None) -> str | None:
    el = _find(node, path, ns)
    if el is None or el.text is None or not el.text.strip():
        if required:
            errors.append(f"missing required element {path}")
        return None
    value = el.text.strip()
    if max_len is not None and len(value) > max_len:
        errors.append(f"{path} exceeds {max_len} characters")
    return value


def _parse_amount(node: ET.Element, path: str, ns: str, errors: list[str], registry: CurrencyRegistry) -> Money | None:
    el = _find(node, path, ns)
    if el is None or el.text is None:
        errors.append(f"missing required element {path}")
        return None
    ccy = el.attrib.get("Ccy")
    if not ccy:
        errors.append(f"{path} missing Ccy attribute")
        return None
    try:
        spec = registry.get(ccy)
    except KeyError:
        errors.append(f"{path} currency {ccy!r} is not in currency registry {registry.version!r}")
        return None
    try:
        value = Decimal(el.text.strip())
    except InvalidOperation:
        errors.append(f"{path} is not a decimal amount")
        return None
    if value <= 0:
        errors.append(f"{path} must be positive")
        return None
    try:
        return Money.from_major_units(value, spec)
    except ValueError as exc:
        errors.append(f"{path}: {exc}")
        return None


def _bic(node: ET.Element, path: str, ns: str, errors: list[str]) -> str | None:
    value = _text(node, path, ns, errors)
    if value is not None and not _BIC.match(value):
        errors.append(f"{path} is not a valid BICFI")
    return value


def _reject_dangerous_xml(payload: bytes) -> None:
    head = payload[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in payload.upper():
        raise MessageValidationError(["DOCTYPE/ENTITY declarations are not permitted"])


def normalize(payload: bytes | str, *, registry: CurrencyRegistry = DEFAULT_CURRENCIES) -> NormalizedMessage:
    """Parse, validate and normalize one ISO 20022 message. Raises MessageValidationError."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    _reject_dangerous_xml(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise MessageValidationError([f"malformed XML: {exc}"]) from exc
    if _local(root.tag) != "Document" or not root.tag.startswith("{" + _NS_PREFIX):
        raise MessageValidationError(["root element must be an ISO 20022 Document"])
    ns = root.tag[1:].split("}", 1)[0]
    definition = ns[len(_NS_PREFIX):]
    if definition not in SUPPORTED_MESSAGES:
        raise MessageValidationError([f"unsupported message definition {definition!r}"])
    business_tag, tx_tag = SUPPORTED_MESSAGES[definition]
    body = _find(root, business_tag, ns)
    if body is None:
        raise MessageValidationError([f"missing business element {business_tag}"])
    errors: list[str] = []
    msg_id = _text(body, "GrpHdr/MsgId", ns, errors, max_len=_MAX35)
    created_raw = _text(body, "GrpHdr/CreDtTm", ns, errors)
    created_at: datetime | None = None
    if created_raw:
        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            if created_at.tzinfo is None:
                errors.append("GrpHdr/CreDtTm must include a UTC offset")
        except ValueError:
            errors.append("GrpHdr/CreDtTm is not an ISO date-time")
    nb = _text(body, "GrpHdr/NbOfTxs", ns, errors)
    sttlm = _text(body, "GrpHdr/SttlmInf/SttlmMtd", ns, errors, required=False)
    tx_nodes = body.findall(f"{{{ns}}}{tx_tag}")
    if not tx_nodes:
        errors.append(f"message contains no {tx_tag} elements")
    if nb is not None and (not nb.isdigit() or int(nb) != len(tx_nodes)):
        errors.append(f"GrpHdr/NbOfTxs={nb} does not match {len(tx_nodes)} transactions")

    is_return = definition.startswith("pacs.004")
    txs: list[NormalizedTransaction] = []
    seen_e2e: set[str] = set()
    for i, tx in enumerate(tx_nodes):
        tx_errors: list[str] = []
        if is_return:
            amount = _parse_amount(tx, "RtrdIntrBkSttlmAmt", ns, tx_errors, registry)
            e2e = _text(tx, "RtrId", ns, tx_errors, max_len=_MAX35)
            original_e2e = _text(tx, "OrgnlEndToEndId", ns, tx_errors, max_len=_MAX35)
            instr = _text(tx, "OrgnlInstrId", ns, tx_errors, required=False, max_len=_MAX35)
            reason = _text(tx, "RtrRsnInf/Rsn/Cd", ns, tx_errors)
            uetr = _text(tx, "OrgnlUETR", ns, tx_errors, required=False)
        else:
            amount = _parse_amount(tx, "IntrBkSttlmAmt", ns, tx_errors, registry)
            e2e = _text(tx, "PmtId/EndToEndId", ns, tx_errors, max_len=_MAX35)
            instr = _text(tx, "PmtId/InstrId", ns, tx_errors, required=False, max_len=_MAX35)
            uetr = _text(tx, "PmtId/UETR", ns, tx_errors, required=False)
            original_e2e, reason = None, None
        if uetr is not None and not _UETR.match(uetr):
            tx_errors.append("UETR must be a lowercase UUIDv4")
        sttl_raw = _text(tx, "IntrBkSttlmDt", ns, tx_errors)
        sttl_date: date | None = None
        if sttl_raw:
            try:
                sttl_date = date.fromisoformat(sttl_raw)
            except ValueError:
                tx_errors.append("IntrBkSttlmDt is not an ISO date")
        dbtr = _bic(tx, "DbtrAgt/FinInstnId/BICFI", ns, tx_errors)
        cdtr = _bic(tx, "CdtrAgt/FinInstnId/BICFI", ns, tx_errors)
        if dbtr and cdtr and dbtr == cdtr:
            tx_errors.append("debtor and creditor agents must differ for interbank settlement")
        if e2e and e2e in seen_e2e:
            tx_errors.append(f"duplicate end-to-end/return identifier {e2e!r} inside message")
        if e2e:
            seen_e2e.add(e2e)
        if tx_errors:
            errors.extend(f"{tx_tag}[{i}]: {err}" for err in tx_errors)
            continue
        assert amount and e2e and sttl_date and dbtr and cdtr
        txs.append(NormalizedTransaction(instr, e2e, uetr, amount, sttl_date, dbtr, cdtr, original_e2e, reason))

    if not is_return:
        total = _find(body, "GrpHdr/TtlIntrBkSttlmAmt", ns)
        if total is not None and txs and not errors:
            total_money = _parse_amount(body, "GrpHdr/TtlIntrBkSttlmAmt", ns, errors, registry)
            if total_money is not None:
                if len({t.amount.currency for t in txs}) != 1 or total_money.currency != txs[0].amount.currency:
                    errors.append("GrpHdr/TtlIntrBkSttlmAmt currency does not match transactions")
                elif total_money.amount_minor != sum(t.amount.amount_minor for t in txs):
                    errors.append("GrpHdr/TtlIntrBkSttlmAmt does not equal the sum of transaction amounts")
    if errors:
        raise MessageValidationError(errors)
    assert msg_id and created_at
    return NormalizedMessage(
        message_definition=definition, message_id=msg_id, created_at=created_at, settlement_method=sttlm,
        transactions=tuple(txs), original_sha256=hashlib.sha256(raw).hexdigest(), original_payload=raw,
    )


def to_payment_instruction(
    message: NormalizedMessage,
    tx: NormalizedTransaction,
    *,
    payment_rail_id: str,
    institution_for_bic: Callable[[str], str],
    account_for_institution: Callable[[str, str], str],
    priority: int = 1,
    due_after: timedelta = timedelta(hours=2),
    scenario_id: str | None = None,
) -> PaymentInstruction:
    """Map a normalized credit transfer to a CREATED PaymentInstruction with provenance."""
    if message.family == "pacs.004":
        raise ValueError("returns are separate instructions; map pacs.004 with explicit return handling")
    sender = institution_for_bic(tx.debtor_agent_bic)
    receiver = institution_for_bic(tx.creditor_agent_bic)
    return PaymentInstruction(
        payment_id=f"{message.message_id}:{tx.end_to_end_id}",
        end_to_end_id=tx.end_to_end_id,
        instruction_id=tx.instruction_id or tx.end_to_end_id,
        sender_institution_id=sender,
        receiver_institution_id=receiver,
        sender_account_id=account_for_institution(sender, payment_rail_id),
        receiver_account_id=account_for_institution(receiver, payment_rail_id),
        payment_rail_id=payment_rail_id,
        currency=tx.amount.currency,
        amount_minor=tx.amount.amount_minor,
        priority=priority,
        created_at=message.created_at,
        due_at=message.created_at + due_after,
        source_message_id=message.message_id,
        message_schema_version=message.message_definition,
        scenario_id=scenario_id,
    )


# ------------------------------------------------------------------ builders
def _fmt_amount(money: Money, registry: CurrencyRegistry) -> str:
    exp = registry.get(money.currency).minor_unit_exponent
    if exp == 0:
        return str(money.amount_minor)
    sign = "-" if money.amount_minor < 0 else ""
    v = abs(money.amount_minor)
    return f"{sign}{v // 10**exp}.{v % 10**exp:0{exp}d}"


def _agent(tag: str, bic: str) -> str:
    return f"<{tag}><FinInstnId><BICFI>{escape(bic)}</BICFI></FinInstnId></{tag}>"


def _credit_transfer(definition: str, msg_id: str, created_at: datetime, txs: list[dict], registry: CurrencyRegistry) -> str:
    business, _ = SUPPORTED_MESSAGES[definition]
    total = sum(t["amount"].amount_minor for t in txs)
    ccy = txs[0]["amount"].currency
    parts = [
        f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{_NS_PREFIX}{definition}"><{business}>',
        f"<GrpHdr><MsgId>{escape(msg_id)}</MsgId><CreDtTm>{created_at.isoformat()}</CreDtTm><NbOfTxs>{len(txs)}</NbOfTxs>",
        f'<TtlIntrBkSttlmAmt Ccy="{ccy}">{_fmt_amount(Money(ccy, total), registry)}</TtlIntrBkSttlmAmt>',
        "<SttlmInf><SttlmMtd>CLRG</SttlmMtd></SttlmInf></GrpHdr>",
    ]
    for t in txs:
        pmt_id = f"<InstrId>{escape(t.get('instruction_id') or t['end_to_end_id'])}</InstrId><EndToEndId>{escape(t['end_to_end_id'])}</EndToEndId>"
        if t.get("uetr"):
            pmt_id += f"<UETR>{t['uetr']}</UETR>"
        parts.append(
            f"<CdtTrfTxInf><PmtId>{pmt_id}</PmtId>"
            f'<IntrBkSttlmAmt Ccy="{t["amount"].currency}">{_fmt_amount(t["amount"], registry)}</IntrBkSttlmAmt>'
            f"<IntrBkSttlmDt>{t['settlement_date'].isoformat()}</IntrBkSttlmDt>"
            f"{_agent('DbtrAgt', t['debtor_bic'])}{_agent('CdtrAgt', t['creditor_bic'])}</CdtTrfTxInf>"
        )
    parts.append(f"</{business}></Document>")
    return "".join(parts)


def build_pacs008(msg_id: str, created_at: datetime, transactions: list[dict], registry: CurrencyRegistry = DEFAULT_CURRENCIES) -> str:
    """Build a minimal synthetic pacs.008.001.08. Each tx dict: end_to_end_id, amount (Money),
    settlement_date, debtor_bic, creditor_bic, optional instruction_id/uetr."""
    return _credit_transfer("pacs.008.001.08", msg_id, created_at, transactions, registry)


def build_pacs009(msg_id: str, created_at: datetime, transactions: list[dict], registry: CurrencyRegistry = DEFAULT_CURRENCIES) -> str:
    return _credit_transfer("pacs.009.001.08", msg_id, created_at, transactions, registry)


def build_pacs004(msg_id: str, created_at: datetime, returns: list[dict], registry: CurrencyRegistry = DEFAULT_CURRENCIES) -> str:
    """Each return dict: return_id, original_end_to_end_id, amount, settlement_date, debtor_bic, creditor_bic, reason_code."""
    definition = "pacs.004.001.10"
    parts = [
        f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{_NS_PREFIX}{definition}"><PmtRtr>',
        f"<GrpHdr><MsgId>{escape(msg_id)}</MsgId><CreDtTm>{created_at.isoformat()}</CreDtTm><NbOfTxs>{len(returns)}</NbOfTxs>",
        "<SttlmInf><SttlmMtd>CLRG</SttlmMtd></SttlmInf></GrpHdr>",
    ]
    for r in returns:
        parts.append(
            f"<TxInf><RtrId>{escape(r['return_id'])}</RtrId><OrgnlEndToEndId>{escape(r['original_end_to_end_id'])}</OrgnlEndToEndId>"
            f'<RtrdIntrBkSttlmAmt Ccy="{r["amount"].currency}">{_fmt_amount(r["amount"], registry)}</RtrdIntrBkSttlmAmt>'
            f"<IntrBkSttlmDt>{r['settlement_date'].isoformat()}</IntrBkSttlmDt>"
            f"<RtrRsnInf><Rsn><Cd>{escape(r['reason_code'])}</Cd></Rsn></RtrRsnInf>"
            f"{_agent('DbtrAgt', r['debtor_bic'])}{_agent('CdtrAgt', r['creditor_bic'])}</TxInf>"
        )
    parts.append("</PmtRtr></Document>")
    return "".join(parts)
