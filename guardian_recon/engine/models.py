"""
GuardianRecon — Core Data Models
==================================
نماذج البيانات الأساسية: معاملة بنكية، قيد دفتر أستاذ، عنصر تسوية.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional
import uuid


class PartyType(str, Enum):
    """تصنيف الطرف المقابل في المعاملة"""
    PETTY_CASH = "Petty Cash"
    SUPPLIER = "Supplier"
    FEE = "Fee"
    GOVERNMENT = "Government"
    PAYROLL = "Payroll"
    INTERNAL_TRANSFER = "Internal Transfer"
    UNKNOWN = "Unknown"


class ReconCategory(str, Enum):
    """تصنيف عنصر التسوية حسب منهجية finance:reconciliation"""
    MATCHED = "Matched"                          # مطابق تماماً
    TIMING_DIFFERENCE = "Timing Difference"       # فرق توقيت (شيكات معلقة / إيداعات بالطريق)
    ADJUSTMENT_REQUIRED = "Adjustment Required"   # يحتاج قيد تسوية (رسوم/فوائد غير مسجلة)
    REQUIRES_INVESTIGATION = "Requires Investigation"  # يحتاج تحقيق


class ItemStatus(str, Enum):
    CURRENT = "Current"          # 0-30 يوم
    AGING = "Aging"              # 31-60 يوم
    OVERDUE = "Overdue"          # 61-90 يوم
    STALE = "Stale"              # 90+ يوم


@dataclass
class BankTransaction:
    """معاملة من كشف الحساب البنكي"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    txn_date: date = None
    amount: float = 0.0                 # موجب = إيداع، سالب = سحب
    description: str = ""
    description_en: str = ""            # الترجمة الإنجليزية النظيفة
    reference: Optional[str] = None
    party_name: Optional[str] = None
    party_type: PartyType = PartyType.UNKNOWN
    raw_row: dict = field(default_factory=dict)

    @property
    def is_debit(self) -> bool:
        return self.amount < 0

    @property
    def is_credit(self) -> bool:
        return self.amount > 0


@dataclass
class GLTransaction:
    """قيد من دفتر الأستاذ (حساب البنك في Odoo)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    move_id: Optional[int] = None       # account.move.line id في Odoo
    txn_date: date = None
    amount: float = 0.0                 # موجب = مدين (دخول نقد)، سالب = دائن
    description: str = ""
    partner_name: Optional[str] = None
    account_code: Optional[str] = None
    reconciled: bool = False
    raw_row: dict = field(default_factory=dict)


@dataclass
class ReconciliationItem:
    """عنصر تسوية واحد — ناتج مطابقة معاملة بنكية مع قيد GL (أو عدم وجود تطابق)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    bank_txn: Optional[BankTransaction] = None
    gl_txn: Optional[GLTransaction] = None
    category: ReconCategory = ReconCategory.REQUIRES_INVESTIGATION
    difference: float = 0.0
    age_days: int = 0
    status: ItemStatus = ItemStatus.CURRENT
    note: str = ""
    match_confidence: float = 0.0       # 0-1، مدى الثقة بالمطابقة (للمطابقة التقريبية)

    def compute_status(self):
        if self.age_days <= 30:
            self.status = ItemStatus.CURRENT
        elif self.age_days <= 60:
            self.status = ItemStatus.AGING
        elif self.age_days <= 90:
            self.status = ItemStatus.OVERDUE
        else:
            self.status = ItemStatus.STALE
        return self.status
