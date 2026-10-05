# Dental Agent — Project Status

> آخرین وضعیت پروژه برای ادامه توسعه در Codex
> پروژه: **طراحی و پیاده‌سازی سامانه مدیریت مطب دندانپزشکی با دستیار هوشمند مبتنی بر ایجنت**

---

# 1. معرفی پروژه

این پروژه یک سامانه تحت وب برای مدیریت یک مطب دندانپزشکی است که در کنار امکانات مدیریتی معمول، یک **دستیار هوشمند مبتنی بر Agent** دارد.

هدف پروژه فقط ساخت یک Chatbot نیست.

هسته اصلی نوآوری پروژه:

* Agentic Architecture
* اتصال Agent به ابزارهای مشخص Backend
* کنترل Permission ابزارها
* ثبت Tool Callها
* ثبت Conversation و Message
* تصمیم‌گیری کنترل‌شده
* اعتبارسنجی تمام عملیات در Backend
* Human-in-the-loop برای عملیات حساس
* استفاده از Laya به عنوان Decision Engine
* استفاده از LangChain برای بخش Agent

موضوع پروژه توسط استاد تأیید شده است.

عنوان پیشنهادی:

**«طراحی و پیاده‌سازی سامانه مدیریت مطب دندانپزشکی با دستیار هوشمند مبتنی بر ایجنت»**

---

# 2. وضعیت کلی پروژه

پروژه در حال حاضر در مرحله **پیاده‌سازی Core Backend** است.

ترتیب پیشنهادی توسعه:

```text
Core API
   ↓
Security / Authentication / Authorization
   ↓
Error Handling استاندارد
   ↓
Agent Tools
   ↓
LangChain Agent
   ↓
Laya Decision Engine
   ↓
Frontend
   ↓
Admin/Support Agent
   ↓
Testing / Hardening / Documentation
```

در حال حاضر هنوز نباید وارد پیاده‌سازی کامل Agent شویم.

---

# 3. تکنولوژی‌های فعلی

## Backend

* Python
* FastAPI
* SQLAlchemy
* Pydantic
* SQLite
* aiosqlite
* Uvicorn

## Security فعلی

* `pwdlib`
* Argon2 برای Hash کردن Password

## AI / Agent

* LangChain
* Laya
* Ollama به عنوان LLM Provider اولیه در نظر گرفته شده است

## Date

* `jdatetime`

## Version Control

* Git
* GitHub

---

# 4. تصمیم معماری فعلی

معماری کلی:

```text
                 ┌──────────────────────┐
                 │      Frontend        │
                 │ Jinja2 / HTMX        │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │      FastAPI         │
                 │      REST API        │
                 └──────────┬───────────┘
                            │
                    Business Logic
                            │
                            ▼
                 ┌──────────────────────┐
                 │      Services        │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │     SQLAlchemy       │
                 │      Database        │
                 └──────────────────────┘
```

بخش Agent:

```text
User
  ↓
Chat UI
  ↓
LangChain Agent
  ↓
Laya Decision Engine
  ↓
Agent Tools
  ↓
Backend Services
  ↓
Database
```

اصل مهم:

**Agent نباید مستقیماً قوانین Business یا Database را دور بزند.**

Agent فقط از Toolهای مشخص استفاده می‌کند و Toolها باید از همان Business Logic و Validationهای Backend استفاده کنند.

---

# 5. Agentها

## Patient Agent

Agent اصلی پروژه برای بیمار است.

قابلیت‌های موردنظر:

* بررسی زمان‌های خالی
* رزرو نوبت
* لغو نوبت
* جابه‌جایی نوبت
* مشاهده نوبت‌های بیمار
* مشاهده سابقه مجاز
* پاسخ به FAQ

Toolهای موردنظر:

```text
check_available_slots()
book_appointment()
cancel_appointment()
reschedule_appointment()
get_patient_appointments()
get_patient_history()
search_faq()
```

---

# 6. Admin / Support Agent

این ایده مطرح شده ولی **فعلاً متوقف است و نباید وارد پیاده‌سازی آن شویم.**

در آینده قرار است بیشتر درباره آن بحث شود.

ایده کلی:

یک Agent مخصوص مدیر/ادمین که بتواند:

* وضعیت سامانه را بررسی کند
* Error Logها را تحلیل کند
* API Health را بررسی کند
* Database Health را بررسی کند
* Agent Logها را بررسی کند
* مشکلات کاربران را تحلیل کند
* وضعیت امنیتی سامانه را بررسی کند
* پیشنهاد رفع مشکل بدهد
* در عملیات حساس Human-in-the-loop داشته باشد

معماری احتمالی آینده:

```text
Admin
  ↓
Support / Operations Agent
  ↓
Decision Engine
  ↓
Read-only Diagnostic Tools
  ↓
System
```

اصل امنیتی:

```text
Read
 ↓
Analyze
 ↓
Recommend
 ↓
Human Approval
 ↓
Execute
```

در نسخه اول نباید Agent دسترسی مستقیم و آزاد به مواردی مانند:

```text
Shell
SQL
File System
Firewall
Permissions
Server Restart
```

داشته باشد.

**یادآوری:** وقتی پروژه وارد بحث Agentها شد، این ایده دوباره بررسی و طراحی شود.

---

# 7. ساختار فعلی پروژه

