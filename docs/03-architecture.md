# ۳. معماری کلی سامانه و جریان Agent

## نمای کلی

```
مرورگر (webapp/ — اپ React  ·  جایگزین: web/index.html)
   │  fetch + Bearer token (same-origin)
   ▼
FastAPI (app/main.py)
   ├── auth router        (login، OTP، /auth/me)
   ├── routers CRUD       (users، patients، doctors، services، schedules، appointments)
   ├── agent_chat router  (POST /agent/chat)
   └── error_handling     (کد خطاهای کاتالوگ‌شده، X-Request-ID)
                │
                ▼
        خدمات دامنه (app/services/*)
                │
                ▼
        SQLAlchemy + SQLite (مهاجرت افزایشی در شروع برنامه)
```

## جریان یک نوبت گفت‌وگو با Agent (POST /agent/chat)

```
۱. احراز هویت: کاربر از توکن JWT سمت سرور شناسایی می‌شود (نه از ورودی مدل).
۲. ساخت AgentState: پیام کاربر + تاریخچهٔ گفت‌وگو که سمت سرور و فقط برای همان کاربر ذخیره شده است (بدون PII داخلی).
۳. گراف LangGraph:
      agent_decision (برگی حداکثر ۱۲ گام؛ در صورت حلقه، پایان امن)
        ├─ مدل زبانی (LLM) فقط از میان ابزارهای اجازه‌گرفته انتخاب می‌کند (bind_tools).
        ├─ ابزار خواندنی → tool_execution
        ├─ ابزار نوشتن  → confirmation_gate
        └─ بدون ابزار    → پاسخ نهایی فارسی
۴. confirmation_gate:
      - هدف نوبت از دیتابیس یکتا می‌شود (resolve_appointment_target)؛ در ابهام، سؤال شفاف پرسیده می‌شود.
      - مجوز عملیات مجدداً توسط authorize_tool_call بررسی می‌شود.
      - خلاصه‌ی عملیات فقط از رکورد واقعی ساخته می‌شود (نام پزشک/خدمت/تاریخ).
      - تأییدیه صادر و در جدول agent_confirmations ذخیره می‌شود (HMAC hash).
۵. اجرا: پس از پاسخ «approved» با token + session از همان کاربر، رکورد مصرف (single-use) می‌شود و ابزار با هویت سرور اجرا می‌گردد.
۶. گزارش نتیجه: پیام موفقیت/خطا از نتیجه‌ی واقعی ابزار و رکورد commit شده ساخته می‌شود؛ شناسه داخلی نوبت هرگز در خروجی/تاریخچه/لاگ نمی‌نشیند.
```

## نقاط کلیدی امنیت

- **تک‌نقطهِ مجوز**: `app/auth/permissions.py` برای HTTP و ابزارهای Agent یکسان.
- **هویت همیشه سرور-ساید**: لا‌ییر مدل/کلاینت هرگز `patient_id`/`appointment_id`/نقش را تعیین نمی‌کند.
- **تفکیک داده داخلی**: آرگومان‌های حساس (کد ملی، نام، شماره، شناسه‌ها) در `internal` نگهداری و از پیام‌های مدل حذف می‌شوند (`safe_tool_call_for_history`).
- **محدویت مدل**: مدل انتخاب‌گر است؛ مقام تصمیم اجرا، عبور از `authorize_tool_call` و گیت تأیید است.
- **پاسخ خطای یکدست**: همه خطاها به کد کاتالوگ‌شده‌ی فارسی در `app/errors.py` نگاشت می‌شوند؛ جزئیات استثنا لاگ نمی‌شود.

## مدل زبانی و پیکربندی

انتخاب ارائه‌دهنده با متغیرهای محیطی (`AGENT_LLM_PROVIDER`) انجام می‌شود؛ Ollama برای اجرای محلی و OpenAI/OpenRouter سازگار برای سرویس ابری. نبود تنظیمات منجر به خطای کاتالوگ `AGENT_PROVIDER_NOT_CONFIGURED` (۵۰۳) بدون کرش است.
