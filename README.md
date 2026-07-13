# GuardianRecon
### محرك التسوية البنكية الآلية — الموديول الأول من منظومة Guardian المالية الموحدة

---

## الفكرة

نظام يقارن كشف الحساب البنكي بقيود دفتر الأستاذ في Odoo تلقائياً، يطابق المعاملات،
يصنّف الفروقات حسب منهجية `finance:reconciliation` المعتمدة (Timing / Adjustment /
Investigation)، يحسب التقادم (Aging)، ويصدّر تقرير Excel احترافي جاهز للمراجعة —
**بدون تدخل يدوي إلا عند الموافقة النهائية على قيود التسوية** (Human-in-the-loop).

## البنية

```
guardian_recon/
├── engine/
│   ├── models.py          # BankTransaction, GLTransaction, ReconciliationItem
│   ├── classifier.py       # تنظيف الوصف + تصنيف الأطراف (Petty Cash/Supplier)
│   └── reconciler.py       # محرك المطابقة (تامة + تقريبية) والتصنيف والتقادم
├── connectors/
│   ├── odoo_connector.py          # سحب قيود GL من Odoo + إنشاء قيود تسوية (draft)
│   └── bank_statement_loader.py   # قراءة كشف حساب من CSV/Excel
├── reports/
│   └── excel_report.py     # تصدير تقرير Excel كامل (6 أوراق ملونة حسب الحالة)
├── demo.py                 # تشغيل تجريبي كامل ببيانات وهمية
└── requirements.txt
```

## كيف يشتغل المحرك (خطوة بخطوة)

1. **المطابقة التامة**: نفس المبلغ + نفس التاريخ → `Matched`
2. **المطابقة التقريبية**: نفس المبلغ ± نافذة أيام (افتراضي 5) + تشابه في الوصف
   → إذا فيه فرق تاريخ: `Timing Difference` (شيك معلّق/إيداع بالطريق)
   → إذا نفس التاريخ بالضبط بس وصف مختلف شوي: `Adjustment Required`
3. **بدون تطابق**: يبقى `Requires Investigation`
4. **التقادم**: كل عنصر غير مطابق يُحسب له عمر بالأيام (Current/Aging/Overdue/Stale)
5. **التصعيد**: أي عنصر فرقه > 10,000 ريال أو عمره > 60 يوم يُعلَّم للمراجعة

## التشغيل السريع (تجريبي)

```bash
pip install -r requirements.txt
cd ..   # اطلع من مجلد guardian_recon
python -m guardian_recon.demo
```

## الربط بأودو الفعلي

```python
from guardian_recon.connectors.odoo_connector import OdooConnector
from guardian_recon.connectors.bank_statement_loader import load_bank_statement
from guardian_recon.engine.reconciler import ReconciliationEngine
from guardian_recon.reports.excel_report import export_reconciliation_report
from datetime import date

# 1) سحب قيود GL من Odoo
connector = OdooConnector(host="your-host", db="your-db",
                           user="your-user", password="your-password")
gl_txns = connector.fetch_gl_transactions(
    account_code="1010",              # كود حساب البنك في دليل الحسابات
    date_from="2026-06-01", date_to="2026-06-30"
)

# 2) قراءة كشف الحساب البنكي
bank_txns = load_bank_statement("statement_june.xlsx")

# 3) التسوية
engine = ReconciliationEngine(bank_txns, gl_txns, as_of=date(2026, 6, 30))
engine.run()
summary = engine.summary()

# 4) التقرير
export_reconciliation_report(summary, "recon_june_2026.xlsx")

# 5) (اختياري) إنشاء قيود تسوية تلقائية كمسودة — تحتاج موافقتك اليدوية في Odoo
for item in summary["items_by_category"]["Adjustment Required"]:
    connector.post_adjustment_entry(
        journal_id=1, account_id=101, counterpart_account_id=202,
        amount=item.difference, label=item.note, date_str=str(item.bank_txn.txn_date)
    )
```

## إعداد الأسرار (Secrets) — الاتصال بأودو

المشروع **لا يحتوي على أي بيانات اتصال حقيقية بالكود** — كلها تُقرأ من متغيرات
البيئة، محلياً عبر ملف `.env` أو بالإنتاج عبر GitHub Secrets. هذا يخلي الكود
آمن للرفع حتى لو المستودع عام.

### محلياً
```bash
cp .env.example .env
# افتح .env وعبّي القيم الحقيقية
```

### الأسرار المطلوبة

