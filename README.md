# Dental Agent — سامانه مدیریت کلینیک دندان‌پزشکی با دستیار عامل‌محور

سامانه مدیریت کلینیک دندان‌پزشکی (FastAPI + SQLAlchemy Async + SQLite) با **دستیار هوش مصنوعی عامل‌محور** فارسی (LangChain/LangGraph) و **وب‌سایت نقش‌محور** (ورود واحد، داشبورد، بیماران، نوبت‌ها، پزشکان/خدمات/برنامه‌ها، کاربران و پنل گفت‌وگوی دستیار).

> در حالت توسعه (`APP_ENV=development`) پیامک واقعی ارسال نمی‌شود (تأمین‌کنندهٔ جعلی و `dev_otp`)؛ برای استقرار واقعی `APP_ENV=production` و `OTP_PROVIDER=smsir` را با کلید در `.env` (فایل git-ignored) تنظیم کنید. دادهٔ نمونهٔ محلی (`scripts/seed_sample.py`) فقط در `sample.db` ساخته می‌شود و هرگز روی دیتابیس واقعی اجرا نمی‌شود.

## اجرای سریع

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # سپس JWT_SECRET و CONFIRMATION_HMAC_SECRET را مقداردهی کنید

python -m app.auth.bootstrap_admin    # ساخت اولین مدیر (تعاملی)
$env:DATABASE_URL = "sqlite+aiosqlite:///./sample.db"
python -m scripts.seed_sample         # (اختیاری) داده نمونه در sample.db

# (اختیاری ولی توصیه‌شده) ساخت رابط کاربری React جدید
cd webapp ; npm install ; npm run build ; cd ..

uvicorn app.main:app --reload --port 8000

# اشتراک در شبکهٔ داخلی (بدون reload):
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

برای دسترسی سایر دستگاه‌های شبکه، در مرورگر `http://<LAN-IP>:8000/app` را باز کنید (مثلاً `http://192.168.152.32:8000/app`). پورت 8000 باید در فایروال ویندوز برای شبکهٔ خصوصی/عمومی مجاز باشد. در حالت اشتراک شبکه، `/dev/sms` را فعال نگذارید؛ این پنل فقط برای توسعهٔ محلی است و کدهای OTP شبیه‌سازی‌شده را نمایش می‌دهد.

| مسیر | محتوا |
|---|---|
| `/app` | اپ React کلینیک (ورود رمز/OTP + داشبورد، بیماران، نوبت‌ها، پزشکان، چت ایجنت)؛ بدون build، fallback روی صفحهٔ قدیمی |
| `/demo` | حذف شده؛ درخواست به آن ۴۰۴ برمی‌گرداند |
| `/dev/sms` | سامانه پیامک لوکال (فقط توسعه، با `OTP_PROVIDER=fake`) |
| `/docs` | OpenAPI تعاملی |
| `/health` | سلامت سرویس |

### نمایش واقعی با `sample.db`

برای دیدن سامانه با دادهٔ واقع‌گرایانه (نوبت‌های امروز، صف پذیرش، پروندهٔ بالینی، نسخه و طرح درمان)، سرور را روی دیتابیس نمونهٔ محلی بالا بیاورید:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./sample.db"
.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
```

| نقش | ورود |
|---|---|
| مدیر | `09121234500` / `ClinicAdmin!1404` |
| پذیرش | `09121234501` / `ClinicDesk!1404` |
| پزشک | `09121234502` / `ClinicDoctor!1404` |
| بیمار | `09121234510` (ورود با OTP؛ کد در `/dev/sms`) |

داده‌های نمونه هر بار اجرا **فقط ردیف‌های تازه** می‌سازند و هیچ داده‌ای را حذف یا بازنویسی نمی‌کنند؛ اسکریپت فقط مسیر دقیق `sample.db` را می‌پذیرد.

### بخش‌های عملیاتی تازه

- **پذیرش امروز** (`/app` → «پذیرش امروز»): لیست نوبت‌های امروز به ترتیب ساعت با شمارهٔ صف، وضعیت (رزروشده / در انتظار / در حال درمان / تکمیل / عدم مراجعه) و یک اقدام بعدی برای هر ردیف.
- **پروندهٔ بالینی کامل**: علاوه بر یادداشت‌ها و چارت FDI، **نسخه‌ها** (دارو، دوز، تعداد، مدت) و **طرح درمان چندجلسه‌ای** (planned → in_progress → completed) در همان پرونده.
- APIهای تازه: `GET /appointments/day`، `POST /appointments/{id}/check-in|start|complete|no-show`، `POST /clinical/patients/{id}/prescriptions`، `POST/PUT /clinical/patients/{id}/plan-items`.

خدمات مدل زبانی: `AGENT_LLM_PROVIDER=ollama` (محلی) یا `openai`/`openrouter` — بدون مدل، بقیه سامانه کار می‌کند و فقط chat خطای ۵۰۳ مدیریت‌شده می‌دهد.

## معماری در یک نگاه

- **Backend = منبع حقیقت**: FastAPI + خدمات دامنه؛ رابط کاربری فقط مشتری همین APIهاست.
- **مجوز متمرکز**: `app/auth/permissions.py` هم برای HTTP و هم ابزارهای Agent (نقش‌ها: admin/receptionist/doctor/patient، fail-closed).
- **Agent امن**: ۱۰ ابزار allowlist‌شده؛ هر write با تأییدیه یک‌بارمصرف bound به (کاربر، نشست، ابزار، آرگومان)؛ هویت بیمار همیشه سرور-ساید؛ شناسه‌های داخلی هرگز به خروجی مدل/UI نمی‌روند.
- **چند پرونده در یک حساب**: صاحب حساب + اعضای خانواده، انتخاب بیمار با کارت‌های سرور-ساید و `selected_patient_id` مستقل برای هر گفتگو؛ کد ملی اجباری و تلفن هر پرونده یکتا.
- **بازخورد درون‌برنامه**: گزارش خطا/پیشنهاد برای هر پیام دستیار، ذخیرهٔ append-only و فهرست فقط برای admin.
- **نوبت‌دهی تراکنشی**: index یکتای جزئی `(doctor_id, appointment_time) WHERE status='scheduled'` + recheck اتمیک → رزرو هم‌زمان ناممکن؛ همه تاریخ‌ها جلالی، منطقه‌ی زمانی `Asia/Tehran`.
- **مهاجرت افزایشی و idempotent** در شروع برنامه (`app/db_migration.py`).

## مستندات

نمای کامل (تطبیق پروپوزال، ERD، ماتریس مجوز، فهرست API، ابزارهای Agent، راه‌اندازی، نتایج تست، محدودیت‌ها، طرح دفاع) در [`docs/README.md`](docs/README.md).

## آزمایش

```powershell
.\.venv\Scripts\python.exe -m pytest             # hermetic: بدون .env و بدون کلید LLM
.\.venv\Scripts\python.exe -m ruff check app scripts tests
npm install --prefix webapp
$env:NODE_PATH = (Resolve-Path .\webapp\node_modules).Path
node tests\ui\app_smoke.js                        # صفحهٔ legacy web/ → ALL WEB UI CHECKS PASSED
cd webapp ; npm run lint ; npm run test ; npm run test:dom ; npm run build   # TypeScript + تست واحد + تست تعاملی (jsdom) + Vite
```
