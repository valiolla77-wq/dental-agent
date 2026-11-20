# مستندات سامانه مدیریت کلینیک دندان‌پزشکی با دستیار هوش مصنوعی عامل‌محور

این مجموعه مستندات، توصیف واقعی و دقیق پیاده‌سازی است؛ هر قابلیتی که پیاده‌سازی نشده باشد در سند «محدودیت‌ها» صریحاً ثبت شده است.

| سند | محتوا |
|---|---|
| [01-introduction.md](01-introduction.md) | معرفی مسئله، اهداف و دامنه پروژه |
| [02-proposal-compliance.md](02-proposal-compliance.md) | تطبیق قابلیت‌های پیاده‌سازی‌شده با پروپوزال |
| [03-architecture.md](03-architecture.md) | معماری کلی سامانه و جریان اجرای Agent |
| [04-erd.md](04-erd.md) | نمودار ERD متناسب با مدل‌های واقعی |
| [05-permissions.md](05-permissions.md) | نقش‌ها و ماتریس مجوزها |
| [06-api.md](06-api.md) | فهرست APIهای سامانه |
| [07-agent-tools.md](07-agent-tools.md) | ابزارهای Agent و اجرای کنترل‌شده عملیات |
| [08-setup.md](08-setup.md) | راه‌اندازی و اجرای محلی |
| [09-testing.md](09-testing.md) | سناریوهای آزمایش و نتایج واقعی |
| [10-limitations.md](10-limitations.md) | محدودیت‌ها و قابلیت‌های توسعه آینده |
| [11-defense-plan.md](11-defense-plan.md) | طرح نمایش پروژه برای جلسه دفاع |
| [12-similar-platforms-research.md](12-similar-platforms-research.md) | تحقیق تطبیقی پلتفرم‌های مشابه (ایجنتیک/غیرایجنتیک) و الگوهای اقتباس‌شده |
| [13-usage-scenarios.md](13-usage-scenarios.md) | سناریوهای استفادهٔ واقعی در یک روز کاری کلینیک (پذیرش، پزشک، مدیر، بیمار) |
| [14-development-plan.md](14-development-plan.md) | طرح توسعهٔ وضعیت سامانه، مرکز حساب کاربری نقش‌محور و پیشنهادهای زمینه‌مند دستیار (پیش‌نویس برای تأیید) |
| [15-subagents-plan.md](15-subagents-plan.md) | طرح ساخت و به‌کارگیری زیرایجنت‌های توسعه، تست، امنیت، مستندات و پژوهش (پیش‌نویس برای تأیید) |

## نقشه گزیده فایل‌ها

```
dental-agent/
├── web/index.html           # وب‌سایت فارسی/RTL نقش‌محور  → http://127.0.0.1:8000/app
├── web/assets/app.css, app.js
├── app/
│   ├── main.py              # چیدمان اپلیکیشن FastAPI
│   ├── auth/                # JWT، Argon2id، OTP، ماتریس مجوز (permissions.py)
│   ├── routers/             # کاربران، بیماران، پزشکان، خدمات، نوبت‌ها، دستیار
│   ├── services/            # منطق دامنه (رزرو، لغو، جابه‌جایی، جستجو)
│   ├── agent/               # گراف LangGraph، پرمپت، تأییدیه‌ها، انتخاب نوبت
│   ├── agent_tools/         # ابزارهای اجازه‌گرفته + اسکیمای ورودی/خروجی
│   ├── models/              # مدل‌های SQLAlchemy
│   ├── db_migration.py      # مهاجرت‌های افزایشی ایمن
│   └── errors.py            # کد خطاهای کاتالوگ‌شده (پیام فارسی)
├── scripts/seed_sample.py   # داده نمونهٔ محلی فقط برای sample.db
├── tests/                   # مجموعه تست‌های خودکار + tests/ui/*_smoke.js
└── docs/                    # همین مستندات
```