```text
dental-agent/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   │
│   ├── utils/
│   │   └── date_utils.py
│   │
│   ├── agent/
│   │   └── __init__.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── patient.py
│   │   ├── doctor.py
│   │   ├── doctor_schedule.py
│   │   ├── appointment.py
│   │   └── clinic_setting.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── patient.py
│   │   ├── doctor.py
│   │   ├── doctor_schedule.py
│   │   ├── appointment.py
│   │   └── clinic_setting.py
│   │
│   └── routers/
│       ├── __init__.py
│       ├── users.py
│       ├── patients.py
│       ├── doctors.py
│       ├── doctor_schedules.py
│       ├── appointments.py
│       └── clinic_settings.py
│
├── .env
├── .gitignore
├── requirements.txt
├── dental_agent.db
└── PROJECT_STATUS.md
```

---

# 8. Database

Database فعلی:

```text
SQLite
```

Connection:

```text
sqlite+aiosqlite:///./dental_agent.db
```

SQLAlchemy به صورت Async استفاده شده است.

---

# 9. Models فعلی

## User

```text
users
```

فیلدها:

```text
id
full_name
phone
password_hash
role
is_active
```

---

## Patient

```text
patients
```

فیلدها:

```text
id
national_id
full_name
phone
```

`national_id`:

* Unique
* Indexed

---

## Doctor

```text
doctors
```

فیلدها:

```text
id
full_name
specialty
phone
is_active
```

---

## DoctorSchedule

```text
doctor_schedules
```

فیلدها:

```text
id
doctor_id
day_of_week
start_time
end_time
slot_duration_minutes
is_active
```

Mapping فعلی:

```text
0 = Saturday
1 = Sunday
2 = Monday
3 = Tuesday
4 = Wednesday
5 = Thursday
6 = Friday
```

---

## Appointment

```text
appointments
```

فیلدها:

```text
id
patient_id
doctor_id
appointment_time
status
reason
```

وضعیت فعلی:

```text
scheduled
```

وضعیت‌های آینده می‌توانند شامل مواردی مانند:

```text
scheduled
cancelled
completed
no_show
```

باشند.

---

## ClinicSetting

```text
clinic_settings
```

فیلدها:

```text
id
max_appointments_per_day
max_appointments_per_week
max_appointments_per_month
```

مقدار `0` به معنی:

```text
No Limit
```

است.

فعلاً فقط یک تنظیم کلینیک وجود دارد:

```text
id = 1
```

معماری فعلی Single Clinic است.

در آینده در صورت نیاز می‌توان `clinic_id` اضافه کرد.

---

# 10. APIهای فعلی

## Users

```text
POST /users/
```

ایجاد User.

Password با Argon2 Hash می‌شود.

فعلاً CRUD کامل Users پیاده نشده است.

---

# 11. Patients API

CRUD فعلی:

```text
POST   /patients/
GET    /patients/
GET    /patients/{patient_id}
PUT    /patients/{patient_id}
DELETE /patients/{patient_id}
```

Validation:

* بررسی وجود Patient
* جلوگیری از Duplicate National ID
* HTTP 409 برای National ID تکراری

---

# 12. Doctors API

فعلاً:

```text
POST /doctors/
```

پیاده شده است.

CRUD کامل Doctor هنوز باید تکمیل شود.

---

# 13. Doctor Schedule API

CRUD پیاده شده:

```text
POST   /doctor-schedules/
GET    /doctor-schedules/{doctor_id}
PUT    /doctor-schedules/{schedule_id}
DELETE /doctor-schedules/{schedule_id}
```

هنگام ایجاد Schedule:

* وجود Doctor بررسی می‌شود.

---

# 14. Appointment API

## Create

```text
POST /appointments/
```

در هنگام ایجاد نوبت موارد زیر بررسی می‌شوند:

1. وجود بیمار
2. وجود پزشک
3. فعال بودن پزشک
4. معتبر بودن تاریخ جلالی
5. معتبر بودن ساعت
6. وجود Schedule برای پزشک
7. معتبر بودن Slot
8. جلوگیری از Double Booking
9. محدودیت روزانه بیمار
10. محدودیت هفتگی بیمار
11. محدودیت ماهانه بیمار

---

## Patient Appointments

```text
GET /appointments/patient/{patient_id}
```

لیست نوبت‌های بیمار را بر اساس تاریخ مرتب می‌کند.

تاریخ و ساعت در Response به صورت جلالی برگردانده می‌شوند.

---

## Available Slots

```text
GET /appointments/available-slots/
```

پارامترها:

```text
doctor_id
appointment_date
```

نمونه:

```text
doctor_id=1
appointment_date=1405/07/13
```

خروجی نمونه:

```json
{
  "doctor_id": 1,
  "date": "1405/07/13",
  "available_slots": [
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "12:00",
    "12:30"
  ]
}
```

---

# 15. Business Rules مربوط به Appointment

## Slot Generation

Slotها بر اساس:

```text
start_time
end_time
slot_duration_minutes
```

ساخته می‌شوند.

مثلاً:

```text
09:00
09:30
10:00
10:30
...
```

---

## Double Booking

سیستم بررسی می‌کند که یک Doctor در یک زمان مشخص نوبت فعال دیگری نداشته باشد.

در صورت وجود:

```text
HTTP 409
```

پیام فعلی:

```text
این زمان قبلاً برای پزشک رزرو شده است.
```

---

# 16. Patient Appointment Limits

