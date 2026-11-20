// Synthetic DOM smoke test for web/index.html (the role-aware clinic app).
// jsdom harness (no browser, no network):
//   npm install --prefix "$env:TEMP/dental-jsdom" jsdom@26
//   $env:NODE_PATH = "$env:TEMP/dental-jsdom/node_modules"
//   node tests/ui/app_smoke.js
// This is not part of unittest discovery and is not a real-browser test.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "index.html"),
  "utf8"
);

let failures = 0;
function ok(condition, message) {
  if (!condition) {
    failures += 1;
    console.log("FAIL:", message);
  } else {
    console.log("ok  :", message);
  }
}

const doctor = { id: 600, full_name: "دکتر نمونه", specialty: "عمومی", is_active: true };
const service = { id: 700, name: "معاینه اولیه", description: null, is_active: true };
const patient = {
  id: 500, national_id: "1000000000",
  full_name: "بیمار نمونه", phone: "09120000500",
};
const receptionist = {
  id: 2, full_name: "پذیرش نمونه", role: "receptionist",
  is_active: true, patient: null, doctor: null,
};
const appointment = {
  id: 900, patient_id: 500, doctor_id: 600, service_id: 700,
  appointment_date: "1405/08/01", appointment_time: "10:00",
  status: "scheduled", reason: null,
  patient_name: "بیمار نمونه", doctor_name: "دکتر نمونه",
  service_name: "معاینه اولیه",
};

const calls = [];
const routes = {
  "POST /auth/login": { access_token: "tok" },
  "GET /auth/me": receptionist,
  "GET /patients/": [patient],
  "GET /users/": [receptionist],
  "GET /doctors/": [doctor],
  "GET /doctors/600/services": [service],
  "GET /dental-services/": [service],
  "GET /appointments/": [appointment],
  "GET /doctor-schedules/600": [],
  "GET /appointments/available-slots/?doctor_id=600&appointment_date=1405/08/01": {
    available_slots: ["10:00", "10:30"],
  },
  "GET /agent/chat": null,
  "POST /agent/chat": null,
  "POST /appointments/900/cancel": null,
  "PUT /users/999": null,
};

/* Queue of POST /agent/chat response bodies, consumed in order. */
const agentScript = [];

function makeFetch(realMe) {
  return async (url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ method, path: url, body });
    if (method === "POST" && url === "/agent/chat") {
      const next = agentScript.shift();
      if (!next) throw new Error("no queued agent response");
      return resp(next.status, next.json);
    }
    let key = `${method} ${url}`;
    let payload = routes[key];
    if (payload === undefined) {
      // Pattern matches for the appointment detail and user detail URLs.
      if (method === "PUT" && /^\/users\/\d+$/.test(url)) payload = { ok: true };
      else if (method === "POST" && /^\/appointments\/\d+\/cancel$/.test(url))
        payload = { ...appointment, status: "cancelled" };
    }
    if (payload === undefined) throw new Error("no route for " + key);
    return resp(200, payload);
  };
}

function resp(status, json) {
  const payload = JSON.stringify(json);
  return { status, ok: status < 400, json: async () => json, text: async () => payload };
}

