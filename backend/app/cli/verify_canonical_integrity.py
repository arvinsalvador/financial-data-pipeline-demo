from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import (
    BankAccount,
    BankTransaction,
    CanonicalRecordLineage,
    CreditAccount,
    CreditCardTransaction,
    Employee,
    FinancialTransaction,
    NormalizationControlTotal,
    PayrollEntry,
    PayrollRun,
)


def main() -> None:
    errors: list[str] = []
    with SessionLocal() as session:
        transactions = list(session.scalars(select(FinancialTransaction)).all())
        for transaction in transactions:
            lineage = (
                session.scalar(
                    select(func.count())
                    .select_from(CanonicalRecordLineage)
                    .where(
                        CanonicalRecordLineage.tenant_id == transaction.tenant_id,
                        CanonicalRecordLineage.canonical_entity_type.in_(
                            ("bank_transaction", "credit_card_transaction")
                        ),
                        CanonicalRecordLineage.source_file_id == transaction.source_file_id,
                        CanonicalRecordLineage.source_row_number == transaction.source_row_number,
                    )
                )
                or 0
            )
            if not lineage:
                errors.append(f"financial transaction {transaction.id}: missing lineage")
        broken_bank = (
            session.scalar(
                select(func.count())
                .select_from(BankTransaction)
                .join(BankAccount, BankAccount.id == BankTransaction.bank_account_id)
                .join(
                    FinancialTransaction,
                    FinancialTransaction.id == BankTransaction.financial_transaction_id,
                )
                .where(
                    (BankTransaction.tenant_id != BankAccount.tenant_id)
                    | (BankTransaction.tenant_id != FinancialTransaction.tenant_id)
                )
            )
            or 0
        )
        if broken_bank:
            errors.append("bank transaction/account cross-tenant relationship")
        broken_card = (
            session.scalar(
                select(func.count())
                .select_from(CreditCardTransaction)
                .join(CreditAccount, CreditAccount.id == CreditCardTransaction.credit_account_id)
                .join(
                    FinancialTransaction,
                    FinancialTransaction.id == CreditCardTransaction.financial_transaction_id,
                )
                .where(
                    (CreditCardTransaction.tenant_id != CreditAccount.tenant_id)
                    | (CreditCardTransaction.tenant_id != FinancialTransaction.tenant_id)
                )
            )
            or 0
        )
        if broken_card:
            errors.append("credit-card transaction/account cross-tenant relationship")
        broken_payroll = (
            session.scalar(
                select(func.count())
                .select_from(PayrollEntry)
                .join(PayrollRun, PayrollRun.id == PayrollEntry.payroll_run_id)
                .join(Employee, Employee.id == PayrollEntry.employee_id)
                .where(
                    (PayrollEntry.tenant_id != PayrollRun.tenant_id)
                    | (PayrollEntry.tenant_id != Employee.tenant_id)
                )
            )
            or 0
        )
        if broken_payroll:
            errors.append("payroll entry cross-tenant relationship")
        entries = list(session.scalars(select(PayrollEntry)).all())
        for entry in entries:
            lineage = (
                session.scalar(
                    select(func.count())
                    .select_from(CanonicalRecordLineage)
                    .where(
                        CanonicalRecordLineage.tenant_id == entry.tenant_id,
                        CanonicalRecordLineage.canonical_entity_type == "payroll_entry",
                        CanonicalRecordLineage.canonical_entity_id == entry.id,
                    )
                )
                or 0
            )
            if not lineage:
                errors.append(f"payroll entry {entry.id}: missing lineage")
        mismatches = (
            session.scalar(
                select(func.count())
                .select_from(NormalizationControlTotal)
                .where(NormalizationControlTotal.status == "mismatch")
            )
            or 0
        )
        if mismatches:
            errors.append(f"normalization control mismatches={mismatches}")
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print(
        f"canonical integrity verified: transactions={len(transactions)} "
        f"payroll_entries={len(entries)} errors=0"
    )


if __name__ == "__main__":
    main()
