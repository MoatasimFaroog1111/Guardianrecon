"""
GuardianRecon — Party Classifier & Description Cleaner
=========================================================
تصنيف الأطراف (عهدة/مورد) وتنظيف وصف المعاملات — منطق مطابق لـ
clean-bank-statement-ar skill لكن كـ pipeline بايثون قابل لإعادة الاستخدام
داخل محرك التسوية والاستيراد الآلي.
"""

import re
from .models import BankTransaction, PartyType

# ---------------------------------------------------------------------------
# قاموس الترجمة الأساسي (قابل للتوسعة من config/term_mappings.json)
# ---------------------------------------------------------------------------
TERM_MAP = {
    "تحويل السريع": "INSTANT PAYMENT TRANSFER",
    "عمولة": "Commission",
    "الضريبة المضافة": "VAT",
    "نسبة ضريبة القيمة المضافة": "VAT Rate",
    "عن طريق النظام الآلي": "Via Automated System",
    "خدمات الشركات اون لاين": "Online Corporate Services",
    "التأمينات": "GOSI (Social Insurance)",
    "بلدي": "Balady (Municipality)",
    "وزارة العمل": "MOL (Ministry of Labor)",
    "قوى": "Qiwa Platform",
    "خدمات المقيمين": "Residents Services",
    "شركة الاتصالات": "Saudi Telecom Company (STC)",
    "تحويل داخل المملكة": "Local Transfer",
    "تحويل دولي": "International Transfer",
    "عهدة": "Petty Cash / Custody",
    "سداد فاتورة لمرة واحدة": "One-time bill payment",
    "الخدمات الحكومية": "Government Services",
}

# كلمات مفتاحية تدل على شركة/منشأة
COMPANY_KEYWORDS = [
    "company", "co", "establishment", "est", "llc", "fze", "trading",
    "industries", "industrial", "services", "solutions", "group",
    "holding", "center", "centre", "factory", "bank", "insurance",
    "international", "شركة", "مؤسسة", "منشأة",
]

# أنماط لا يجب تصنيفها كطرف (رسوم/حكومي/رواتب/تحويل داخلي)
NON_PARTY_PATTERNS = [
    r"\bfee(s)?\b", r"\bcharges?\b", r"\bvat\b",
    r"\bgosi\b", r"\bbalady\b", r"\bmol\b", r"\bqiwa\b", r"\bstc\b",
    r"\bpayroll\b", r"\bsalary\b", r"\binternal transfer\b",
]

# ضجيج تقني يُزال من الوصف (REF, IBAN, SWIFT, تواريخ...)
NOISE_PATTERNS = [
    r"REF[\s:#]*\S+",
    r"\bSA\d{20,}\b",                      # IBAN سعودي
    r"\b[A-Z]{4}SA[A-Z0-9]{2,4}\b",         # SWIFT/BIC
    r"\d{2}/\d{2}[-\s]\d{2}:\d{2}:\d{2}",   # DATE-TIME
    r"VALUE\s*DT\S*", r"SENT\s*DATE\S*",
    r"BILLER\s*ID\S*", r"SUB\s*\d+", r"ID#\s*\d+",
    r"EXCHANGE\s*RATE\S*", r"VIA\s*CORE\s*SYSTEM", r"VIA\s*ECORP\s*CHANNEL",
    r"\bP0*\d{6,}\b",                       # أرقام الملفات
]


def clean_description(raw: str) -> str:
    """يزيل الضجيج التقني ويبقي فقط المعنى التجاري الأساسي."""
    text = raw
    for term_ar, term_en in TERM_MAP.items():
        text = text.replace(term_ar, term_en)
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" -,")
    return text


def is_non_party_row(text: str) -> bool:
    """يتحقق إذا كان الصف رسوم/حكومي/رواتب/تحويل داخلي (لا يُصنَّف كطرف)."""
    lowered = text.lower()
    return any(re.search(p, lowered) for p in NON_PARTY_PATTERNS)


def looks_like_company(name: str) -> bool:
    lowered = name.lower()
    return any(kw in lowered for kw in COMPANY_KEYWORDS)


def classify_party(name: str, description: str) -> PartyType:
    """يصنف الطرف المقابل بناءً على الاسم ونوع المعاملة."""
    if not name:
        return PartyType.UNKNOWN
    if is_non_party_row(description):
        desc_lower = description.lower()
        if "gosi" in desc_lower or "balady" in desc_lower or "mol" in desc_lower or "qiwa" in desc_lower:
            return PartyType.GOVERNMENT
        if "payroll" in desc_lower or "salary" in desc_lower:
            return PartyType.PAYROLL
        if "fee" in desc_lower or "charge" in desc_lower:
            return PartyType.FEE
        if "internal transfer" in desc_lower:
            return PartyType.INTERNAL_TRANSFER
        return PartyType.UNKNOWN

    if looks_like_company(name):
        return PartyType.SUPPLIER

    # اسم شخص (كلمتين لأربع كلمات، بدون كلمات شركات)
    word_count = len(name.strip().split())
    if 1 <= word_count <= 4:
        return PartyType.PETTY_CASH

    return PartyType.UNKNOWN


def process_transaction(txn: BankTransaction) -> BankTransaction:
    """يطبق التنظيف والتصنيف الكامل على معاملة بنكية واحدة."""
    txn.description_en = clean_description(txn.description)
    if txn.party_name:
        txn.party_type = classify_party(txn.party_name, txn.description_en)
    return txn
