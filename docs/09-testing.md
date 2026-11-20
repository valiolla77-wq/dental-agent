# ۹. سناریوها و نتایج واقعی آزمایش

## دستورها

```powershell
# مجموعه کامل تست‌های Python/HTTP/service/agent
.\.venv\Scripts\python.exe -m pytest -q
# تست‌ها hermetic هستند: بدون `.env` و بدون کلید LLM اجرا می‌شوند (CI هم همین‌طور).
# تعداد تست‌ها را در خروجی خود pytest ببینید؛ عدد ثابتی در مستندات نگه‌داری نمی‌شود.

# لینت پایتون
.\.venv\Scripts\python.exe -m ruff check app scripts tests

# تست‌های DOM صفحهٔ قدیمی web/ (از jsdom نصب‌شده در webapp استفاده می‌کند)
npm install --prefix webapp
$env:NODE_PATH = (Resolve-Path .\webapp\node_modules).Path
node tests\ui\app_smoke.js      # صفحهٔ legacy web/ → ALL WEB UI CHECKS PASSED

# تست‌های منطق فرانتِ React (RBAC، تاریخ جلالی، تعارض نوبت)
cd webapp ; npm run lint   # tsc --noEmit
npm run test               # تست‌های واحد منطق (RBAC، تاریخ، تعارض، زمان‌های خالی) + محافظ مقیاس تایپی
npm run test:dom           # تعامل واقعی با مودال رزرو (۹ سناریو) + «ظاهر محصول» (۴ سناریو: ورود، هدر، قطع ارتباط) + دو درگاه ورود در jsdom
npm run build              # → Vite build موفق
cd ..
```

## پوشش به تفکیک سناریو

| حوزه | تست‌ها |
|---|---|
| احراز هویت (رمز/OTP، rate-limit، پاسخ یکنواخت) | `test_otp_auth.py`، `test_login_rate_limit.py` |
| شاخه‌های کم‌تردد نود تصمیم (ابزار درخواستی میزبان، آرگومان نامعتبر، فراخوانی ناقص مدل، پاسخ خالی) | `test_agent_decision_branches.py` |
| سخت‌سازی: سقف صدور OTP، محدودکنندهٔ چت/بازخورد، حافظهٔ کران‌دار، اعتبارسنجی راز‌ها هنگام شروع، هش async | `test_hardening.py` |
| تأمین‌کننده پیامک واقعی (SMS.ir؛ حالت قالب/خط، fail-closed، بدون لاگ کد/کلید) | `test_sms_provider.py` (+ سناریوی خرابی ارسال در `test_otp_auth.py`) |
| سامانه پیامک لوکال (اینباکس شبیه‌سازی‌شده و fail-closed آن) | `test_dev_sms_panel.py` |
| ماتریس مجوز و fail-closed | `test_permissions.py` |
| IDOR و پیوند حساب–پرونده | `test_link_and_idor.py`، `test_patient_link_migration.py` |
| حریم کاتالوگ (بدون تلفن پزشک برای غیر-admin) | `test_catalog_privacy.py` |
| رزرو/لغو/جابه‌جایی و تراکنش‌ها | `test_appointment_http_flow.py` |
| یکتایی slot (رزرو هم‌زمان) | `test_appointment_slot_uniqueness.py` |
| تداخل‌ها و کد خطاهای APPOINTMENT_* | `test_appointment_conflicts.py` |
| سرویس‌های دامنه (بیمار/پزشک/خدمت/برنامه) | `test_patient_service.py`، `test_doctor_service.py`، `test_dental_service.py`، `test_doctor_schedule_service.py` |
| جستجوی فارسی خدمات | `test_service_search_fa.py` |
| ابزارهای Agent (رزرو/لغو/جابه‌جایی/نزدیک‌ترین/نوبت‌های بیمار) | `test_book_appointment_tool.py`*، `test_cancel_appointment_tool.py`، `test_reschedule_appointment_tool.py`، `test_nearest_appointments.py`، `test_get_patient_appointments.py`* |
| چند پرونده در یک حساب، انتخاب بیمار و رزرو خانوادگی | `test_multi_patient_chat.py`، `test_patient_record_flow.py` |
| بازخورد کاربر و فهرست admin | `test_feedback.py` |
| گزارش‌های کارکنان/مدیر | `test_reports_endpoints.py` |
| سخت‌سازی Agent (allowlist/تأیید/محدود پارامتر/خطای LLM) | `test_agent_hardening.py`، `test_agent_security.py`* |
| مجوز فراخوانی Toolها | `test_agent_tool_authorization.py` |
| تأییدیه‌های یک‌بارمصرف | `test_confirmations.py`* |
| APIهای مدیریتی تازه (users/doctors/appointments/me/link) | `test_management_apis.py` (۱۶ تست) |
| صفحه‌های وب (روتینگ/static؛ bundle React یا fallback قدیمی) | `test_web_app_pages.py`، `test_sample_ui_and_seed.py` (seeder نمونه) |
| سلامت سرویس و صفحهٔ مدیر (liveness/readiness، عدم افشای راز) | `test_system_health.py` |
| مهاجرت افزایشی و شِما | `test_database_schema.py` |
| هندلینگ خطای یکدست | `test_error_handling.py` |
| کارخانه مدل LLM | `test_provider_factory.py` |

\* نام دقیق برخی فایل‌ها ممکن است کمی متفاوت باشد؛ برای فهرست کامل `Get-ChildItem tests` را ببینید.

## سناریوهای پذیرش پروپوزال (و پوشش آن‌ها)

| سناریو | پوشش |
|---|---|
| ورود پذیرش/مدیر با رمز و ورود بیمار با OTP | `test_otp_auth.py` + `app_smoke.js` (مسیر login) |
| رزرو نوبت از طریق دستیار با تأیید صریح | `test_agent_hardening.py` + `app_smoke.js` (confirmation pane) |
| جلوگیری از رزرو هم‌زمان دو کاربر | `test_appointment_slot_uniqueness.py` |
| بیمار نمی‌تواند نوبت/پرونده بیمار دیگر را ببیند | `test_link_and_idor.py` |
| پزشک فقط نوبت‌های خود را می‌بیند (پیوند حساب→رکورد) | `test_management_apis.py::test_doctor_listing_is_scoped_to_linked_record` |
| لغو/جابه‌جایی نوبت لغوشده مجاز نیست | `test_appointment_conflicts.py` |
| شناسه داخلی در خروجی Agent/UI نمایش داده نمی‌شود | `test_agent_hardening.py` + `app_smoke.js::no internal ids` |
| منقضی‌شدن نشست در UI → بازگشت به ورود | `app_smoke.js::401 clears the session` |

## یادداشت فنی

- تست‌ها همه در دیتابیس حافظه (`sqlite+aiosqlite:///:memory:`) اجرا می‌شوند؛ `sample.db` واقعی دست‌نخورده می‌ماند.
- تست‌های DOM جایگزین مرورگر واقعی نیستند؛ خروجی‌های حساس سرراست از پاسخ API‌های مسخره‌شده در سطح جاوااسکریپت خوانده می‌شوند و رندر امن (textContent) را می‌سنجند.