سه محدودیت قابل تنظیم هستند:

```text
Daily
Weekly
Monthly
```

مقدار:

```text
0 = بدون محدودیت
```

---

## Daily Limit

تابع:

```text
check_patient_appointment_limits()
```

نوبت‌های فعال بیمار را در همان روز می‌شمارد.

تست انجام شده و موفق بوده است.

پیام فعلی:

```text
تعداد نوبت‌های فعال این بیمار در این روز به حد مجاز رسیده است.
```

---

## Weekly Limit

محدودیت هفتگی نیز پیاده شده و تست موفق بوده است.

پیام فعلی:

```text
تعداد نوبت‌های فعال این بیمار در این هفته به حد مجاز رسیده است.
```

---

## Monthly Limit

محدودیت ماهانه نیز پیاده شده و تست موفق بوده است.

پیام فعلی:

```text
تعداد نوبت‌های فعال این بیمار در این ماه به حد مجاز رسیده است.
```

---

# 17. تست‌های انجام‌شده

تست‌های زیر با Swagger انجام شده‌اند.

## Test 1 — Valid Slot

یک Slot معتبر با موفقیت رزرو شد.

نتیجه:

```text
200
```

---

## Test 2 — Invalid Slot

مثلاً:

```text
10:15
```

که Slot معتبر نبود.

نتیجه:

```text
400
```

---

## Test 3 — Double Booking

رزرو زمان قبلاً رزرو شده.

نتیجه:

```text
409
```

پیام:

```text
این زمان قبلاً برای پزشک رزرو شده است.
```

---

## Test 4 — Daily Limit

تنظیم:

```text
max_appointments_per_day = 1
```

تلاش برای رزرو دوم در همان روز.

نتیجه:

```text
409
```

پیام:

```text
تعداد نوبت‌های فعال این بیمار در این روز به حد مجاز رسیده است.
```

---

## Test 5 — Weekly Limit

تنظیم:

```text
max_appointments_per_day = 0
max_appointments_per_week = 2
max_appointments_per_month = 4
```

دو نوبت فعال برای بیمار ایجاد شد.

تلاش برای نوبت سوم در همان هفته:

```text
409
```

پیام:

```text
تعداد نوبت‌های فعال این بیمار در این هفته به حد مجاز رسیده است.
```

---

## Test 6 — Monthly Limit

تنظیم:

```text
max_appointments_per_day = 0
max_appointments_per_week = 0
max_appointments_per_month = 2
```

با وجود دو نوبت فعال، تلاش برای نوبت سوم:

```text
409
```

پیام:

```text
تعداد نوبت‌های فعال این بیمار در این ماه به حد مجاز رسیده است.
```

---

# 18. داده‌های تست فعلی

Patient 3:

```text
ID: 3
نام: بیمار نمونهٔ ساختگی
National ID: 0000000000 (نمونهٔ غیرواقعی)
Phone: 09000000000 (شمارهٔ نمونهٔ غیرواقعی)
```

نوبت‌های فعلی ثبت‌شده برای Patient 3:

```text
ID 5
1405/07/12
09:00
```

```text
ID 6
1405/07/13
09:00
```

```text
ID 7
1405/07/13
09:30
```

این داده‌ها صرفاً داده‌های تست هستند.

---

# 19. Doctor Scheduleهای تست

Doctor:

```text
doctor_id = 1
```

Schedule شنبه:

```text
day_of_week = 0
09:00 - 13:00
30 minutes
```

Schedule یکشنبه:

```text
day_of_week = 1
09:00 - 13:00
30 minutes
```

---

# 20. Clinic Settings فعلی

آخرین تنظیمی که برای تست اعمال شده:

```json
{
  "id": 1,
  "max_appointments_per_day": 0,
  "max_appointments_per_week": 0,
  "max_appointments_per_month": 2
}
```

این مقدار تستی است.

قبل از ادامه توسعه باید مشخص شود تنظیمات مناسب Development چه باشند.

---

# 21. تاریخ جلالی

Utility فعلی:

```text
app/utils/date_utils.py
```

توابع:

```text
jalali_to_gregorian()
gregorian_to_jalali()
```

Backend تاریخ ورودی را به صورت:

```text
YYYY/MM/DD
```

دریافت می‌کند.

مثال:

```text
1405/07/13
```

و برای Database به Gregorian datetime تبدیل می‌کند.

---

# 22. نکته مهم درباره Week و Month

در پیاده‌سازی فعلی، محاسبه Week و Month با `datetime.date` میلادی انجام می‌شود.

تابع فعلی Week:

```python
def get_week_start(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())
```

یعنی هفته از Monday شروع می‌شود.

برای یک سامانه ایرانی احتمالاً Business Rule مناسب‌تر:

```text
Saturday → Friday
```

است.

همچنین Month فعلی بر اساس ماه Gregorian محاسبه می‌شود.

**این موضوع هنوز نهایی نشده است.**

قبل از Finalizing Appointment Rules باید تصمیم بگیریم که:

* Weekly Limit بر اساس هفته شمسی باشد یا میلادی
* Monthly Limit بر اساس ماه شمسی باشد یا میلادی

پیشنهاد فعلی برای Business Application ایرانی:

```text
Week = Saturday → Friday
Month = Persian/Jalali Month
```

اما قبل از تغییر، باید معماری Date/Time یک‌بار اصولی طراحی شود.

