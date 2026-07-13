"""
GuardianRecon — Demo Run
============================
يشغّل المحرك الكامل ببيانات تجريبية (بدون الحاجة لاتصال Odoo حقيقي)
عشان نتأكد المنطق سليم قبل الربط الفعلي.

تشغيل: python -m guardian_recon.demo
"""

from datetime import date
from .engine.models import BankTransaction, GLTransaction
from .engine.classifier import process_transaction
from .engine.reconciler import ReconciliationEngine
from .reports.excel_report import export_reconciliation_report


def build_sample_data():
    bank_txns = [
        # 1) مطابقة تامة
        BankTransaction(txn_date=date(2026, 6, 5), amount=-15000, description="Outgoing Instant Payment to ABC Trading Co REF 88213"),
        # 2) فرق توقيت — شيك صادر يتأخر 3 أيام عن البنك
        BankTransaction(txn_date=date(2026, 6, 10), amount=-8200, description="Cheque Payment to Al Faisal Establishment REF 99021"),
        # 3) رسوم بنكية غير مسجلة في GL (Adjustment Required)
        BankTransaction(txn_date=date(2026, 6, 12), amount=-45, description="Local Transfer Fees"),
        # 4) إيداع بدون أي أثر في GL (يحتاج تحقيق)
        BankTransaction(txn_date=date(2026, 6, 15), amount=22000, description="Incoming Transfer from Client X"),
        # 5) عهدة موظف (Petty Cash) مطابقة تماماً
        BankTransaction(txn_date=date(2026, 6, 18), amount=-3000, description="Outgoing Instant Payment to Ahmed Al-Otaibi - Personal/Other"),
    ]
    for t in bank_txns:
        process_transaction(t)
        if t.description_en and " to " in t.description_en:
            t.party_name = t.description_en.split(" to ")[-1].split(" REF")[0].split(" - ")[0]
            process_transaction(t)

    gl_txns = [
        GLTransaction(move_id=1001, txn_date=date(2026, 6, 5), amount=-15000, description="ABC Trading Co - Invoice #4521"),
        GLTransaction(move_id=1002, txn_date=date(2026, 6, 7), amount=-8200, description="Al Faisal Establishment - Cheque #302"),  # توقيت مختلف
        GLTransaction(move_id=1003, txn_date=date(2026, 6, 18), amount=-3000, description="Ahmed Al-Otaibi - Petty Cash Advance"),
        # ملاحظة: لا يوجد قيد لرسوم التحويل ولا للإيداع الوارد → يظهران كعناصر تحتاج معالجة
    ]

    return bank_txns, gl_txns


def main():
    bank_txns, gl_txns = build_sample_data()

    engine = ReconciliationEngine(
        bank_txns=bank_txns,
        gl_txns=gl_txns,
        as_of=date(2026, 6, 30),
    )
    engine.run()
    summary = engine.summary()

    print("=" * 60)
    print("ملخص التسوية البنكية — GuardianRecon")
    print("=" * 60)
    print(f"رصيد البنك:          {summary['bank_balance']:,.2f}")
    print(f"رصيد دفتر الأستاذ:    {summary['gl_balance']:,.2f}")
    print(f"الفرق الخام:          {summary['raw_difference']:,.2f}")
    print("-" * 60)
    print(f"إجمالي العناصر:              {summary['total_items']}")
    print(f"  مطابقة تماماً:              {summary['matched_count']}")
    print(f"  فروقات توقيت:               {summary['timing_diff_count']}")
    print(f"  تحتاج قيد تسوية:            {summary['adjustment_count']}")
    print(f"  تحتاج تحقيق:                {summary['investigation_count']}")
    print("-" * 60)

    for item in engine.items:
        ref = item.bank_txn or item.gl_txn
        desc = getattr(ref, "description_en", None) or ref.description
        party_info = f" [{item.bank_txn.party_type.value}]" if item.bank_txn and item.bank_txn.party_type else ""
        print(f"[{item.category.value:22s}] {desc[:45]:45s} | فرق: {item.difference:>10,.2f} | ثقة: {item.match_confidence:.0%}{party_info}")

    output_path = "/home/claude/guardian_recon/demo_reconciliation_report.xlsx"
    export_reconciliation_report(summary, output_path)
    print("-" * 60)
    print(f"✅ تم إنشاء التقرير: {output_path}")


if __name__ == "__main__":
    main()
