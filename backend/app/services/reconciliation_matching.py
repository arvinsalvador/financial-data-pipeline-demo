import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import combinations
from typing import Any


@dataclass(frozen=True)
class BankRecord:
    bank_transaction_id: int
    financial_transaction_id: int
    transaction_date: date
    signed_amount: Decimal
    reference: str
    description: str
    canonical_hash: str
    source_row_number: int
    validation_blocked: bool = False


@dataclass(frozen=True)
class LedgerRecord:
    ledger_record_id: str
    row_number: int
    entry_date: date
    signed_amount: Decimal
    reference: str
    description: str
    journal_entry_id: str
    account_code: str
    row_hash: str
    validation_blocked: bool = False


@dataclass(frozen=True)
class CandidateScore:
    rule_code: str
    confidence: Decimal
    amount_difference: Decimal
    date_difference_days: int
    reference_score: Decimal
    description_score: Decimal
    amount_score: Decimal
    date_score: Decimal
    reasons: dict[str, Any]


def normalize_reference(value: str, prefixes: tuple[str, ...] = ()) -> str:
    normalized = " ".join(re.sub(r"[^\w\s-]", " ", value.casefold()).split())
    for prefix in prefixes:
        marker = f"{prefix.casefold()} "
        if normalized.startswith(marker):
            normalized = normalized[len(marker) :]
            break
    return normalized


def normalize_description(value: str, boilerplate: tuple[str, ...] = ()) -> str:
    normalized = " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())
    tokens = [
        token
        for token in normalized.split()
        if token not in {item.casefold() for item in boilerplate}
    ]
    return " ".join(tokens)


def token_similarity(left: str, right: str) -> Decimal:
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return Decimal(0)
    return (
        Decimal(len(left_tokens & right_tokens)) / Decimal(len(left_tokens | right_tokens))
    ).quantize(Decimal("0.000001"))


def score_candidate(
    bank: BankRecord, ledger: LedgerRecord, date_tolerance: int, amount_tolerance: Decimal
) -> CandidateScore | None:
    amount_difference = abs(bank.signed_amount - ledger.signed_amount)
    if amount_difference > amount_tolerance or bank.signed_amount * ledger.signed_amount < 0:
        return None
    date_difference = abs((bank.transaction_date - ledger.entry_date).days)
    if date_difference > date_tolerance:
        return None
    bank_reference = normalize_reference(bank.reference)
    ledger_reference = normalize_reference(ledger.reference)
    reference_score = (
        Decimal(1)
        if bank_reference and bank_reference == ledger_reference
        else token_similarity(bank_reference, ledger_reference)
    )
    description_score = token_similarity(
        normalize_description(bank.description), normalize_description(ledger.description)
    )
    amount_score = max(
        Decimal(0), Decimal(1) - amount_difference / max(abs(bank.signed_amount), Decimal(1))
    )
    date_score = max(
        Decimal(0), Decimal(1) - Decimal(date_difference) / Decimal(max(date_tolerance + 1, 1))
    )
    if reference_score == 1:
        rule_code, confidence = "exact_reference_amount", Decimal("1.000000")
    elif date_difference == 0:
        rule_code, confidence = "exact_amount_exact_date", Decimal("0.980000")
    elif description_score >= Decimal("0.35"):
        rule_code = "normalized_description_amount"
        confidence = min(
            Decimal("0.950000"),
            Decimal("0.70") + description_score * Decimal("0.20") + date_score * Decimal("0.05"),
        )
    else:
        rule_code = "exact_amount_date_tolerance"
        confidence = max(
            Decimal("0.700000"),
            Decimal("0.950000") - Decimal(date_difference) * Decimal("0.050000"),
        )
    return CandidateScore(
        rule_code,
        confidence.quantize(Decimal("0.000001")),
        amount_difference,
        date_difference,
        reference_score,
        description_score,
        amount_score.quantize(Decimal("0.000001")),
        date_score.quantize(Decimal("0.000001")),
        {
            "normalized_bank_reference": bank_reference,
            "normalized_ledger_reference": ledger_reference,
            "normalized_bank_description": normalize_description(bank.description),
            "normalized_ledger_description": normalize_description(ledger.description),
            "economic_direction_equal": True,
        },
    )


def bounded_exact_groups(
    target: Decimal,
    records: list[tuple[str, Decimal, date]],
    anchor_date: date,
    maximum_size: int,
    date_tolerance: int,
    amount_tolerance: Decimal,
    maximum_results: int = 10,
) -> list[tuple[str, ...]]:
    eligible = sorted(
        (
            (key, amount, record_date)
            for key, amount, record_date in records
            if amount * target > 0 and abs((record_date - anchor_date).days) <= date_tolerance
        ),
        key=lambda item: (item[2], item[0]),
    )
    results: list[tuple[str, ...]] = []
    for size in range(2, min(maximum_size, len(eligible)) + 1):
        for group in combinations(eligible, size):
            if abs(sum((item[1] for item in group), Decimal(0)) - target) <= amount_tolerance:
                results.append(tuple(item[0] for item in group))
                if len(results) >= maximum_results:
                    return results
    return results


def stable_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