---

# 23. Error Handling — تصمیم معماری جدید

کاربر پیشنهاد داده است که برای خطاها Error Code یکتا داشته باشیم.

این تصمیم تأیید شده است، اما هنوز **پیاده‌سازی نشده است.**

هدف:

به جای اینکه سیستم فقط این را برگرداند:

```json
{
  "detail": "این زمان قبلاً برای پزشک رزرو شده است."
}
```

ساختار آینده می‌تواند چیزی شبیه:

```json
{
  "error": {
    "code": "APPOINTMENT_SLOT_BOOKED",
    "message": "این زمان قبلاً برای پزشک رزرو شده است.",
    "details": {},
    "request_id": "..."
  }
}
```

باشد.

---

# 24. اصول Error Contract

Error System باید برای کل پروژه طراحی شود، نه فقط Appointment.

اصول:

## 1. HTTP Status و Error Code جدا باشند

مثلاً چند خطای مختلف می‌توانند:

```text
HTTP 409
```

باشند:

```text
APPOINTMENT_SLOT_BOOKED
APPOINTMENT_DAILY_LIMIT
APPOINTMENT_WEEKLY_LIMIT
APPOINTMENT_MONTHLY_LIMIT
```

---

## 2. Error Code باید پایدار باشد

Frontend و Agent نباید بر اساس متن فارسی تصمیم بگیرند.

مثلاً:

```text
APPOINTMENT_SLOT_BOOKED
```

به جای بررسی:

```text
"این زمان قبلاً برای پزشک رزرو شده است."
```

---

## 3. Message قابل تغییر باشد

Message برای User/Frontend است.

تغییر متن نباید منطق سیستم را خراب کند.

---

## 4. Details

در صورت نیاز اطلاعات ساختاریافته برگردد.

مثلاً:

```json
{
  "limit": 2,
  "current_count": 2
}
```

---

## 5. Request ID

برای Trace کردن درخواست‌ها و Debugging در نظر گرفته شود.

---

## 6. Internal Errors

Stack Trace و جزئیات حساس نباید به Client داده شوند.

مثلاً:

```text
INTERNAL_SERVER_ERROR
```

به کاربر نشان داده شود و جزئیات واقعی در Server Log ذخیره شود.

---

# 25. Error Catalog پیشنهادی

این Catalog هنوز نهایی نشده است و باید قبل از پیاده‌سازی بررسی شود.

## Appointment

```text
APPOINTMENT_SLOT_BOOKED
APPOINTMENT_SLOT_INVALID
APPOINTMENT_DOCTOR_NOT_WORKING
APPOINTMENT_DAILY_LIMIT
APPOINTMENT_WEEKLY_LIMIT
APPOINTMENT_MONTHLY_LIMIT
APPOINTMENT_NOT_FOUND
APPOINTMENT_ALREADY_CANCELLED
APPOINTMENT_ALREADY_COMPLETED
APPOINTMENT_CANCEL_NOT_ALLOWED
APPOINTMENT_RESCHEDULE_NOT_ALLOWED
```

## Patient

```text
PATIENT_NOT_FOUND
PATIENT_DUPLICATE_NATIONAL_ID
PATIENT_INVALID_DATA
```

## Doctor

```text
DOCTOR_NOT_FOUND
DOCTOR_INACTIVE
DOCTOR_INVALID_SCHEDULE
```

## Authentication

آینده:

```text
AUTH_INVALID_CREDENTIALS
AUTH_ACCOUNT_INACTIVE
AUTH_ACCOUNT_LOCKED
AUTH_TOKEN_INVALID
AUTH_TOKEN_EXPIRED
AUTH_2FA_REQUIRED
AUTH_2FA_INVALID
```

## Authorization

آینده:

```text
AUTHZ_FORBIDDEN
AUTHZ_INSUFFICIENT_PERMISSION
```

## Agent

آینده:

```text
AGENT_TOOL_NOT_ALLOWED
AGENT_TOOL_TIMEOUT
AGENT_TOOL_FAILED
AGENT_ACTION_REQUIRES_HUMAN
AGENT_CONTEXT_INVALID
```

## System

آینده:

```text
INTERNAL_SERVER_ERROR
DATABASE_ERROR
DATABASE_TIMEOUT
SERVICE_UNAVAILABLE
```

این لیست قبل از پیاده‌سازی باید بازبینی شود.

---

# 26. Security Requirements

کاربر تأکید کرده است که امنیت باید در Backend واقعی باشد و فقط به UI محدود نشود.

اصل:

> Frontend قابل اعتماد نیست.

تمام APIهای حساس باید Backend Validation و Authorization داشته باشند.

موارد موردنیاز:

* Authentication
* Authorization
* RBAC
* Permission checks
* Ownership checks
* Input validation
* ID manipulation protection
* Password security
* Session/token security
* Rate limiting در نقاط لازم
* Audit Log
* Agent Tool Permission
* Human approval برای عملیات حساس
* File access control
* Protection against unauthorized patient data access

---

# 27. Agent Security

Agent نباید Backend Validation را دور بزند.

مثلاً:

```text
book_appointment()
```

باید همان قوانین API معمولی را رعایت کند:

```text
Patient exists?
Doctor exists?
Doctor active?
Valid slot?
Double booking?
Daily limit?
Weekly limit?
Monthly limit?
Permission?
```

