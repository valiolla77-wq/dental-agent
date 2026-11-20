"""DEVELOPMENT-ONLY local SMS panel (simulated phone inbox).

Serves the messages that the ``fake`` SMS provider would have "delivered", so
the OTP flow can be tested end-to-end without any real SMS vendor:

- ``GET /dev/sms``            → simple RTL page polling the outbox (2s).
- ``GET /dev/sms/outbox.json``→ JSON list of simulated messages.
- ``POST /dev/sms/clear``     → clears the simulated inbox.

Fail-closed gating: every endpoint returns 404 unless the fake provider is
active, i.e. ``APP_ENV`` is development/test **and** ``OTP_PROVIDER=fake``.
In production (or any non-fake provider) the whole panel is unreachable, so a
misconfigured deployment can never leak OTP messages through it.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth.sms import fake_provider_allowed, fake_sms

router = APIRouter(prefix="/dev/sms", include_in_schema=False)

_DISCLAIMER = (
    "سامانه پیامک لوکال (فقط توسعه) — این پیام‌ها شبیه‌سازی‌شده‌اند و پیامک "
    "واقعی ارسال نمی‌شود."
)

_PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>سامانه پیامک لوکال</title>
<style>
  :root { color-scheme: light; }
  body { font-family: Tahoma, "Segoe UI", sans-serif; margin: 0;
         background: #f3f5f8; color: #1c2430; }
  header { background: #123057; color: #fff; padding: 14px 20px; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header p { margin: 4px 0 0; font-size: 12px; color: #c9d8ea; }
  main { max-width: 460px; margin: 18px auto; padding: 0 12px; }
  .toolbar { display: flex; justify-content: space-between; align-items: center;
             margin-bottom: 10px; font-size: 12px; color: #5b6673; }
  .toolbar button { font: inherit; font-size: 12px; padding: 5px 12px;
                    border: 1px solid #cfd8e3; background: #fff;
                    border-radius: 8px; cursor: pointer; }
  .toolbar button:hover { background: #eef3fa; }
  .phone { background: #123057; border-radius: 22px 22px 0 0; padding: 10px 16px;
           color: #cfe0f2; font-size: 12px; max-width: 460px; margin: 0 auto; }
  .message { background: #d9f2d0; border: 1px solid #b9dcb0; border-radius: 12px;
             padding: 10px 12px; margin: 10px 0 0; max-width: 460px; }
  .message .meta { font-size: 11px; color: #4a5a49; display: flex;
                   justify-content: space-between; gap: 8px; }
  .message .text { margin-top: 6px; font-size: 14px; line-height: 1.7;
                   word-break: break-word; }
  .empty { background: #fff; border: 1px dashed #c3cdda; color: #6b7684;
             padding: 28px 16px; text-align: center; border-radius: 12px;
             font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>📥 سامانه پیامک لوکال — اینباکس شبیه‌سازی‌شده</h1>
  <p>__DISCLAIMER__</p>
</header>
<main>
  <div class="toolbar">
    <span id="status">در حال به‌روزرسانی…</span>
    <button id="clearButton" type="button">پاک‌کردن اینباکس</button>
  </div>
  <div class="phone">📱 GSM</div>
  <div id="list"></div>
</main>
<script>
const list = document.getElementById("list");
const status = document.getElementById("status");
const emptyHTML = '<div class="empty">هنوز پیامکی نرسیده است.<br>از فرم OTP وب‌سایت یک کد خبری بگیرید.</div>';
async function refresh() {
  try {
    const r = await fetch("/dev/sms/outbox.json", { cache: "no-store" });
    if (!r.ok) { status.textContent = "پنل غیرفعال است"; return; }
    const data = await r.json();
    const items = data.messages || [];
    list.innerHTML = items.length ? "" : emptyHTML;
    for (const m of [...items].reverse()) {
      const el = document.createElement("div");
      el.className = "message";
      const meta = document.createElement("div");
      meta.className = "meta";
      const who = document.createElement("span");
      who.textContent = "گیرنده: " + m.phone;
      const age = document.createElement("span");
      age.textContent = m.age_seconds.toFixed(0) + " ثانیه پیش";
      meta.append(who, age);
      const text = document.createElement("div");
      text.className = "text";
      text.textContent = m.body;
      el.append(meta, text);
      list.append(el);
    }
    status.textContent = "آخرین به‌روزرسانی: " + new Date().toLocaleTimeString("fa-IR");
  } catch {
    status.textContent = "خطای ارتباط با سرور";
  }
}
document.getElementById("clearButton").addEventListener("click", async () => {
  await fetch("/dev/sms/clear", { method: "POST" });
  refresh();
});
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


def _panel_open() -> bool:
    return fake_provider_allowed()


@router.get("")
@router.get("/")
async def sms_panel_page() -> HTMLResponse:
    if not _panel_open():
        return HTMLResponse("Development SMS panel is unavailable.", status_code=404)
    return HTMLResponse(_PAGE.replace("__DISCLAIMER__", _DISCLAIMER))


@router.get("/outbox.json")
async def sms_panel_outbox() -> JSONResponse:
    if not _panel_open():
        return JSONResponse({"messages": []}, status_code=404)
    now = time.time()
    messages = [
        {
            "phone": str(entry["phone"]),
            "body": str(entry["body"]),
            "age_seconds": max(0.0, now - float(entry["at"])),
        }
        for entry in fake_sms.sent_messages()
    ]
    return JSONResponse({"messages": messages})


@router.post("/clear")
async def sms_panel_clear() -> JSONResponse:
    if not _panel_open():
        return JSONResponse({"cleared": False}, status_code=404)
    fake_sms.clear()
    return JSONResponse({"cleared": True})
