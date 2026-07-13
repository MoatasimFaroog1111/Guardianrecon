"""
GuardianRecon — Automated Tests
===================================
اختبارات pytest لمحرك التسوية، تشتغل آلياً عبر GitHub Actions
عند كل push (مرحلة 1.6 من خارطة الطريق).

تشغيل محلياً:
    cd /home/claude   (أو جذر المشروع اللي فوق guardian_recon)
    pytest guardian_recon/tests/ -v
"""

from datetime import date
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from guardian_recon.demo import build_sample_data
from guardian_recon.engine.reconciler import ReconciliationEngine
from guardian_recon.engine.models import ReconCategory, BankTransaction, GLTransaction, PartyType
from guardian_recon.engine.classifier import classify_party, clean_description


def _run_demo_engine():
    bank_txns, gl_txns = build_sample_data()
    engine = ReconciliationEngine(bank_txns, gl_txns, as_of=date(2026, 6, 30))
    engine.run()
    return engine


# ---------------------------------------------------------------------
# اختبارات محرك التسوية على بيانات الديمو المعروفة
# ---------------------------------------------------------------------
def test_demo_reconciliation_item_count():
    engine = _run_demo_engine()
    assert len(engine.items) == 5


def test_demo_exact_matches():
    engine = _run_demo_engine()
    matched = [i for i in engine.items if i.category == ReconCategory.MATCHED]
    assert len(matched) == 2


def test_demo_timing_difference_detected():
    engine = _run_demo_engine()
    timing = [i for i in engine.items if i.category == ReconCategory.TIMING_DIFFERENCE]
    assert len(timing) == 1
    assert timing[0].difference == 0.0  # نفس المبلغ بالضبط، بس فرق تاريخ


def test_demo_investigation_items():
    engine = _run_demo_engine()
    investigation = [i for i in engine.items if i.category == ReconCategory.REQUIRES_INVESTIGATION]
    assert len(investigation) == 2
    descriptions = {(i.bank_txn.description if i.bank_txn else "") for i in investigation}
    assert any("Fee" in d for d in descriptions)


def test_summary_balances_correct():
    engine = _run_demo_engine()
    summary = engine.summary()
    expected_bank_balance = sum(t.amount for t in engine.bank_txns)
    assert summary["bank_balance"] == round(expected_bank_balance, 2)


# ---------------------------------------------------------------------
# اختبارات المطابقة الأساسية (Exact / Fuzzy) بحالات مصطنعة بسيطة
# ---------------------------------------------------------------------
def test_exact_match_same_amount_same_date():
    bank = [BankTransaction(txn_date=date(2026, 1, 1), amount=-500, description="Test Payment")]
    gl = [GLTransaction(txn_date=date(2026, 1, 1), amount=-500, description="Test Payment")]
    engine = ReconciliationEngine(bank, gl, as_of=date(2026, 1, 5))
    engine.run()
    assert engine.items[0].category == ReconCategory.MATCHED
    assert engine.items[0].match_confidence == 1.0


def test_no_match_beyond_date_window():
    bank = [BankTransaction(txn_date=date(2026, 1, 1), amount=-500, description="Test Payment")]
    gl = [GLTransaction(txn_date=date(2026, 2, 1), amount=-500, description="Unrelated Entry")]
    engine = ReconciliationEngine(bank, gl, as_of=date(2026, 2, 5), date_window_days=5)
    engine.run()
    # الفرق شهر كامل، أكبر من نافذة الأيام → ما لازم يتطابق
    categories = {i.category for i in engine.items}
    assert ReconCategory.MATCHED not in categories


def test_aging_status_buckets():
    bank = [BankTransaction(txn_date=date(2026, 1, 1), amount=100, description="Old unmatched item")]
    engine = ReconciliationEngine(bank, [], as_of=date(2026, 5, 1))  # ~120 يوم
    engine.run()
    assert engine.items[0].age_days > 90
    assert engine.items[0].status.value == "Stale"


# ---------------------------------------------------------------------
# اختبارات مصنف الأطراف
# ---------------------------------------------------------------------
def test_classify_company_as_supplier():
    result = classify_party("ABC Trading Company", "Outgoing Payment")
    assert result == PartyType.SUPPLIER


def test_classify_person_name_as_petty_cash():
    result = classify_party("Ahmed Al-Otaibi", "Outgoing Payment - Personal/Other")
    assert result == PartyType.PETTY_CASH


def test_classify_gosi_as_government():
    result = classify_party("GOSI", "Bill Payment - GOSI (Social Insurance)")
    assert result == PartyType.GOVERNMENT


def test_clean_description_removes_reference_numbers():
    raw = "Outgoing Instant Payment REF 88213 to ABC Trading Co"
    cleaned = clean_description(raw)
    assert "REF" not in cleaned
    assert "88213" not in cleaned