Agent فقط یک مسیر دیگر برای استفاده از Business Logic است.

---

# 28. Authentication

هنوز پیاده‌سازی نشده است.

هدف:

* Login
* Password
* Session/Token
* Logout
* Account status
* Account lock
* 2FA در آینده

---

# 29. RBAC

Roles پیشنهادی:

```text
patient
doctor
receptionist
admin
```

ممکن است Roleهای بیشتری در آینده اضافه شوند.

Permissionها باید قابل توسعه باشند.

مثلاً:

```text
appointments.read
appointments.create
appointments.cancel
appointments.reschedule
patients.read
patients.update
patients.notes.read
patients.notes.write
agent.use
agent.admin
audit.read
users.manage
```

---

# 30. Patient Notes / History

هنوز پیاده‌سازی نشده است.

Model آینده:

```text
patient_notes
```

هدف:

* ثبت یادداشت پزشک
* مشاهده سابقه مجاز
* ثبت زمان
* ثبت نویسنده
* دسترسی محدود

این بخش باید از نظر Permission جدی طراحی شود.

---

# 31. FAQ

هنوز پیاده‌سازی نشده است.

Model آینده:

```text
faqs
```

Tool:

```text
search_faq()
```

FAQ باید منبع اصلی پاسخ‌های عمومی Agent باشد.

---

# 32. Agent Conversation

هنوز پیاده‌سازی نشده است.

Modelهای آینده:

```text
agent_conversations
agent_messages
agent_tool_calls
```

هدف ثبت:

* Conversation
* User message
* Agent response
* Tool call
* Tool result
* Timestamp
* Error
* Decision
* احتمالا token/cost metadata در آینده

---

# 33. Audit Log

هنوز پیاده‌سازی نشده است.

Model آینده:

```text
audit_logs
```

اطلاعات احتمالی:

```text
id
timestamp
user_id
action
entity_type
entity_id
result
ip
metadata
```

Audit Log برای:

* User actions
* Patient changes
* Appointment actions
* Document/record changes
* Permission changes
* Agent Tool Calls
* Security events

اهمیت زیادی دارد.

---

# 34. CRUDهای باقی‌مانده

## Users

باید تکمیل شود:

```text
GET
PUT
DELETE / deactivate
Reset Password
```

---

## Doctors

باید تکمیل شود:

```text
GET
GET by ID
PUT
DELETE / deactivate
```

---

## Appointments

باید اضافه شود:

```text
GET /appointments/{id}
POST /appointments/{id}/cancel
POST /appointments/{id}/reschedule
```

همچنین وضعیت‌های Appointment باید اصولی طراحی شوند.

---

# 35. Appointment Cancellation

هنوز پیاده‌سازی نشده.

باید Business Rule مشخص شود:

* چه کسی می‌تواند Cancel کند؟
* بیمار تا چه زمانی می‌تواند Cancel کند؟
* پزشک می‌تواند Cancel کند؟
* Receptionist؟
* Admin؟
* Cancelled appointment در Limitها شمرده شود یا نه؟

در حال حاضر Limitها فقط:

```text
status == "scheduled"
```

را شمارش می‌کنند.

این رفتار باید حفظ یا اصلاح شود بر اساس Business Rules نهایی.

---

# 36. Reschedule

هنوز پیاده‌سازی نشده.

باید تمام Validationهای Create Appointment را مجدداً انجام دهد.

یعنی Reschedule نباید بتواند:

* Double Booking ایجاد کند
* Slot نامعتبر انتخاب کند
* محدودیت‌های بیمار را دور بزند
* Doctor inactive را استفاده کند

---

# 37. Frontend

هنوز شروع نشده است.

Stack پیشنهادی:

```text
Jinja2
HTMX
CSS
JavaScript در حد نیاز
```

هدف:

* ساده
* قابل توسعه
* سریع
* بدون SPA سنگین در نسخه اول

---

# 38. UI بخش بیمار

صفحات آینده:

```text
Login
Dashboard
My Appointments
Book Appointment
Appointment Details
Chat with Agent
Profile
FAQ
```

---

# 39. UI بخش Doctor

صفحات آینده:

```text
Dashboard
Today's Appointments
Patient History
Notes
Schedule
```

---

# 40. UI بخش Receptionist

صفحات آینده:

```text
Dashboard
Patients
Appointments
Calendar
Doctor Schedule
Appointment Management
```

---

# 41. UI بخش Admin

صفحات آینده:

```text
Dashboard
Users
Roles
Permissions
Doctors
Schedules
Clinic Settings
FAQs
Audit Logs
Agent Logs
System Health
```

---

# 42. Agent UI

هدف:

یک Chat UI داخل سامانه.

نمونه:

```text
بیمار:
برای فردا وقت خالی دارید؟

Agent:
بله، برای دکتر ... ساعت‌های زیر آزاد است:

09:00
10:30
11:00

کدام ساعت را انتخاب می‌کنید؟
```

Agent باید Tool Calling واقعی داشته باشد.

---

# 43. Laya

Laya در پروژه به عنوان:

**Decision Engine**

در نظر گرفته شده است.

Laya نباید به عنوان LLM تلقی شود.

وظیفه:

* Decision
* Rule/Choice
* Score
* Yes/No
* تصمیم‌گیری کنترل‌شده

LangChain مسئول بخش Agent/LLM است.

معماری:

