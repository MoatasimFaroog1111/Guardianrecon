"""
GuardianRecon — Odoo Connector
==================================
سحب قيود دفتر الأستاذ (حساب البنك) من Odoo عبر odoorpc،
وتحويلها إلى GLTransaction جاهزة لمحرك التسوية.

الاستخدام:
    connector = OdooConnector(host="...", db="...", user="...", password="...")
    connector.connect()
    gl_txns = connector.fetch_gl_transactions(account_code="1010", date_from="2026-06-01", date_to="2026-06-30")
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from ..engine.models import GLTransaction

try:
    import odoorpc
except ImportError:
    odoorpc = None  # يسمح باستيراد الملف حتى لو المكتبة غير مثبتة بعد


class OdooConnector:
    def __init__(self, host: str, db: str, user: str, password: str,
                 port: int = 443, protocol: str = "jsonrpc+ssl"):
        if odoorpc is None:
            raise ImportError("ثبّت المكتبة أولاً: pip install odoorpc")
        self.host = host
        self.db = db
        self.user = user
        self.password = password
        self.port = port
        self.protocol = protocol
        self.odoo: Optional["odoorpc.ODOO"] = None

    def connect(self):
        self.odoo = odoorpc.ODOO(self.host, protocol=self.protocol, port=self.port)
        self.odoo.login(self.db, self.user, self.password)
        return self.odoo

    def fetch_gl_transactions(
        self, account_code: str, date_from: str, date_to: str
    ) -> List[GLTransaction]:
        """يسحب قيود account.move.line لحساب بنكي محدد ضمن فترة زمنية."""
        if self.odoo is None:
            self.connect()

        AccountMoveLine = self.odoo.env["account.move.line"]

        domain = [
            ("account_id.code", "=", account_code),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("parent_state", "=", "posted"),  # قيود مرحّلة فقط
        ]
        fields = ["id", "date", "debit", "credit", "name", "partner_id",
                  "account_id", "reconciled", "move_id"]

        ids = AccountMoveLine.search(domain)
        records = AccountMoveLine.read(ids, fields)

        gl_txns = []
        for rec in records:
            amount = (rec.get("debit") or 0.0) - (rec.get("credit") or 0.0)
            txn_date = datetime.strptime(rec["date"], "%Y-%m-%d").date()
            partner = rec.get("partner_id")
            gl_txns.append(GLTransaction(
                move_id=rec["id"],
                txn_date=txn_date,
                amount=amount,
                description=rec.get("name") or "",
                partner_name=partner[1] if partner else None,
                account_code=account_code,
                reconciled=bool(rec.get("reconciled")),
                raw_row=rec,
            ))
        return gl_txns

    def post_adjustment_entry(
        self, journal_id: int, account_id: int, counterpart_account_id: int,
        amount: float, label: str, date_str: str
    ) -> int:
        """
        ينشئ قيد تسوية (Adjustment Required) في Odoo — مسودة (draft) دائماً،
        يحتاج موافقة يدوية قبل الترحيل (Human-in-the-loop).
        """
        AccountMove = self.odoo.env["account.move"]
        line_amount = abs(amount)
        is_debit_bank = amount > 0

        move_vals = {
            "journal_id": journal_id,
            "date": date_str,
            "ref": f"GuardianRecon Auto-Adjustment: {label}",
            "line_ids": [
                (0, 0, {
                    "account_id": account_id,
                    "name": label,
                    "debit": line_amount if is_debit_bank else 0.0,
                    "credit": 0.0 if is_debit_bank else line_amount,
                }),
                (0, 0, {
                    "account_id": counterpart_account_id,
                    "name": label,
                    "debit": 0.0 if is_debit_bank else line_amount,
                    "credit": line_amount if is_debit_bank else 0.0,
                }),
            ],
        }
        move_id = AccountMove.create(move_vals)
        # يبقى في حالة draft عمداً — لا يُرحَّل تلقائياً
        return move_id
