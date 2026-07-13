"""
GuardianRecon — Reconciliation Engine
=========================================
محرك التسوية البنكية الآلية الكاملة.
يطبق منهجية finance:reconciliation:
  1) مطابقة تامة (Exact Match): نفس المبلغ + نفس التاريخ
  2) مطابقة تقريبية (Fuzzy Match): نفس المبلغ ± نافذة أيام، أو تشابه وصف
  3) تصنيف الفروقات: Timing Difference / Adjustment Required / Investigation
  4) تحليل تقادم (Aging) للعناصر غير المطابقة
"""

from __future__ import annotations
from datetime import date
from difflib import SequenceMatcher
from typing import List, Tuple

from .models import (
    BankTransaction, GLTransaction, ReconciliationItem,
    ReconCategory, ItemStatus,
)

AMOUNT_TOLERANCE = 0.01     # فرق مسموح به بالريال (أخطاء تقريب)
DATE_WINDOW_DAYS = 5        # نافذة الأيام للمطابقة التقريبية (شيكات معلقة عادة تتأخر)
DESC_SIMILARITY_THRESHOLD = 0.55


def _amounts_match(a: float, b: float, tolerance: float = AMOUNT_TOLERANCE) -> bool:
    return abs(a - b) <= tolerance


def _description_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class ReconciliationEngine:
    """المحرك الرئيسي: يأخذ قوائم معاملات بنكية وقيود GL وينتج تقرير تسوية كامل."""

    def __init__(
        self,
        bank_txns: List[BankTransaction],
        gl_txns: List[GLTransaction],
        as_of: date = None,
        date_window_days: int = DATE_WINDOW_DAYS,
        amount_tolerance: float = AMOUNT_TOLERANCE,
    ):
        self.bank_txns = list(bank_txns)
        self.gl_txns = list(gl_txns)
        self.as_of = as_of or date.today()
        self.date_window_days = date_window_days
        self.amount_tolerance = amount_tolerance
        self.items: List[ReconciliationItem] = []

    # -----------------------------------------------------------------
    # المرحلة 1: المطابقة التامة
    # -----------------------------------------------------------------
    def _exact_match(self) -> Tuple[List[ReconciliationItem], List[BankTransaction], List[GLTransaction]]:
        matched_items = []
        unmatched_bank = list(self.bank_txns)
        unmatched_gl = list(self.gl_txns)

        for bank_txn in list(unmatched_bank):
            for gl_txn in list(unmatched_gl):
                same_amount = _amounts_match(bank_txn.amount, gl_txn.amount, self.amount_tolerance)
                same_date = bank_txn.txn_date == gl_txn.txn_date
                if same_amount and same_date:
                    item = ReconciliationItem(
                        bank_txn=bank_txn,
                        gl_txn=gl_txn,
                        category=ReconCategory.MATCHED,
                        difference=round(bank_txn.amount - gl_txn.amount, 2),
                        match_confidence=1.0,
                        note="مطابقة تامة: نفس المبلغ ونفس التاريخ",
                    )
                    matched_items.append(item)
                    unmatched_bank.remove(bank_txn)
                    unmatched_gl.remove(gl_txn)
                    break

        return matched_items, unmatched_bank, unmatched_gl

    # -----------------------------------------------------------------
    # المرحلة 2: المطابقة التقريبية (نافذة تاريخ + تشابه وصف)
    # -----------------------------------------------------------------
    def _fuzzy_match(
        self, unmatched_bank: List[BankTransaction], unmatched_gl: List[GLTransaction]
    ) -> Tuple[List[ReconciliationItem], List[BankTransaction], List[GLTransaction]]:
        matched_items = []
        remaining_bank = list(unmatched_bank)
        remaining_gl = list(unmatched_gl)

        for bank_txn in list(remaining_bank):
            best_candidate = None
            best_score = 0.0

            for gl_txn in remaining_gl:
                if not _amounts_match(bank_txn.amount, gl_txn.amount, self.amount_tolerance):
                    continue
                day_diff = abs((bank_txn.txn_date - gl_txn.txn_date).days)
                if day_diff > self.date_window_days:
                    continue

                desc_sim = _description_similarity(
                    bank_txn.description_en or bank_txn.description,
                    gl_txn.description,
                )
                # نقاط الثقة: كلما قلّت الأيام وزاد تشابه الوصف زادت الثقة
                date_score = 1 - (day_diff / max(self.date_window_days, 1))
                score = 0.6 * date_score + 0.4 * desc_sim

                if score > best_score:
                    best_score = score
                    best_candidate = gl_txn

            if best_candidate is not None and best_score >= 0.35:
                day_diff = abs((bank_txn.txn_date - best_candidate.txn_date).days)
                category = (
                    ReconCategory.TIMING_DIFFERENCE
                    if day_diff > 0
                    else ReconCategory.ADJUSTMENT_REQUIRED
                )
                item = ReconciliationItem(
                    bank_txn=bank_txn,
                    gl_txn=best_candidate,
                    category=category,
                    difference=round(bank_txn.amount - best_candidate.amount, 2),
                    match_confidence=round(best_score, 2),
                    note=f"مطابقة تقريبية: فرق {day_diff} يوم، تشابه وصف {best_score:.0%}",
                )
                matched_items.append(item)
                remaining_bank.remove(bank_txn)
                remaining_gl.remove(best_candidate)

        return matched_items, remaining_bank, remaining_gl

    # -----------------------------------------------------------------
    # المرحلة 3: العناصر المتبقية بدون تطابق → تحتاج تحقيق
    # -----------------------------------------------------------------
    def _unmatched_to_items(
        self, unmatched_bank: List[BankTransaction], unmatched_gl: List[GLTransaction]
    ) -> List[ReconciliationItem]:
        items = []
        for bank_txn in unmatched_bank:
            items.append(ReconciliationItem(
                bank_txn=bank_txn,
                gl_txn=None,
                category=ReconCategory.REQUIRES_INVESTIGATION,
                difference=bank_txn.amount,
                note="معاملة بنكية بدون قيد مقابل في دفتر الأستاذ",
            ))
        for gl_txn in unmatched_gl:
            items.append(ReconciliationItem(
                bank_txn=None,
                gl_txn=gl_txn,
                category=ReconCategory.REQUIRES_INVESTIGATION,
                difference=-gl_txn.amount,
                note="قيد في دفتر الأستاذ بدون معاملة بنكية مقابلة",
            ))
        return items

    # -----------------------------------------------------------------
    # حساب التقادم لكل عنصر غير مطابق تماماً
    # -----------------------------------------------------------------
    def _apply_aging(self, items: List[ReconciliationItem]) -> None:
        for item in items:
            if item.category == ReconCategory.MATCHED:
                continue
            ref_date = None
            if item.bank_txn:
                ref_date = item.bank_txn.txn_date
            elif item.gl_txn:
                ref_date = item.gl_txn.txn_date
            if ref_date:
                item.age_days = (self.as_of - ref_date).days
                item.compute_status()

    # -----------------------------------------------------------------
    # التشغيل الكامل
    # -----------------------------------------------------------------
    def run(self) -> List[ReconciliationItem]:
        exact_items, rem_bank, rem_gl = self._exact_match()
        fuzzy_items, rem_bank, rem_gl = self._fuzzy_match(rem_bank, rem_gl)
        unmatched_items = self._unmatched_to_items(rem_bank, rem_gl)

        self.items = exact_items + fuzzy_items + unmatched_items
        self._apply_aging(self.items)
        return self.items

    # -----------------------------------------------------------------
    # ملخص التسوية بصيغة قابلة للطباعة/التصدير
    # -----------------------------------------------------------------
    def summary(self) -> dict:
        bank_balance = sum(t.amount for t in self.bank_txns)
        gl_balance = sum(t.amount for t in self.gl_txns)

        outstanding = [i for i in self.items if i.category != ReconCategory.MATCHED]
        by_category = {}
        for cat in ReconCategory:
            by_category[cat.value] = [i for i in self.items if i.category == cat]

        escalations = [
            i for i in outstanding
            if abs(i.difference) > 10000 or i.status in (ItemStatus.OVERDUE, ItemStatus.STALE)
        ]

        return {
            "as_of": self.as_of,
            "bank_balance": round(bank_balance, 2),
            "gl_balance": round(gl_balance, 2),
            "raw_difference": round(bank_balance - gl_balance, 2),
            "total_items": len(self.items),
            "matched_count": len(by_category[ReconCategory.MATCHED.value]),
            "timing_diff_count": len(by_category[ReconCategory.TIMING_DIFFERENCE.value]),
            "adjustment_count": len(by_category[ReconCategory.ADJUSTMENT_REQUIRED.value]),
            "investigation_count": len(by_category[ReconCategory.REQUIRES_INVESTIGATION.value]),
            "outstanding_total": round(sum(i.difference for i in outstanding), 2),
            "escalations": escalations,
            "items_by_category": by_category,
        }
