# ۷. ابزارهای Agent و اجرای کنترل‌شده عملیات

## فهرست ابزارهای اجازه‌گرفته (`app/agent/registry.py`)

| ابزار | نوع | شرح | مالکیت/محدودیت | نقش‌های مجاز |
|---|---|---|---|---|
| `search_dental_services` | read | جستجوی خدمات کلینیک | — | همه نقش‌ها |
| `find_doctors_for_service` | read | پزشکان ارائه‌دهنده یک خدمت | — | همه نقش‌ها |
| `find_available_slots` | read | ساعت‌های آزاد یک پزشک | تاریخِ معتبر جلالی؛ فقط آینده | همه نقش‌ها |
| `find_nearest_appointments` | read | نزدیک‌ترین slotهای کلینیک | سقف نتایج | همه نقش‌ها |
| `get_patient_appointments` | read | نوبت‌های یک بیمار | بیمار: فقط خود (`patient_id` تزریق سرور-ساید) | همه نقش‌ها (مطابق ماتریس) |
| `book_appointment` | write | رزرو نوبت | تأیید صریح لازم؛ بیمار: فقط پروندهٔ انتخاب‌شدهٔ خود/خانواده | admin/receptionist/بیمار-خود |
| `reschedule_appointment` | write | جابه‌جایی نوبت | تأیید صریح لازم | مطابق ماتریس |
| `cancel_appointment` | write | لغو نوبت | تأیید صریح لازم | مطابق ماتریس |
| `get_clinic_appointments_report` | read | آمار نوبت‌های کلینیک و بار پزشکان | فقط کارکنان | admin/receptionist/doctor |
| `get_clinic_overview_stats` | read | نمای کلی بیماران/پزشکان/خدمات/نوبت‌ها | فقط admin | admin |
| `search_patients` | read | جست‌وجوی بیمار با نام/تلفن/کد ملی | فقط کارکنان؛ کد ملی در خروجی پوشانده می‌شود | admin/receptionist/doctor |
| `get_patient_summary` | read | کارت خلاصهٔ بیمار (نوبت بعدی، مراجعه‌های اخیر، وضعیت پرونده) | فقط کارکنان | admin/receptionist/doctor |
| `get_doctor_schedules` | read | برنامهٔ هفتگی پزشکان فعال | — | همه نقش‌ها (شامل بیمار) |
| `get_doctor_day_plan` | read | برنامهٔ روزانهٔ یک پزشک (نام بیمار، خدمت، ساعت، وضعیت) | فقط کارکنان؛ حساب پزشک به پروندهٔ خودش محدود است؛ مدیر/پذیرش باید `doctor_id` بدهند | admin/receptionist/doctor |
| `get_user_reports_summary` | read | خلاصهٔ بازخوردهای کاربران (دسته/وضعیت/۵ مورد اخیر) | فقط admin | admin |
| `get_my_profile` | read | کارت پرونده‌های حساب بیمار (نام، تلفن، رابطه، وضعیت پرونده، نوبت بعدی) | فقط بیمار؛ کد ملی هرگز در خروجی نیست؛ مالکیت سرور-ساید | patient |
| `create_patient` | write | ثبت پروندهٔ بیمار جدید (کد ملی ۱۰ رقمی، نام، تلفن یکتا) | تأیید صریح لازم؛ در حسابرسی (`patient.create`) ثبت می‌شود | admin/receptionist (پزشک با override) |
| `update_patient` | write | ویرایش نام/تلفن/کد ملی پروندهٔ موجود | تأیید صریح لازم؛ فیلدهای ارسال‌نشده بدون تغییر؛ در حسابرسی (`patient.update`) ثبت می‌شود | admin/receptionist (پزشک با override) |
| `get_staff_directory` | read | شمارش حساب‌ها بر اساس نقش، فعال/غیرفعال، ۵ حساب با آخرین ورود | فقط admin؛ رمز عبور هرگز در خروجی نیست | admin |
| `get_audit_trail` | read | آخرین رخدادهای حساس زنجیرهٔ audit (اکشن، بازیگر، هدف، زمان) | فقط admin؛ خروجی فقط-خواندنی از جدول فقط-افزودنی | admin |
| `submit_feedback` | write | ثبت گزارش خطا یا پیشنهاد از درون چت | تأیید صریح لازم؛ ردیف فقط به حساب واردشده متصل می‌شود (`context.source=agent`) | همه نقش‌ها |

