from typing import Final

PROFILE_STEPS: Final[tuple[str, ...]] = (
    "load_registered_file",
    "detect_encoding_and_delimiter",
    "inspect_schema",
    "calculate_file_statistics",
    "calculate_column_statistics",
    "run_data_quality_rules",
    "validate_running_balance",
    "persist_profile",
    "finalize_profile",
)

COLUMN_ALIASES: Final[dict[str, frozenset[str]]] = {
    "transaction_date": frozenset(
        {
            "transaction_date",
            "date",
            "posted_date",
            "posting_date",
            "transaction date",
            "posted date",
        }
    ),
    "amount": frozenset(
        {"amount", "transaction_amount", "transaction amount", "net_amount", "total"}
    ),
    "debit": frozenset({"debit", "debit_amount", "debit amount", "withdrawal", "withdrawals"}),
    "credit": frozenset({"credit", "credit_amount", "credit amount", "deposit", "deposits"}),
    "balance": frozenset({"balance", "running_balance", "running balance", "account_balance"}),
    "identifier": frozenset(
        {
            "id",
            "transaction_id",
            "transaction id",
            "reference",
            "reference_number",
            "reference number",
        }
    ),
}


def normalize_column_name(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split())


def identify_columns(headers: list[str]) -> dict[str, str]:
    identified: dict[str, str] = {}
    for header in headers:
        normalized = normalize_column_name(header)
        for concept, aliases in COLUMN_ALIASES.items():
            if normalized in {normalize_column_name(alias) for alias in aliases}:
                identified.setdefault(concept, header)
    return identified
