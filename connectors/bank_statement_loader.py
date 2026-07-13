"""
GuardianRecon — Bank Statement Loader
=========================================
يقرأ كشف حساب بنكي (CSV/Excel) ويحوله لقائمة BankTransaction
جاهزة، مع تطبيق التنظيف والتصنيف تلقائياً (engine.classifier).
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
import pandas as pd

from ..engine.models import BankTransaction
from ..engine.classifier import process_transaction


def load_bank_statement(
    path: str,
    date_col: str = "Value Date",
    debit_col: str = "Debit Amount",
    credit_col: str = "Credit Amount",
    desc_col: str = "Details",
    ref_col: Optional[str] = "Reference No",
    party_col: Optional[str] = None,
    date_format: Optional[str] = None,
) -> List[BankTransaction]:
    """
    يدعم CSV و Excel. الأعمدة الافتراضية مطابقة لتنسيق البنوك السعودية
    الشائع (SABB / NCB / Al Rajhi / Riyad Bank) المستخدم في clean-bank-statement-ar.
    """
    if path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    df.columns = [c.strip() for c in df.columns]

    transactions = []
    for _, row in df.iterrows():
        debit = float(row.get(debit_col, 0) or 0)
        credit = float(row.get(credit_col, 0) or 0)
        amount = credit - debit

        raw_date = row.get(date_col)
        if isinstance(raw_date, str) and date_format:
            txn_date = datetime.strptime(raw_date, date_format).date()
        elif isinstance(raw_date, str):
            txn_date = pd.to_datetime(raw_date).date()
        else:
            txn_date = pd.to_datetime(raw_date).date()

        description = str(row.get(desc_col, "") or "")
        party_name = str(row.get(party_col, "") or "") if party_col else None

        txn = BankTransaction(
            txn_date=txn_date,
            amount=amount,
            description=description,
            reference=str(row.get(ref_col, "") or "") if ref_col else None,
            party_name=party_name,
            raw_row=row.to_dict(),
        )
        transactions.append(process_transaction(txn))

    return transactions
