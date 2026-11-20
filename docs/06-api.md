# ۶. فهرست APIهای سامانه

همه endpointها مگر موارد مشخص، احراز هویت (`Authorization: Bearer <JWT>`) می‌خواهند. ساختار خطای یکدست:

```json
{ "error": { "code": "APPOINTMENT_SLOT_BOOKED", "message": "این زمان قبلاً ... رزرو شده است.",
             "details": {}, "request_id": "uuid" } }
```

## Authentication (`/auth`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `POST /auth/login` | همه (با رمز) | Rate-limit per phone/IP؛ پاسخ یکنواخت برای خطا. فیلد اختیاری `portal`: `patient` حساب‌های پرسنل را (۴۰۳ `AUTH_PORTAL_MISMATCH`) و `staff` حساب‌های بیمار را رد می‌کند؛ بدون portal رفتار قدیمی حفظ می‌شود. ورود موفق `last_login_at` را ثبت می‌کند |
| `POST /auth/staff/login` | admin/receptionist/doctor | درگاه فقط-پرسنل؛ حساب بیمار حتی با رمز درست ۴۰۳ می‌گیرد |
| `POST /auth/otp/request` | بیمار | کد یک‌بارمصرف؛ پاسخ یکنواخت؛ `dev_otp` فقط در `APP_ENV=development\|test` |
| `POST /auth/otp/verify` | بیمار | ایجاد حساب بیمار خودکار برای شماره جدید |
| `GET /auth/me` | همه | نام، نقش، وضعیت + رکورد متصل (بیمار/پزشک) |

## Users (`/users`, فقط admin)

| متد و مسیر | توضیح |
|---|---|
| `POST /users/` | ایجاد حساب با نقش صریح؛ تاریخ ایجاد ثبت و در گزارش حسابرسی نوشته می‌شود |
| `GET /users/` | فهرست حساب‌ها (بدون هش رمز) شامل `created_at`، `last_login_at` و `permission_overrides` |
| `GET /users/{user_id}` | جزئیات یک حساب |
| `PUT /users/{user_id}` | تغییر نام/نقش/وضعیت/رمز؛ قفل‌شدن خودِ مدیر ممنوع؛ تنزل/غیرفعال‌کردن آخرین مدیر فعال ممنوع (`USER_LAST_ADMIN_PROTECTED`)؛ تغییر سمت، overrideهای دسترسی را پاک می‌کند |
| `DELETE /users/{user_id}` | حذف قطعی؛ ممنوع برای خودِ مدیر؛ ارجاع‌های نرم (پرونده متصل/گفتگو/بازخورد) جدا می‌شوند؛ در گزارش حسابرسی ثبت می‌شود |
| `GET /users/{user_id}/permissions` | ماتریس دسترسی حساب: پیش‌فرض نقش + override + اثر نهایی |
| `PUT /users/{user_id}/permissions` | جایگزینی کامل overrideها؛ فقط پذیرش/پزشک؛ آبجکت خالی = بازگشت به پیش‌فرض نقش |

## Audit Logs (`/audit-logs`, فقط admin)

| متد و مسیر | توضیح |
|---|---|
| `GET /audit-logs/?limit=&offset=&action=` | دنبالهٔ فقط-افزودنی تغییرات حساس (حساب‌ها، دسترسی‌ها، حذف پرونده، CRUD پزشک/خدمت)؛ بدون ویرایش/حذف |

## Patients (`/patients`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `GET /patients/?search=` | admin/receptionist/doctor (بیمار: فقط پرونده‌های متصل) | جستجو در نام/تلفن/کد ملی |
| `GET /patients/{id}` | همان قاعده ownership | |
| `POST /patients/me` | بیمار | ثبت پروندهٔ `self` یا `other`؛ کد ملی اجباری، تلفن یکتا |
| `POST /patients/` | admin/receptionist | کد ملی یکتا → `409 PATIENT_DUPLICATE_NATIONAL_ID` |
| `PUT /patients/{id}` | admin/receptionist | |
| `DELETE /patients/{id}` | admin | اگر نوبت فعال داشته باشد `409 PATIENT_HAS_ACTIVE_APPOINTMENTS`؛ تاریخچه همراه پرونده حذف و در گزارش حسابرسی ثبت می‌شود |
| `POST /patients/{id}/link-user` | admin | پیوند انطباقی با تلفن |

## Doctors / Services / Schedules

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `GET /doctors/`، `GET /doctors/{id}` | همه نشسته‌ها | کاتالوگ بدون شماره تلفن |
| `GET /doctors/manage` | admin | فهرست مدیریتی: تلفن + `user_id` + `service_ids` در یک فراخوان |
| `GET /doctors/{id}/manage` | admin | رکورد کامل یک پزشک برای فرم ویرایش |
| `GET /doctors/{id}/services` | همه نشسته‌ها | خدمات یک پزشک |
| `POST /doctors/` ، `PUT /doctors/{id}` | admin | پاسخ admin شامل تلفن؛ در گزارش حسابرسی ثبت می‌شود |
| `POST /doctors/{id}/link-user` | admin | پیوند حساب پزشک به رکورد؛ در گزارش حسابرسی ثبت می‌شود |
| `GET /dental-services/`، `GET /dental-services/{id}` | عمومی (بدون داده حساس) | |
| `GET /dental-services/{id}/doctors` | همه نشسته‌ها | |
| `POST/PUT/DELETE /dental-services*` | admin | |
| `GET /doctor-schedules/{doctor_id}` | همه نشسته‌ها | |
| `POST/PUT/DELETE /doctor-schedules*` | admin | |