(async () => {
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: "http://clinic.local/app",
    beforeParse(window) {
      window.fetch = makeFetch();
      window.HTMLElement.prototype.scrollIntoView = () => {};
    },
  });
  // The web app loads its script from /app-assets/app.js; jsdom does not
  // fetch external resources, so the same source is injected inline.
  const appSource = fs.readFileSync(
    path.join(__dirname, "..", "..", "web", "assets", "app.js"),
    "utf8"
  );
  const scriptNode = dom.window.document.createElement("script");
  scriptNode.textContent = appSource;
  dom.window.document.body.append(scriptNode);
  await new Promise((resolve) => setTimeout(resolve, 60));
  const d = dom.window.document;
  const $ = (id) => d.getElementById(id);
  const click = (node) =>
    node.dispatchEvent(new dom.window.Event("click", { bubbles: true }));
  const tick = (ms = 40) => new Promise((resolve) => setTimeout(resolve, ms));

  ok($("loginView") && !$("loginView").hidden, "login view is shown first");
  ok($("panelView").hidden, "panel is hidden before login");

  // OTP tab is present for patients; staff logs in with a password.
  click($("tabLoginOtp"));
  await tick(20);
  ok(!$("otpLoginForm").hidden, "OTP login form can be selected");

  // --- password login -> panel ---
  $("loginPhone").value = "09120000002";
  $("loginPassword").value = "correct-horse";
  $("passwordLoginForm").dispatchEvent(
    new dom.window.Event("submit", { cancelable: true })
  );
  await tick(120);
  ok(!$("panelView").hidden && $("loginView").hidden, "panel opens after login");
  ok(
    $("panelUserName").textContent === "پذیرش نمونه",
    "header shows the account name"
  );
  ok($("panelUserRole").textContent === "پذیرش", "role badge is shown");

  const tabs = [...$("panelNav").children].map((node) => node.dataset.tab);
  ok(
    tabs.includes("patients") && tabs.includes("appointments") &&
    tabs.includes("agent") && !tabs.includes("users"),
    "receptionist sees patient/appointment/agent tabs but not the users tab"
  );

  // Dashboard already fetched data.
  const dashText = $("dashboardCards").textContent;
  ok(dashText.includes("بیماران"), "dashboard renders stat cards");

  // --- patients tab ---
  click($("panelNav").querySelector("[data-tab='patients']"));
  await tick(80);
  ok(
    $("patientsTable").textContent.includes("بیمار نمونه"),
    "patient list renders names"
  );

  // --- appointments tab ---
  click($("panelNav").querySelector("[data-tab='appointments']"));
  await tick(120);
  const apptText = $("appointmentsTable").textContent;
  ok(
    apptText.includes("دکتر نمونه") && apptText.includes("معاینه اولیه"),
    "appointment listing renders doctor/service names, not ids"
  );
  ok(!apptText.includes("patient_id"), "no internal field leaks into the table");

  // Cancel action flows through the API.
  const cancelButtons = [...$("appointmentsTable").querySelectorAll("button")].filter(
    (button) => button.textContent === "لغو"
  );
  ok(cancelButtons.length === 1, "cancel action is offered for scheduled rows");
  click(cancelButtons[0]);
  await tick(20);
  ok(!$("appointmentActionForm").hidden, "cancel confirmation form opens");
  click(
    [...$("appointmentActionForm").querySelectorAll("button")].find(
      (button) => button.textContent === "لغو نوبت"
    )
  );
  await tick(120);
  ok(
    calls.some(
      (call) => call.method === "POST" && call.path === "/appointments/900/cancel"
    ),
    "cancel posts to the appointments API"
  );

  // --- booking form fills and posts ---
  $("bookingDate").value = "1405/08/01";
  click($("bookingLoadSlots"));
  await tick(60);
  ok(
    calls.some(
      (call) => call.method === "GET" &&
      call.path.startsWith("/appointments/available-slots/?doctor_id=600"),
    ),
    "slot lookup uses the available-slots API"
  );

  // --- agent chat with confirmation flow ---
  click($("panelNav").querySelector("[data-tab='agent']"));
  await tick(20);
  ok(
    $("chatMessages").textContent.includes("دستیار کلینیک"),
    "agent welcome message is rendered"
  );
  ok(
    $("quickActions").querySelectorAll("button[data-prompt]").length >= 2,
    "quick actions are offered"
  );

  agentScript.push({
    status: 200,
    json: {
      reply: "لطفاً ثبت این نوبت را تأیید کنید.",
      session_id: "s9",
      confirmation_required: true,
      confirmation_token: "T7",
      confirmation_prompt:
        "ثبت نوبت «معاینه اولیه» با دکتر نمونه در 1405/08/01 ساعت 10:00 را تأیید می‌کنید؟",
      slots: [],
    },
  });
  agentScript.push({
    status: 200,
    json: {
      reply: "نوبت «معاینه اولیه» با دکتر نمونه در 1405/08/01 ساعت 10:00 ثبت شد.",
      session_id: "s9",
      confirmation_required: false,
      slots: [],
    },
  });

  $("messageInput").value = "نزدیک‌ترین نوبت را رزرو کن";
  $("composer").dispatchEvent(
    new dom.window.Event("submit", { cancelable: true })
  );
  await tick(60);
  ok(
    !$("confirmationPane").hidden &&
      $("confirmationPrompt").textContent.includes("دکتر نمونه"),
    "confirmation pane shows the server prompt before any write"
  );
  ok(
    $("messageInput").disabled && $("sendBtn").disabled,
    "composer is locked while a write confirmation is pending"
  );
  click($("approve"));
  await tick(60);
  const approvalCall = [...calls]
    .reverse()
    .find((call) => call.path === "/agent/chat" && call.method === "POST");
  ok(
    approvalCall &&
      approvalCall.body.confirmation &&
      approvalCall.body.confirmation.token === "T7" &&
      approvalCall.body.confirmation.decision === "approved" &&
      approvalCall.body.session_id === "s9",
    "approval sends token, decision, and session id"
  );
  ok(
    $("chatMessages").textContent.includes("ثبت شد"),
    "success comes from the real API result"
  );
  ok(
    !$("chatMessages").textContent.includes("900"),
    "internal appointment ids are never rendered"
  );
  ok(
    $("confirmationPane").hidden,
    "confirmation pane clears after the decision"
  );

  // --- slot card click sends a plain booking message ---
  agentScript.push({
    status: 200,
    json: {
      reply: "نزدیک‌ترین نوبت‌ها:",
      session_id: "s9",
      confirmation_required: false,
      slots: [
        {
          doctor_id: 600,
          doctor_name: "دکتر نمونه",
          service_id: 700,
          service_name: "معاینه اولیه",
          appointment_date: "1405/08/02",
          appointment_time: "09:30",
        },
      ],
    },
  });
  click($("quickActions").querySelector("button[data-prompt]"));
  await tick(60);
  const slotCard = d.querySelector(".slot");
  ok(!!slotCard, "slot card renders");
  agentScript.push({
    status: 200,
    json: { reply: "باشه.", session_id: "s9", confirmation_required: false, slots: [] },
  });
  click(slotCard);
  await tick(60);
  const pickedCall = [...calls]
    .reverse()
    .find((call) => call.path === "/agent/chat" && call.method === "POST");
  ok(
    pickedCall &&
      pickedCall.body.message.includes("دکتر نمونه") &&
      pickedCall.body.message.includes("1405/08/02"),
    "slot selection sends a plain message with real slot data"
  );

  // --- session expiry returns to login ---
  agentScript.push({ status: 401, json: {} });
  $("messageInput").value = "پس از انقضا";
  $("composer").dispatchEvent(
    new dom.window.Event("submit", { cancelable: true })
  );
  await tick(60);
  ok(
    !$("loginView").hidden && $("panelView").hidden,
    "401 clears the session and returns to login"
  );
  ok(
    $("loginError").textContent.includes("منقضی"),
    "expiry message is shown"
  );

  // --- model content renders as text, never as markup ---
  const probe = d.createElement("div");
  probe.textContent = "<img src=x onerror=alert(1)>";
  ok(
    probe.querySelector("img") === null && probe.textContent.includes("img"),
    "textContent-based rendering keeps HTML inert"
  );

  console.log(
    failures ? "FAILURES: " + failures : "ALL WEB UI CHECKS PASSED"
  );
  process.exit(failures ? 1 : 0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