## گسترش دسترسی نقش‌محور (۲۰۲۶-۱۰-۳۰)

- **دو اکشن جدید در ماتریس دسترسی:** `patient:search` (admin/receptionist/doctor) و `report:feedback` (فقط admin)؛ هر دو قابل Override در صفحهٔ پرسنل هستند و برچسب فارسی در UI دارند.
- **فیلتر نمایش نقش‌محور اسکیماها:** `get_llm_tool_schemas(patient_bound, role)`؛ ابزارهای `admin_only` از دید جلسهٔ پذیرش/پزشک حذف می‌شوند (fail-closed: بدون نقش هم مخفی‌اند). این فیلتر فقط «قابلیت استفاده» است؛ مرز امنیتی همان `authorize_tool_call` سرور-ساید باقی می‌ماند.
- **حریم خصوصی:** کد ملی در خروجی `search_patients` و `get_patient_summary` فقط به‌صورت `***سه رقم آخر` به مدل می‌رسد؛ کد ملی کامل فقط از پنل پرونده‌ها قابل مشاهده است.
- **پیوند با عملیات نوشتن:** `get_doctor_day_plan` شناسهٔ نوبت را برای حساب‌های کارکنان برمی‌گرداند تا لغو/جابه‌جایی از طریق ایجنت (همراه با همان جریان تأیید یک‌بارمصرف) ممکن شود.

## گسترش دوم نقش‌محور: ۲۱ ابزار (۲۰۲۶-۱۰-۳۰، نسخهٔ سوم)

- **شش ابزار جدید (مجموع ۲۱):** `get_my_profile` (فقط بیمار؛ پرچم جدید `patient_only`)، `create_patient` و `update_patient` (مدیریت پرونده توسط پذیرش/مدیر با جریان تأیید)، `get_staff_directory` و `get_audit_trail` (فقط admin)، `submit_feedback` (همهٔ نقش‌ها).
- **سه اکشن جدید در ماتریس:** `user:read` و `audit:read` (فقط admin) و `feedback:create` (همهٔ نقش‌ها) — خودکار در UI ماتریس دسترسی ظاهر می‌شوند و برای پذیرش/پزشک قابل Override هستند.
- **visibility هم‌راستا با ماتریس مجوز:** ابزارهای staff_only فقط وقتی به مدل عرضه می‌شوند که نقش (یا override `allow` حساب) اکشن متناظر را داشته باشد؛ مدل هرگز ابزاری نمی‌بیند که فراخوانی‌اش مردود می‌شود. `get_llm_tool_schemas` پارامتر اختیاری `actor` گرفت تا overrideهای حساب در visibility هم لحاظ شود.
- **audit فراخوانی‌های مردود:** هر تلاش برای فراخوانی ابزاری که مجوز ندارد (`COMMON_FORBIDDEN`) با اکشن `agent.tool.denied` در `audit_logs` ثبت می‌شود (بدون افشای جزئیات).
- **توضیح تأیید نقش‌محور:** `_describe_action` برای `create_patient` (کد ملی پوشانده‌شده)، `update_patient` (فقط فیلدهای تغییرکرده از دیتابیس) و `submit_feedback` (پیش‌نمایش متن) توضیح فارسی می‌سازد.
- **پرامپت نقش‌محور:** بخش «ابزارهای نقش‌محور» در system prompt + خطوط زمینهٔ نقش (بیمار/کارکنان/مدیر) در `build_system_prompt(now, patient_bound, role)`؛ `role` از گراف به پرامپت منتقل می‌شود.
- **نکتهٔ تست:** نام `submit_feedback` شامل «db» است؛ tripwire قدیمی `assertNotIn("db", ...)` در `test_agent_graph` به بررسی دقیق‌تر نشت (`AsyncSession`، `sqlalchemy`، `object at 0x`) ارتقا یافت.
- **تست‌ها:** ۱۶ تست جدید در `tests/test_agent_role_tools.py` (visibility ماتریس، override پزشک، جریان کامل تأیید create/update patient با audit، deny بیمار، فهرست حساب‌ها و audit برای admin، بازخورد بیمار با تأیید، اکشن‌های جدید در UI ماتریس)؛ به‌علاوه به‌روزرسانی تعدادهای `test_agent_llm` (۱۰/۲۰/۱۶/۱۴/۱۱).

