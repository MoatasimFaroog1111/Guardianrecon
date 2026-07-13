"""
GuardianRecon Dashboard — State & Approval Manager
======================================================
يحتفظ بحالة عناصر التسوية الحالية + قرارات الموافقة/الرفض،
ويشكّل الجسر بين محرك guardian_recon.engine ولوحة المراقبة.

كل قرار (موافقة/رفض) يُسجَّل بختم زمني ولا يُرحَّل شيء في Odoo
تلقائياً إلا بعد موافقة صريحة — هذا هو مبدأ Human-in-the-loop.
"""

from __future__ import annotations
from datetime import datetime, date
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from guardian_recon.engine.models import ReconciliationItem, ReconCategory
from guardian_recon.engine.reconciler import ReconciliationEngine


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_CLEARED = "auto_cleared"   # Matched تلقائياً، لا يحتاج قرار بشري


@dataclass
class ApprovalRecord:
    item_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: str = ""
    posted_to_odoo: bool = False


class DashboardState:
    """حالة مركزية في الذاكرة (in-memory) — يمكن استبدالها بقاعدة بيانات لاحقاً."""

    def __init__(self):
        self.engine: Optional[ReconciliationEngine] = None
        self.items: Dict[str, ReconciliationItem] = {}
        self.approvals: Dict[str, ApprovalRecord] = {}
        self.last_run_at: Optional[datetime] = None
        self.activity_log: List[dict] = []

    # -----------------------------------------------------------------
    def load_from_engine(self, engine: ReconciliationEngine):
        """يستقبل نتيجة تشغيل محرك التسوية ويهيئ حالة الموافقات."""
        self.engine = engine
        self.items = {item.id: item for item in engine.items}
        self.approvals = {}
        for item in engine.items:
            status = (
                ApprovalStatus.AUTO_CLEARED
                if item.category == ReconCategory.MATCHED
                else ApprovalStatus.PENDING
            )
            self.approvals[item.id] = ApprovalRecord(item_id=item.id, status=status)
        self.last_run_at = datetime.now()
        self._log("system", "تشغيل تسوية جديدة", f"{len(engine.items)} عنصر")

    # -----------------------------------------------------------------
    def decide(self, item_id: str, approve: bool, decided_by: str = "معتصم", comment: str = "") -> ApprovalRecord:
        if item_id not in self.approvals:
            raise KeyError(f"عنصر غير موجود: {item_id}")

        record = self.approvals[item_id]
        record.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        record.decided_by = decided_by
        record.decided_at = datetime.now()
        record.comment = comment

        action = "وافق على" if approve else "رفض"
        item = self.items[item_id]
        desc = (item.bank_txn.description_en if item.bank_txn else None) or \
               (item.gl_txn.description if item.gl_txn else "عنصر")
        self._log(decided_by, f"{action} عنصر", f"{desc[:50]} ({item.difference:,.2f})")

        return record

    def bulk_decide(self, item_ids: List[str], approve: bool, decided_by: str = "معتصم") -> List[ApprovalRecord]:
        return [self.decide(i, approve, decided_by) for i in item_ids]

    # -----------------------------------------------------------------
    def mark_posted(self, item_id: str):
        if item_id in self.approvals:
            self.approvals[item_id].posted_to_odoo = True
            self._log("system", "تم الترحيل لأودو", item_id)

    # -----------------------------------------------------------------
    def _log(self, actor: str, action: str, detail: str):
        self.activity_log.insert(0, {
            "timestamp": datetime.now().isoformat(),
            "actor": actor,
            "action": action,
            "detail": detail,
        })
        self.activity_log = self.activity_log[:200]  # الاحتفاظ بآخر 200 حدث فقط

    # -----------------------------------------------------------------
    def stats(self) -> dict:
        counts = {s.value: 0 for s in ApprovalStatus}
        for record in self.approvals.values():
            counts[record.status.value] += 1

        pending_items = [
            self.items[iid] for iid, rec in self.approvals.items()
            if rec.status == ApprovalStatus.PENDING
        ]
        escalations = [
            i for i in pending_items
            if abs(i.difference) > 10000 or i.status.value in ("Overdue", "Stale")
        ]

        return {
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "total_items": len(self.items),
            "counts": counts,
            "pending_count": counts[ApprovalStatus.PENDING.value],
            "escalation_count": len(escalations),
        }


# نسخة عامة واحدة (Singleton) يستخدمها الـ API كله
state = DashboardState()
