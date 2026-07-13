"""
GuardianRecon Dashboard — State & Approval Manager (DB-backed)
===================================================================
نفس الواجهة البرمجية السابقة (state.py الأصلي) لكن بدل التخزين
بالذاكرة، كل شي يُكتب فوراً بقاعدة البيانات — يعني لو السيرفر
انطفى أو انعاد تشغيله، القرارات والعناصر ما تضيع.

مرحلة 1.1 من خارطة الطريق.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import uuid
import logging

from .database import (
    init_db, get_session, ReconciliationRunORM, ReconciliationItemORM, ActivityLogORM
)

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from guardian_recon.engine.models import ReconciliationItem, ReconCategory
from guardian_recon.engine.reconciler import ReconciliationEngine

logger = logging.getLogger("guardian_recon.dashboard")


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_CLEARED = "auto_cleared"


class DashboardState:
    """
    واجهة مطابقة لواجهة النسخة القديمة (in-memory) عشان main.py ما يحتاج
    يتغير كثير — لكن كل عملية هنا تُكتب لقاعدة البيانات فوراً.
    """

    def __init__(self):
        init_db()

    # -----------------------------------------------------------------
    def load_from_engine(self, engine: ReconciliationEngine, source: str = "demo") -> str:
        """يحفظ نتيجة تشغيل محرك التسوية كـ Run جديد في قاعدة البيانات."""
        session = get_session()
        try:
            run_id = str(uuid.uuid4())[:8]
            summary = engine.summary()

            run = ReconciliationRunORM(
                id=run_id,
                as_of=engine.as_of,
                bank_balance=summary["bank_balance"],
                gl_balance=summary["gl_balance"],
                raw_difference=summary["raw_difference"],
                source=source,
            )
            session.add(run)

            for item in engine.items:
                status = (
                    ApprovalStatus.AUTO_CLEARED.value
                    if item.category == ReconCategory.MATCHED
                    else ApprovalStatus.PENDING.value
                )
                ref_txn = item.bank_txn or item.gl_txn
                desc = (
                    (item.bank_txn.description_en if item.bank_txn else None)
                    or (item.gl_txn.description if item.gl_txn else "")
                )
                party_type = (
                    item.bank_txn.party_type.value
                    if item.bank_txn and item.bank_txn.party_type else None
                )
                row = ReconciliationItemORM(
                    id=item.id,
                    run_id=run_id,
                    category=item.category.value,
                    txn_date=ref_txn.txn_date if ref_txn else None,
                    description=desc,
                    party_type=party_type,
                    amount=ref_txn.amount if ref_txn else 0,
                    difference=item.difference,
                    status=item.status.value,
                    age_days=item.age_days,
                    match_confidence=item.match_confidence,
                    note=item.note,
                    approval_status=status,
                )
                session.add(row)

            session.commit()
            self._log(session, "system", "تشغيل تسوية جديدة", f"{len(engine.items)} عنصر (run: {run_id})")
            logger.info("New reconciliation run %s with %d items", run_id, len(engine.items))
            return run_id
        finally:
            session.close()

    # -----------------------------------------------------------------
    def decide(self, item_id: str, approve: bool, decided_by: str = "معتصم", comment: str = "") -> dict:
        session = get_session()
        try:
            row = session.query(ReconciliationItemORM).filter_by(id=item_id).first()
            if row is None:
                raise KeyError(f"عنصر غير موجود: {item_id}")

            row.approval_status = ApprovalStatus.APPROVED.value if approve else ApprovalStatus.REJECTED.value
            row.decided_by = decided_by
            row.decided_at = datetime.utcnow()
            row.comment = comment
            session.commit()

            action = "وافق على" if approve else "رفض"
            self._log(session, decided_by, f"{action} عنصر",
                       f"{(row.description or '')[:50]} ({row.difference:,.2f})")
            logger.info("Item %s decided=%s by %s", item_id, row.approval_status, decided_by)

            return {"item_id": item_id, "status": row.approval_status}
        finally:
            session.close()

    def bulk_decide(self, item_ids: List[str], approve: bool, decided_by: str = "معتصم") -> List[dict]:
        return [self.decide(i, approve, decided_by) for i in item_ids]

    # -----------------------------------------------------------------
    def mark_posted(self, item_id: str):
        session = get_session()
        try:
            row = session.query(ReconciliationItemORM).filter_by(id=item_id).first()
            if row:
                row.posted_to_odoo = True
                session.commit()
                self._log(session, "system", "تم الترحيل لأودو", item_id)
        finally:
            session.close()

    # -----------------------------------------------------------------
    def _log(self, session, actor: str, action: str, detail: str):
        entry = ActivityLogORM(actor=actor, action=action, detail=detail)
        session.add(entry)
        session.commit()

    # -----------------------------------------------------------------
    def get_items(self, category: Optional[str] = None, approval_status: Optional[str] = None) -> List[dict]:
        session = get_session()
        try:
            query = session.query(ReconciliationItemORM)
            if category:
                query = query.filter_by(category=category)
            if approval_status:
                query = query.filter_by(approval_status=approval_status)
            rows = query.all()

            items = [self._serialize_row(r) for r in rows]
            items.sort(key=lambda i: (
                0 if (abs(i["difference"]) > 10000 or i["status"] in ("Overdue", "Stale")) else 1,
                -abs(i["difference"])
            ))
            return items
        finally:
            session.close()

    @staticmethod
    def _serialize_row(row: ReconciliationItemORM) -> dict:
        return {
            "id": row.id,
            "category": row.category,
            "date": str(row.txn_date) if row.txn_date else None,
            "description": row.description,
            "party_type": row.party_type,
            "amount": row.amount,
            "difference": row.difference,
            "status": row.status,
            "age_days": row.age_days,
            "match_confidence": row.match_confidence,
            "note": row.note,
            "approval_status": row.approval_status,
            "decided_by": row.decided_by,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "posted_to_odoo": row.posted_to_odoo,
        }

    def get_activity(self, limit: int = 50) -> List[dict]:
        session = get_session()
        try:
            rows = (
                session.query(ActivityLogORM)
                .order_by(ActivityLogORM.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "actor": r.actor,
                    "action": r.action,
                    "detail": r.detail,
                }
                for r in rows
            ]
        finally:
            session.close()

    # -----------------------------------------------------------------
    def stats(self) -> dict:
        session = get_session()
        try:
            last_run = (
                session.query(ReconciliationRunORM)
                .order_by(ReconciliationRunORM.created_at.desc())
                .first()
            )
            all_items = session.query(ReconciliationItemORM).all()

            counts = {s.value: 0 for s in ApprovalStatus}
            for row in all_items:
                counts[row.approval_status] = counts.get(row.approval_status, 0) + 1

            escalations = [
                r for r in all_items
                if r.approval_status == ApprovalStatus.PENDING.value
                and (abs(r.difference) > 10000 or r.status in ("Overdue", "Stale"))
            ]

            return {
                "last_run_at": last_run.created_at.isoformat() if last_run else None,
                "total_items": len(all_items),
                "counts": counts,
                "pending_count": counts.get(ApprovalStatus.PENDING.value, 0),
                "escalation_count": len(escalations),
            }
        finally:
            session.close()


# نسخة عامة واحدة (Singleton) يستخدمها الـ API كله
state = DashboardState()