```text
LLM / LangChain
       ↓
Decision Context
       ↓
Laya
       ↓
Decision
       ↓
Tool / Human Handoff
```

پیاده‌سازی Laya هنوز شروع نشده است.

---

# 44. LangChain

LangChain فقط در بخش Agent استفاده شود.

نباید کل Backend به LangChain وابسته شود.

Business Logic باید مستقل باشد.

مثلاً:

```text
AppointmentService
```

می‌تواند بدون LangChain هم کار کند.

بعد Tool:

```text
book_appointment
```

از همان Service استفاده کند.

---

# 45. Service Layer

در حال حاضر بخش زیادی از Business Logic داخل Routerهاست.

قبل از Agent Tools بهتر است Business Logic مهم به Service Layer منتقل شود.

ساختار پیشنهادی:

```text
app/
├── services/
│   ├── appointment_service.py
│   ├── patient_service.py
│   ├── doctor_service.py
│   ├── auth_service.py
│   └── ...
```

هدف:

```text
Router
  ↓
Service
  ↓
Repository / SQLAlchemy
```

و:

```text
Agent Tool
  ↓
Service
  ↓
Repository / SQLAlchemy
```

این موضوع برای جلوگیری از Duplicate Logic مهم است.

---

# 46. Repository Layer

فعلاً اجباری نیست.

اگر پروژه بیش از حد پیچیده نشود، می‌توان ابتدا Service Layer را ایجاد کرد.

نباید Architecture را بدون نیاز بیش از حد پیچیده کنیم.

---

# 47. Configuration

`.env` برای تنظیمات پروژه در نظر گرفته شده است.

موارد آینده:

```text
DATABASE_URL
SECRET_KEY
JWT settings
LLM provider
OLLAMA_URL
MODEL_NAME
ENVIRONMENT
DEBUG
```

Secretها نباید داخل Git قرار بگیرند.

---

# 48. Database Migration

در حال حاضر:

```text
Base.metadata.create_all()
```

استفاده می‌شود.

برای Development فعلی قابل قبول است.

اما قبل از نسخه جدی پروژه باید Migration System مثل:

```text
Alembic
```

بررسی و اضافه شود.

---

# 49. Testing

فعلاً تست‌ها دستی و از طریق Swagger انجام شده‌اند.

در ادامه باید:

```text
pytest
pytest-asyncio
```

بررسی شوند.

حداقل تست‌ها:

```text
Patient CRUD
Doctor CRUD
Schedule CRUD
Appointment creation
Invalid slot
Double booking
Daily limit
Weekly limit
Monthly limit
Cancel
Reschedule
Authentication
Authorization
Agent tools
```

---

# 50. تست‌های مهم آینده

باید Edge Caseها نیز تست شوند:

## Appointment

* بیمار وجود ندارد
* پزشک وجود ندارد
* پزشک غیرفعال است
* Schedule وجود ندارد
* Slot خارج از Schedule
* Slot بین دو Slot معتبر
* Double booking
* Limit reached
* Cancelled appointment
* Reschedule
* Past appointment
* Invalid date
* Invalid time

---

# 51. امنیت Agent

Agent باید در برابر موارد زیر مقاوم باشد:

* Prompt Injection
* Tool Injection
* Unauthorized Tool Calls
* Data Leakage
* Cross-patient access
* Privilege Escalation
* Hallucinated actions
* Tool argument manipulation

اصل مهم:

**LLM نباید Authority باشد.**

Authority باید در:

```text
Backend
Permission Layer
Business Rules
Tool Validation
```

باشد.

---

# 52. MCP

استفاده از MCP در آینده ممکن است بررسی شود.

اما پروژه نباید به MCP داخل ChatGPT وابسته باشد.

به دلیل محدودیت‌های محیط ChatGPT/Free:

```text
Project
≠
ChatGPT MCP dependency
```

اگر MCP اضافه شود باید مستقل و قابل اجرای خارج از ChatGPT طراحی شود.

---

# 53. Scope فعلی پروژه

## داخل Scope

```text
Authentication
RBAC
Patient Management
Doctor Management
Doctor Schedule
Appointment Management
FAQ
Agent Chat
Agent Tools
Tool Logs
Audit Logs
Human Handoff
Error Handling
Admin Dashboard
Basic Monitoring
```

## فعلاً خارج از Scope

```text
Payments
Insurance
Prescription
Diagnosis
Treatment Recommendation
SMS
Mobile App
Multiple Clinics
OCR
Complex Medical Records
Advanced Hospital Integration
```

---

# 54. نکته مهم درباره Medical AI

Agent نباید:

* Diagnosis انجام دهد
* Treatment recommendation بدهد
* Prescription تولید کند
* جای پزشک تصمیم‌گیری کند

Agent فعلاً برای:

```text
Scheduling
FAQ
Patient-specific permitted information
Administrative operations
```

است.

---

# 55. اصول توسعه پروژه

## اصل 1

Frontend را Trust نکن.

## اصل 2

Business Rule فقط در Backend معتبر است.

## اصل 3

Agent نمی‌تواند Backend Rules را دور بزند.

## اصل 4

Permission باید در Backend بررسی شود.

## اصل 5

Sensitive Operations باید قابل Audit باشند.

## اصل 6

Error Handling باید استاندارد باشد.

## اصل 7

Agent باید Toolهای محدود و مشخص داشته باشد.

## اصل 8

