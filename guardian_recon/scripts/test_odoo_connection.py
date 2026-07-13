"""
GuardianRecon — Odoo Connection Test Script
================================================
يختبر الاتصال بأودو باستخدام بيانات من متغيرات البيئة (GitHub Secrets)
ويطبع ملخص آمن فقط — لا يطبع أي بيانة حساسة (host/user/password) إطلاقاً.

يُستخدم عبر GitHub Actions (workflow_dispatch) — الأسرار تبقى داخل
بيئة الـ runner ولا تظهر بالمحادثة مع Claude أبداً.

خروج بكود 0 = نجاح، كود 1 = فشل (عشان GitHub Actions يعكس الحالة صح).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from guardian_recon.config import get_odoo_config
from guardian_recon.connectors.odoo_connector import OdooConnector


def mask(value: str, keep: int = 2) -> str:
    """يخفي القيمة الحساسة، يبقي بس أول/آخر حرفين للتأكد إنها مو فاضية."""
    if not value or len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


def main():
    print("=" * 60)
    print("GuardianRecon — اختبار الاتصال بـ Odoo")
    print("=" * 60)

    # 1) التحقق من وجود كل المتغيرات (بدون طباعة قيمها)
    try:
        cfg = get_odoo_config()
    except ValueError as e:
        print(f"❌ فشل: {e}")
        sys.exit(1)

    print(f"✅ الإعدادات موجودة: host={mask(cfg.host)}, db={mask(cfg.db)}, "
          f"user={mask(cfg.user)}, port={cfg.port}, protocol={cfg.protocol}")

    # 2) محاولة الاتصال الفعلي وتسجيل الدخول
    try:
        connector = OdooConnector.from_env()
        connector.connect()
        print("✅ تم الاتصال وتسجيل الدخول بنجاح")
    except Exception as e:
        print(f"❌ فشل الاتصال/تسجيل الدخول: {type(e).__name__}: {e}")
        sys.exit(1)

    # 3) اختبار قراءة فعلية بسيطة (بدون كتابة أي شي) — حساب مستخدمين مثلاً
    try:
        Users = connector.odoo.env["res.users"]
        count = Users.search_count([])
        print(f"✅ اختبار قراءة ناجح: {count} مستخدم موجود في قاعدة البيانات")
    except Exception as e:
        print(f"⚠️ الاتصال نجح لكن فشل اختبار القراءة: {type(e).__name__}: {e}")
        sys.exit(1)

    # 4) اختبار اختياري: قراءة حساب بنكي محدد لو معطى كمتغير بيئة
    account_code = os.environ.get("TEST_ACCOUNT_CODE")
    if account_code:
        try:
            gl_txns = connector.fetch_gl_transactions(
                account_code=account_code,
                date_from=os.environ.get("TEST_DATE_FROM", "2026-01-01"),
                date_to=os.environ.get("TEST_DATE_TO", "2026-12-31"),
            )
            print(f"✅ قراءة قيود الحساب '{mask(account_code)}': {len(gl_txns)} قيد")
        except Exception as e:
            print(f"⚠️ فشل قراءة قيود الحساب: {type(e).__name__}: {e}")
            sys.exit(1)
    else:
        print("ℹ️  تم تخطي اختبار قراءة حساب محدد (TEST_ACCOUNT_CODE غير معطى)")

    print("=" * 60)
    print("🎉 كل الاختبارات نجحت — الاتصال بـ Odoo جاهز للاستخدام الفعلي")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