## Appointments (`/appointments`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `GET /appointments/` | admin/receptionist/doctor | فیلترها: `doctor_id`, `patient_id`, `appointment_date` (جلالی), `status`؛ پزشک فقط خود |
| `GET /appointments/me` | بیمار | نوبت‌های حساب خود (بدون نیاز به شناسه) |
| `GET /appointments/patient/{id}` | مطابق ownership | سازگاری با کلاینت‌های قدیمی |
| `GET /appointments/available-slots/?doctor_id&appointment_date` | همه نشسته‌ها | slotهای واقعاً آزاد (جلالی) |
| `POST /appointments/` | admin/receptionist/بیمار-خود | ثبت رزرو تراکنشی |
| `POST /appointments/{id}/cancel` | مطابق ماتریس | فقط نوبت `scheduled` |
| `POST /appointments/{id}/reschedule` | مطابق ماتریس | بدون بازation |

## Agent (`/agent`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `POST /agent/chat` | همه نشسته‌ها | یک turn؛ تاریخچه حداکثر ۲۰ پیام؛ `session_id` bound به کاربر؛ انتخاب بیمار در چندپرونده‌ای |

## Feedback (`/feedback`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `POST /feedback/` | همه نشسته‌ها | ثبت گزارش خطا یا پیشنهاد؛ برای error، ۲۰۰ خط آخر لاگ بافر |
| `GET /feedback/` | admin | فهرست جدیدترین بازخوردها (حداکثر ۳۰۰) |

## پرونده بالینی (`/clinical`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `GET /clinical/me` | بیمار | پرونده سلامت همه پرونده‌های حساب (رکوردها + نقشه دندان) — مالکیت از توکن |
| `GET /clinical/patients/{id}` | مدیر/پذیرش/پزشک | مشاهده پرونده بالینی یک بیمار (`clinical:read`) |
| `POST /clinical/patients/{id}/entries` | مدیر/پزشک | افزودن یادداشت درمان/حساسیت/یادداشت (`clinical:write`)؛ هم‌تراکنش با audit و اعلان |
| `PUT /clinical/patients/{id}/teeth/{fdi}` | مدیر/پزشک | ثبت وضعیت دندان FDI (سالم/درمان‌شده/نیاز به درمان/کشیده‌شده) |

## اعلان‌ها (`/notifications`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `GET /notifications/me` | همه نشسته‌ها | ۵۰ اعلان آخر + شمارنده خوانده‌نشده؛ برای بیمار، یادآور ۲۴ساعته idempotent ساخته می‌شود |
| `POST /notifications/{id}/read` | مالک اعلان | علامت‌گذاری خوانده‌شده (اعلان بیگانه = ۴۰۴) |
| `POST /notifications/read-all` | همه نشسته‌ها | خواندن همه اعلان‌های حساب |

## امتیاز رضایت (`/visit-ratings`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `POST /visit-ratings/` | بیمار | امتیاز ۱-۵ + نظر برای نوبت گذشته غیرلغوشده خود؛ یک بار برای هر نوبت |
| `GET /visit-ratings/mine` | بیمار | امتیازهای خود حساب (برای پنهان‌کردن ویزیت‌های امتیاز داده‌شده) |
| `GET /visit-ratings/summary` | admin | میانگین کل و ۳۰روزه رضایت بیماران |

## حساب من (`/users/me`)

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `PUT /users/me` | همه نشسته‌ها فعال | تغییر نام نمایشی خود؛ تلفن/نقش/وضعیت محافظت‌شده؛ ثبت در audit (`user.self_update`) |

## سلامت و پایش

| متد و مسیر | نقش‌ها | توضیح |
|---|---|---|
| `GET /health` | عمومی | Liveness بدون وابستگی؛ فقط `{"status":"healthy"}` و هیچ جزئیات اتصال یا رازی برنمی‌گرداند |
| `GET /health/ready` | عمومی | Readiness؛ با `SELECT 1` اتصال پایگاه داده را بررسی می‌کند و در قطعی `503` می‌دهد |
| `GET /system/health` | مدیر | خلاصهٔ عملیاتی: نسخه، uptime، وضعیت پایگاه داده، نام ارائه‌دهندهٔ پیامک و دستیار؛ بدون کلید، آدرس داخلی یا داده بیمار |

## وب — صفحه‌ها

| مسیر | توضیح |
|---|---|
| `/app` | وب‌سایت نقش‌محور فارسی (ورود یکپارچه + پنل) |
| `/app-assets/*` | Assets همان‌مبدأ |
| `/demo` | حذف شده؛ ۴۰۴ برمی‌گرداند |
| `/docs`, `/redoc` | OpenAPI تعاملی (خودکار FastAPI) |