## ویژگی‌های اجرای امن

1. **Allowlist**: مدل فقط می‌توانید درخواست ابزار از این فهرست بدهد؛ هر نام دیگر رد می‌شود (`TOOL_NOT_ALLOWED`).
2. **اعتبارسنجی ورودی**: آرگومان‌ها با اسکیمای Pydantic (`agent_tools/schemas.py`) اعتبارسنجی می‌شوند؛ خطا پیام فارسی بازگشتی به مدل می‌رسد، نه کرش.
3. **مجوز در زمان اجرا**: پیش از هر فراخوانی، `authorize_tool_call` همان ماتریس `permissions.py` را چک می‌کند.
4. **پارامترهای محدود (`PATIENT_BOUND_FIELDS`)**: برای بیمار، `patient_id` و فیلدهای هویتی هرگز از مدل گرفته نمی‌شوند؛ سرور پروندهٔ انتخاب‌شده در همان گفتگو (`selected_patient_id`) را تزریق می‌کند و انتخاب بیمار از کارت‌های سرور-ساید انجام می‌شود.
5. **تأییدیه یک‌بارمصرف**: توکن تصادفی فقط به‌صورت HMAC ذخیره می‌شود؛ bound به `(user_id, session_id, tool_name, tool_call_id)`؛ مصرف/انقضا/دوباره‌مصرف → `409 CONFIRMATION_EXPIRED_OR_USED`.
6. **مخفی‌سازی آرگومان‌های حساس در تاریخچه**: خروجیِ ثبت‌شده در پیام‌های مدل (`safe_tool_call_for_history`) از `internal` (شناسه‌ها/کد ملی/args) پاک می‌شود؛ حذف placeholder اثبات می‌کند که مدل آرگومان واقعی را برای اعلام موفقیت نمی‌بیند.
7. **سقف گام‌ها**: `AGENT_RECURSION_LIMIT`؛ حلقه بی‌پایان با پایان امن و پیام فارسی.
8. **خطای ارائه‌دهنده**: نبود پیکربندی/timeout/پاسخ نامعتبر → پیام کاتالوگ‌شده بدون افشای جزئیات (تست: `tests/test_agent_hardening.py`).

## چرا «واقعی» است، آزمایشی نیست؟

- مسیر chat واقعاً `CreateChatModel + bind_tools` را از ارائه‌دهنده تنظیم‌شده می‌سازد (fallback مسیر آزمایشی که سعی ابزار می‌سازد فقط برای تست محیط بدون LLM وجود دارد و هرگز تصادفی فعال نمی‌شود).
- تصمیم‌ها و خروجی نهایی از نتیجه‌ی واقعی ابزارها ساخته می‌شود؛ تأیید صرفنظر از مدل اعمال می‌شود (گیت در گراف است، نه در تنظیمات مدل).
- تست‌های `test_reschedule_appointment_tool.py`، `test_cancel_appointment_tool.py`، `test_nearest_appointments.py`، `test_agent_hardening.py` و `test_sample_ui_and_seed.py` این رفتارها را پوشش می‌دهند.
