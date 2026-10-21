// Synthetic DOM smoke test for demo/chat.html.
// Run (jsdom is a dev-only dependency, not required by the Python app):
//   npm install --prefix "$env:TEMP/dental-jsdom" jsdom@26
//   $env:NODE_PATH = "$env:TEMP/dental-jsdom/node_modules"
//   node tests/ui/chat_smoke.js
// This is not part of unittest discovery and is not a real-browser test.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(
  path.join(__dirname, "..", "..", "demo", "chat.html"),
  "utf8"
);

const calls = [];
let script = [];

function resp(status, json) {
  return { status, ok: status < 400, json: async () => json };
}

function makeFetch() {
  return async (url, options) => {
    const body = options && options.body ? JSON.parse(options.body) : null;
    calls.push({ path: url, body });
    if (url === "/auth/otp/request") return resp(200, { dev_otp: "123456" });
    if (url === "/auth/otp/verify") return resp(200, { access_token: "tok" });
    const next = script.shift();
    if (next === "NETWORK") throw new TypeError("network down");
    if (!next) throw new Error("no queued response for " + url);
    return resp(next.status, next.json);
  };
}

const tick = (ms = 30) => new Promise((resolve) => setTimeout(resolve, ms));
let failures = 0;
function ok(condition, message) {
  if (!condition) {
    failures += 1;
    console.log("FAIL:", message);
  } else {
    console.log("ok  :", message);
  }
}

