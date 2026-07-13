"""
GuardianRecon — Configuration Loader
========================================
يقرأ كل الأسرار/الإعدادات من متغيرات البيئة (Environment Variables) —
نفس الأسماء تُستخدم محلياً في ملف .env أو كـ GitHub Secrets في الإنتاج.

لا يوجد أي بيانات اتصال مكتوبة داخل الكود مباشرة — هذا مقصود؛ الكود نفسه
آمن للرفع على GitHub علناً حتى لو المستودع عام، لأن الأسرار الفعلية
تعيش فقط في GitHub Secrets أو ملف .env المحلي (المستثنى من git عبر
.gitignore ولا يُرفع أبداً).

الاستخدام:
    from guardian_recon.config import get_odoo_config
    cfg = get_odoo_config()   # يرمي خطأ واضح لو أي متغير ناقص
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()  # يقرأ ملف .env المحلي إذا موجود (لا يؤثر شي في GitHub Actions)
except ImportError:
    pass


REQUIRED_ODOO_VARS = ["ODOO_HOST", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD"]


@dataclass
class OdooConfig:
    host: str
    db: str
    user: str
    password: str
    port: int = 443
    protocol: str = "jsonrpc+ssl"


def get_odoo_config() -> OdooConfig:
    """
    يقرأ إعدادات الاتصال بأودو من متغيرات البيئة:
        ODOO_HOST, ODOO_PORT, ODOO_PROTOCOL, ODOO_DB, ODOO_USER, ODOO_PASSWORD

    يرمي ValueError برسالة واضحة تحدد بالضبط أي متغير ناقص، بدل خطأ غامض لاحقاً.
    """
    missing = [v for v in REQUIRED_ODOO_VARS if not os.environ.get(v)]
    if missing:
        raise ValueError(
            "متغيرات بيئة ناقصة للاتصال بأودو: " + ", ".join(missing) +
            "\nضِفها إما بملف .env محلياً، أو كـ GitHub Secrets بنفس الأسماء بالضبط."
        )

    return OdooConfig(
        host=os.environ["ODOO_HOST"],
        db=os.environ["ODOO_DB"],
        user=os.environ["ODOO_USER"],
        password=os.environ["ODOO_PASSWORD"],
        port=int(os.environ.get("ODOO_PORT", 443)),
        protocol=os.environ.get("ODOO_PROTOCOL", "jsonrpc+ssl"),
    )


def get_database_url() -> str:
    """رابط قاعدة بيانات GuardianRecon نفسها (SQLite افتراضياً، PostgreSQL لاحقاً)."""
    return os.environ.get("GUARDIAN_DB_URL", "sqlite:///./guardian_recon.db")