| الاسم | الوصف | مثال |
|---|---|---|
| `ODOO_HOST` | نطاق/IP سيرفر Odoo بدون `https://` | `mycompany.odoo.com` |
| `ODOO_PORT` | المنفذ (443 للسحابي عادة) | `443` |
| `ODOO_PROTOCOL` | `jsonrpc+ssl` سحابي / `jsonrpc` محلي بدون SSL | `jsonrpc+ssl` |
| `ODOO_DB` | اسم قاعدة بيانات Odoo | `mycompany-prod` |
| `ODOO_USER` | إيميل حساب Odoo | `moatasim@gitc.com` |
| `ODOO_PASSWORD` | كلمة المرور أو API Key (يُفضّل API Key) | — |

اختياري: `GUARDIAN_DB_URL` لو رقّينا من SQLite لـ PostgreSQL لاحقاً.

### بالكود
```python
from guardian_recon.connectors.odoo_connector import OdooConnector

# يقرأ تلقائياً من .env أو من متغيرات البيئة — بدون ما تكتب بيانات بالكود
connector = OdooConnector.from_env()
connector.connect()
```

### GitHub Secrets
`Settings` → `Secrets and variables` → `Actions` → `New repository secret` —
نفس الأسماء أعلاه بالضبط (حساسة لحالة الأحرف).

## لوحة المراقبة والموافقات (Human-in-the-loop Dashboard)

طبقة FastAPI + WebSocket فوق المحرك، بواجهة Dark Theme عربي، تخليك تراقب
وتوافق/ترفض بدل ما تدخل يدوي بكل قيد.

```bash
pip install fastapi uvicorn -r requirements.txt --break-system-packages
cd ..   # اطلع من مجلد guardian_recon
uvicorn guardian_recon.dashboard.main:app --host 0.0.0.0 --port 8420 --reload
```

افتح المتصفح على `http://localhost:8420` — بتلقى:
- **بطاقات إحصائية حية**: إجمالي العناصر، بانتظار الموافقة، تصعيد، مطابق تلقائياً
- **تبويبات حسب التصنيف**: مطابق تماماً / فروقات توقيت / تحتاج تسوية / تحتاج تحقيق
- **موافقة/رفض فردي أو جماعي** (تحديد عدة صفوف بالـ checkbox)
- **بث حي عبر WebSocket** — أي قرار ينعكس فوراً بدون تحديث الصفحة
- **سجل نشاط كامل** — كل قرار موثّق بالوقت والمسؤول

اضغط "▶ تشغيل تسوية تجريبية" لتشغيل المحرك ببيانات الديمو ومشاهدة اللوحة تعمل مباشرة.

### الربط بالتسوية الحقيقية

بدل `POST /api/run-demo`، شغّل `ReconciliationEngine` ببيانات Odoo الحقيقية
(زي المثال في القسم اللي فوق) واستدعِ `state.load_from_engine(engine)` من
داخل endpoint جديد — نفس اللوحة تشتغل مباشرة بدون أي تعديل على الواجهة.

### الخطوة التالية لكل عنصر "موافَق عليه"

حالياً الموافقة تُسجَّل في اللوحة فقط ولا تترحّل تلقائياً لأودو (لسا). الخطوة
الجاية الطبيعية: endpoint `/api/post-approved` يمر على كل عنصر `approved` من
نوع `Adjustment Required` وينشئ له قيد Odoo عبر `connector.post_adjustment_entry()`
(اللي هو أصلاً مسودة/draft) — بحيث تصير رحلة القيد: بنك → محرك → لوحتك →
موافقتك → مسودة Odoo → ترحيلك النهائي اليدوي في Odoo نفسه (طبقة أمان مزدوجة).

## الخطوة التالية في خارطة الطريق

- [ ] ربط `connectors/odoo_connector.py` بحسابك الحقيقي (بيانات الاتصال)
- [ ] لوحة مراقبة وموافقات (FastAPI + WebSocket) فوق هذا المحرك
- [ ] تفعيل تصنيف الأطراف بنموذج `scikit-learn` مدرَّب بدل القواعد الثابتة
- [ ] ربط Guardian Bot لتغذية بيانات التداول لنفس المنظومة
- [ ] تنبؤ تدفقات نقدية بـ `statsmodels`/`prophet` فوق بيانات GL التاريخية

## ⚠️ ملاحظة مهمة

هذا النظام أداة مساعدة للتسوية، وليس بديلاً عن المراجعة المهنية. أي قيد تسوية
يُنشأ تلقائياً يبقى **مسودة (draft)** في Odoo ولا يُرحَّل إلا بموافقتك اليدوية —
تصميم متعمد ليبقيك أنت المراقب والمعتمد النهائي، مو النظام.