(async () => {
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = makeFetch();
      window.HTMLElement.prototype.scrollIntoView = () => {};
    },
  });
  const d = dom.window.document;
  const $ = (id) => d.getElementById(id);
  const click = (node) =>
    node.dispatchEvent(new dom.window.Event("click", { bubbles: true }));
  const chatCalls = () => calls.filter((call) => call.path === "/agent/chat");
  const send = async (text) => {
    $("messageInput").value = text;
    $("composer").dispatchEvent(
      new dom.window.Event("submit", { cancelable: true })
    );
    await tick(45);
  };
  const noticeButton = (label) =>
    [...d.querySelectorAll(".notice button")].find(
      (button) => button.textContent.trim() === label
    );

  ok($("loginView") && !$("loginView").hidden, "login view starts visible");
  click($("requestOtp"));
  await tick();
  ok($("otp").value === "123456", "dev OTP is filled from the request response");
  click($("verifyOtp"));
  await tick();
  ok($("loginView").hidden && !$("chatView").hidden, "chat opens after OTP");
  ok(
    $("messages").textContent.includes("دستیار نوبت‌دهی"),
    "welcome message rendered"
  );
  ok(
    !$("messageInput").disabled && !$("sendBtn").disabled,
    "composer is enabled"
  );

  // Normal reply through a quick action.
  script.push({
    status: 200,
    json: {
      reply: "سه نوبت پیدا شد.",
      session_id: "s1",
      confirmation_required: false,
      slots: [],
    },
  });
  click($("quickActions").querySelector("button[data-prompt]"));
  await tick(45);
  const firstChat = chatCalls()[0];
  ok(
    firstChat && firstChat.body.message.length > 0,
    "quick action sends a message"
  );
  ok($("quickActions").hidden, "quick actions hide after the first message");
  ok(
    $("messages").textContent.includes("سه نوبت پیدا شد."),
    "assistant reply is rendered"
  );

  // Network failure on a normal turn -> safe retry, no duplicated history.
  script = ["NETWORK"];
  await send("سلام");
  ok(!!noticeButton("تلاش مجدد"), "network failure offers retry");
  ok(
    $("connectionLabel").textContent === "ارتباط برقرار نیست",
    "header shows connection failure"
  );
  script = [
    {
      status: 200,
      json: { reply: "پاسخ", session_id: "s1", slots: [] },
    },
  ];
  click(noticeButton("تلاش مجدد"));
  await tick(45);
  const retried = chatCalls()[chatCalls().length - 1].body;
  ok(
    retried.message === "سلام" &&
      !(retried.history || []).some((item) => item.content === "سلام"),
    "retry resends once without duplicating the user turn in history"
  );
  ok(
    $("connectionLabel").textContent === "آماده",
    "header returns to ready after a successful retry"
  );
  ok(
    d.querySelectorAll(".message-row.user").length === 2,
    "retry did not duplicate the user bubble"
  );

  // Confirmation card and a definite 409 rejection.
  script = [
    {
      status: 200,
      json: {
        reply: "لطفاً تأیید کنید.",
        confirmation_required: true,
        confirmation_token: "T1",
        confirmation_prompt: "ثبت نوبت با دکتر نمونه را تأیید می‌کنید؟",
        session_id: "s1",
        slots: [],
      },
    },
  ];
  await send("نوبت اول را می‌خواهم.");
  ok(
    !$("confirmationPane").hidden &&
      $("confirmationPrompt").textContent.includes("دکتر نمونه"),
    "confirmation pane shows the server prompt"
  );
  ok(
    $("messageInput").disabled && $("sendBtn").disabled,
    "composer is locked while confirmation is pending"
  );
  script = [
    {
      status: 409,
      json: {
        error: { code: "AGENT_CONFIRMATION_INVALID", message: "تأیید منقضی شد." },
      },
    },
  ];
  click($("approve"));
  await tick(45);
  const approval = chatCalls()[chatCalls().length - 1].body;
  ok(
    approval.confirmation.token === "T1" &&
      approval.confirmation.decision === "approved" &&
      approval.session_id === "s1",
    "approval sends the token, decision, and session id"
  );
  ok(
    $("confirmationPane").hidden && !!noticeButton("درخواست دوباره"),
    "409 hides the card and offers a fresh request"
  );

  // Network loss during approval -> uncertain result, no token replay.
  script = [
    {
      status: 200,
      json: {
        reply: "تأیید لازم است.",
        confirmation_required: true,
        confirmation_token: "T2",
        confirmation_prompt: "ثبت نوبت دوم را تأیید می‌کنید؟",
        session_id: "s1",
        slots: [],
      },
    },
  ];
  await send("نوبت دوم را می‌خواهم.");
  const beforeApproval = chatCalls().length;
  script = ["NETWORK"];
  click($("approve"));
  await tick(45);
  ok(
    chatCalls().length === beforeApproval + 1,
    "network loss during approval sends exactly one attempt"
  );
  ok(
    d.body.textContent.includes("نتیجهٔ این تأیید مشخص نیست"),
    "uncertain-result notice is shown"
  );
  ok(
    $("confirmationPane").hidden,
    "confirmation card is cleared after uncertain result"
  );
  script = [
    {
      status: 200,
      json: { reply: "نوبتی ندارید.", session_id: "s1", slots: [] },
    },
  ];
  click(noticeButton("بررسی نوبت‌های من"));
  await tick(45);
  const followUp = chatCalls()[chatCalls().length - 1].body;
  ok(
    followUp.message === "نوبت‌های من را نشان بده." && !followUp.confirmation,
    "follow-up after uncertainty is a plain message without the old token"
  );

  // Structured slot cards render safely and become a plain booking request.
  script = [
    {
      status: 200,
      json: {
        reply: "نزدیک‌ترین نوبت‌ها:",
        session_id: "s1",
        slots: [
          {
            doctor_id: 1,
            doctor_name: "دکتر نمونه",
            service_id: 2,
            service_name: "معاینه اولیه",
            appointment_date: "1405/08/01",
            appointment_time: "09:00",
          },
          {
            doctor_id: 1,
            doctor_name: "دکتر نمونه",
            service_id: 2,
            service_name: "معاینه اولیه",
            appointment_date: "1405/08/01",
            appointment_time: "09:30",
          },
        ],
      },
    },
  ];
  await send("نزدیک‌ترین نوبت");
  const cards = d.querySelectorAll(".slot");
  ok(cards.length === 2, "two slot cards are rendered");
  ok(
    cards[0].textContent.includes("۰۹:۰۰"),
    "slot cards render Persian digits"
  );
  script = [
    {
      status: 200,
      json: { reply: "باشه.", session_id: "s1", slots: [] },
    },
  ];
  click(cards[0]);
  await tick(45);
  const picked = chatCalls()[chatCalls().length - 1].body;
  ok(
    picked.message.includes("دکتر نمونه") &&
      picked.message.includes("1405/08/01") &&
      picked.message.includes("09:00") &&
      !picked.confirmation,
    "selecting a slot sends a plain message with real slot data"
  );
  ok(
    [...d.querySelectorAll(".slot")].every((button) => button.disabled),
    "all slot cards are disabled after a selection"
  );

  // 422 -> editable input, no blind retry.
  script = [
    {
      status: 422,
      json: { error: { code: "COMMON_VALIDATION_ERROR", message: "ورودی نامعتبر" } },
    },
  ];
  await send("یک پیام خیلی طولانی");
  ok(!!noticeButton("ویرایش پیام"), "422 offers editing instead of retry");
  ok(!noticeButton("تلاش مجدد"), "422 does not offer an unsafe retry");

  // 401 -> session expired, back to login.
  script = [{ status: 401, json: {} }];
  await send("سلام دوباره");
  ok(
    !$("loginView").hidden && $("chatView").hidden,
    "401 returns to the login view"
  );
  ok(
    $("loginError").textContent.includes("منقضی"),
    "session-expiry message is shown"
  );

  console.log(
    failures ? "FAILURES: " + failures : "ALL SYNTHETIC UI CHECKS PASSED"
  );
  process.exit(failures ? 1 : 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