LLM نباید Authority باشد.

## اصل 9

عملیات حساس باید Human-in-the-loop داشته باشند.

## اصل 10

از Overengineering جلوگیری شود.

---

# 56. وضعیت فعلی Error Handling

### پیاده شده

* HTTP Status مناسب برای برخی خطاها
* HTTP 400
* HTTP 404
* HTTP 409
* HTTP 422 از FastAPI/Pydantic

### هنوز پیاده نشده

* Global Exception Handler
* Error Code
* Error Catalog
* Standard Error Response
* Request ID
* Error Correlation
* Internal Error Logging

---

# 57. کار بعدی پیشنهادی

قبل از ادامه Appointment API:

## مرحله 1

طراحی نهایی Error Contract.

## مرحله 2

طراحی Error Catalog.

## مرحله 3

Global Error Handler در FastAPI.

## مرحله 4

تبدیل Errorهای فعلی به Error Code.

## مرحله 5

اضافه کردن Request ID.

## مرحله 6

ثبت Errorها در Log.

بعد:

```text
Appointment Cancel
        ↓
Appointment Reschedule
        ↓
Doctor CRUD
        ↓
Patient Notes
        ↓
FAQ
        ↓
Authentication
        ↓
Authorization / RBAC
        ↓
Audit Log
        ↓
Service Layer
        ↓
Agent Tools
        ↓
LangChain
        ↓
Laya
```

---

# 58. نکته مهم درباره Error Catalog

قبل از پیاده‌سازی Error System، باید این موارد مشخص شوند:

* Naming Convention
* HTTP Status Mapping
* Retryable / Non-retryable
* Agent Action
* User-facing Message
* Internal Message
* Details Schema
* Request ID
* Logging Level
* Security Sensitivity

نباید فقط چند Error Code سریع ایجاد شود.

هدف این است که بعداً مجبور به Refactor گسترده نشویم.

---

# 59. Development Workflow

کاربر ترجیح می‌دهد:

1. یک مرحله کوچک انجام شود.
2. نتیجه تست شود.
3. سپس مرحله بعدی شروع شود.

هنگام تغییر کد:

**کد را به صورت تکه‌های متعدد نده.**

اگر لازم است یک فایل تغییر کند، ترجیح کاربر این است که:

* فایل کامل ارائه شود
* جایگزین فایل فعلی شود
* سپس تست انجام شود

از ارائه چند Snippet پراکنده برای یک فایل خودداری شود.

---

# 60. قانون مهم برای Codex

قبل از تغییر کد:

1. وضعیت فعلی Repository را بررسی کن.
2. فایل‌های مرتبط را بخوان.
3. تغییرات موجود را حفظ کن.
4. چیزی را بدون دلیل حذف نکن.
5. Business Rules فعلی را نشکن.
6. تست‌های قبلی را در نظر بگیر.
7. بعد از تغییر، تست مناسب پیشنهاد/اجرا کن.

اگر تصمیم معماری جدیدی لازم است، قبل از پیاده‌سازی توضیح داده شود.

---

# 61. Current Known Issues / Decisions To Review

## 1. Persian Week

فعلاً Week با Monday-start Gregorian محاسبه می‌شود.

باید بررسی شود که به Saturday-start تغییر کند.

## 2. Persian Month

فعلاً Month Gregorian است.

باید بررسی شود که Month Jalali شود.

## 3. Error Contract

هنوز طراحی و پیاده‌سازی نشده.

## 4. Service Layer

Business Logic هنوز در Routerها قرار دارد.

قبل از Agent Tools بهتر است Refactor شود.

## 5. Authentication

هنوز پیاده نشده.

## 6. Authorization

هنوز پیاده نشده.

## 7. Appointment Cancellation

هنوز پیاده نشده.

## 8. Appointment Reschedule

هنوز پیاده نشده.

## 9. Database Migration

Alembic هنوز اضافه نشده.

## 10. Automated Tests

هنوز اضافه نشده.

---

# 62. Definition of Done برای Core Backend

قبل از ورود جدی به Agent باید حداقل موارد زیر آماده باشند:

```text
[ ] Patient CRUD
[x] Doctor Schedule CRUD
[ ] Doctor CRUD کامل
[x] Appointment Create
[x] Available Slots
[x] Double Booking Protection
[x] Daily Limit
[x] Weekly Limit
[x] Monthly Limit
[ ] Cancel Appointment
[ ] Reschedule Appointment
[ ] Standard Error Contract
[ ] Authentication
[ ] Authorization
[ ] RBAC
[ ] Patient Notes
[ ] FAQ
[ ] Audit Log
[ ] Service Layer
[ ] Automated Tests
```

---

# 63. Definition of Done برای Agent

بعد از Core Backend:

```text
[ ] Agent Conversation Model
[ ] Agent Message Model
[ ] Agent Tool Call Model
[ ] Tool Interface
[ ] Tool Permission Layer
[ ] check_available_slots
[ ] book_appointment
[ ] cancel_appointment
[ ] reschedule_appointment
[ ] get_patient_appointments
[ ] get_patient_history
[ ] search_faq
[ ] LangChain Agent
[ ] Laya Decision Engine
[ ] Tool Logging
[ ] Human Handoff
[ ] Agent Security
[ ] Prompt Injection Protection
```

---

# 64. Final Architecture Target

هدف نهایی تقریباً:

```text
                         ┌───────────────────┐
                         │       User        │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │       UI          │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │      FastAPI       │
                         └─────────┬─────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
             Normal APIs                    Agent APIs
                    │                             │
                    │                       LangChain
                    │                             │
                    │                           Laya
                    │                             │
                    │                       Agent Tools
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │   Service Layer   │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │ Permission/Rules  │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │    SQLAlchemy     │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │      Database     │
                         └───────────────────┘

Cross-cutting:
────────────────────────────────────────────────────

Authentication
Authorization
RBAC
Error Contract
Request ID
Audit Log
Agent Logs
Security
Validation
Human-in-the-loop
```

---

# 65. Immediate Next Task

**Do not start Agent implementation yet.**

اولین کار بعدی:

### طراحی اصولی Error Handling

باید ابتدا مشخص شود:

```text
Error Response Schema
Error Code Convention
Error Catalog
HTTP Status Mapping
Details Schema
Request ID
Logging Strategy
Retry Semantics
Agent Semantics
Security Classification
```

بعد پیاده‌سازی شود.

---

# 66. Important Reminder

ایده زیر فعلاً کنار گذاشته شده و نباید بدون تصمیم جدید وارد Scope فعلی شود:

**Admin / Support Monitoring Agent**

وقتی به مرحله طراحی Agentها رسیدیم، این موضوع را دوباره مطرح کن و درباره موارد زیر بحث شود:

* Monitoring
* Diagnostics
* Security Advisor
* Incident Investigation
* Read-only Diagnostic Tools
* Human Approval
* Safe Remediation
* Agent Permissions
* Auditability

---

# 67. Project Philosophy

این پروژه نباید صرفاً یک:

```text
CRUD + Chatbot
```

باشد.

هدف:

```text
Real Backend
+
Business Rules
+
Security
+
Controlled Tools
+
Agentic Architecture
+
Decision Engine
+
Auditability
+
Human Oversight
```

است.

هر قابلیت جدید باید تا حد امکان:

* کاربرد واقعی داشته باشد
* قابل دفاع در پروژه کارشناسی باشد
* قابل تست باشد
* از نظر امنیتی کنترل‌شده باشد
* با معماری Agentic پروژه هماهنگ باشد
* بدون Overengineering قابل پیاده‌سازی باشد

---

# 68. Current Project Status Summary

```text
Backend:
████████░░  ~80% Core اولیه

Database:
███████░░░  مدل‌های اصلی اولیه آماده

Appointment:
████████░░  Create + Slots + Limits آماده

Security:
██░░░░░░░░  هنوز ابتدایی

Error Handling:
██░░░░░░░░  نیازمند طراحی

Service Layer:
░░░░░░░░░░  شروع نشده

Authentication:
░░░░░░░░░░  شروع نشده

RBAC:
░░░░░░░░░░  شروع نشده

Agent:
░░░░░░░░░░  شروع نشده

LangChain:
░░░░░░░░░░  شروع نشده

Laya:
░░░░░░░░░░  شروع نشده

Frontend:
░░░░░░░░░░  شروع نشده

Automated Tests:
░░░░░░░░░░  شروع نشده
```

---

# 69. Instruction for Future Development

هر توسعه‌دهنده/Agentی که این فایل را می‌خواند باید:

1. ابتدا وضعیت فعلی پروژه را بررسی کند.
2. قبل از تغییر Architecture، تصمیم‌های این فایل را در نظر بگیرد.
3. Error Handling را قبل از زیاد شدن APIها استاندارد کند.
4. Security را فقط در Frontend پیاده نکند.
5. Agent را به Database مستقیم متصل نکند.
6. Agent Tools را از Business Rules عبور ندهد.
7. برای عملیات حساس Human-in-the-loop در نظر بگیرد.
8. از ایجاد قابلیت‌های خارج از Scope خودداری کند.
9. تست هر قابلیت را قبل از رفتن به مرحله بعد انجام دهد.
10. در صورت تغییر معماری مهم، این فایل را به‌روزرسانی کند.

---

# 70. Last Known Successful Tests

آخرین تست‌های موفق:

```text
✓ Patient creation
✓ Patient CRUD
✓ Doctor creation
✓ Doctor Schedule creation
✓ Appointment creation
✓ Jalali date conversion
✓ Valid appointment slot
✓ Invalid appointment slot rejection
✓ Double booking rejection
✓ Daily appointment limit
✓ Weekly appointment limit
✓ Monthly appointment limit
✓ Available slots endpoint
✓ Clinic settings update
```

---

# 71. Last Known Database Test Data

Patient:

```text
ID: 3
Name: بیمار نمونهٔ ساختگی
National ID: 0000000000 (نمونهٔ غیرواقعی)
Phone: 09000000000 (شمارهٔ نمونهٔ غیرواقعی)
```

Doctor:

```text
ID: 1
```

Schedules:

```text
Saturday: 09:00 - 13:00 / 30 min
Sunday:   09:00 - 13:00 / 30 min
```

Appointments for Patient 3:

```text
5 → 1405/07/12 09:00
6 → 1405/07/13 09:00
7 → 1405/07/13 09:30
```

آخرین Clinic Settings:

```text
Daily:   0
Weekly:  0
Monthly: 2
```

این داده‌ها Test Data هستند و نباید به عنوان داده واقعی بیمار در نظر گرفته شوند.

---

# END OF PROJECT STATUS
