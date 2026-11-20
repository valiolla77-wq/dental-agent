/* Dental clinic web app (vanilla JS, same-origin API). */
"use strict";

/* =================== state & helpers =================== */

const state = {
  token: null,
  me: null,
  sessionId: null,
  pendingConfirmation: null,
  history: [],
};

const $ = (id) => document.getElementById(id);

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

function toFa(text) {
  return String(text ?? "").replace(/\d/g, (d) => FA_DIGITS[Number(d)]);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") {
      node.textContent = value; // safe text-only rendering everywhere
    } else if (key.startsWith("on")) {
      // React-style attr names (onClick/onSubmit) map to real DOM events.
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else {
      node.setAttribute(key, value);
    }
  }
  for (const child of children) node.append(child);
  return node;
}

function notice(id, message, kind = "info") {
  const box = $(id);
  if (!box) return;
  if (!message) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  box.className = `notice ${kind}`;
  box.textContent = message; // textContent: model/user content renders as text
  box.hidden = false;
}

const ROLE_LABELS = {
  admin: "مدیر",
  receptionist: "پذیرش",
  doctor: "پزشک",
  patient: "بیمار",
};

const STATUS_LABELS = {
  scheduled: "فعال",
  cancelled: "لغوشده",
};

const DAY_LABELS = [
  "شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه",
  "چهارشنبه", "پنجشنبه", "جمعه",
];

/* =================== API client =================== */

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw { network: true, message: "ارتباط با سرور برقرار نشد." };
  }
  let payload = {};
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      payload = {};
    }
  }
  if (!response.ok) {
    const detail = payload && payload.error ? payload.error : {};
    throw {
      status: response.status,
      code: detail.code || "INTERNAL_ERROR",
      message: detail.message || "خطای نامشخص سامانه.",
    };
  }
  return payload;
}

/* =================== auth =================== */

function resetAppState() {
  state.token = null;
  state.me = null;
  state.sessionId = null;
  state.pendingConfirmation = null;
  state.history = [];
}

function showLogin(message, kind = "error") {
  $("panelView").hidden = true;
  $("loginView").hidden = false;
  notice("loginError", kind === "error" ? message : "", "error");
  notice("loginNotice", kind === "info" ? message : "", "info");
}

function enterPanel() {
  $("loginView").hidden = true;
  $("panelView").hidden = false;
  notice("loginError", "");
  notice("loginNotice", "");
  buildNavigation();
  renderChatIntro();
  activateTab("dashboard");
}

async function loginWithPassword(phone, password) {
  const data = await api("/auth/login", {
    method: "POST",
    body: { phone, password },
  });
  state.token = data.access_token;
  state.me = await api("/auth/me");
  enterPanel();
}

async function initDashboard() {
  await renderDashboard();
}

async function logout() {
  try {
    resetAppState();
  } finally {
    showLogin("");
  }
}

/* =================== navigation & role gating =================== */

function permissions() {
  const role = state.me ? state.me.role : "patient";
  return {
    patientRead: ["admin", "receptionist", "doctor"].includes(role),
    patientWrite: ["admin", "receptionist"].includes(role),
    adminOnly: role === "admin",
    staff: ["admin", "receptionist"].includes(role),
    appointmentWrite: ["admin", "receptionist"].includes(role),
    appointmentRead: ["admin", "receptionist", "doctor"].includes(role),
  };
}

function activeTabs() {
  const perms = permissions();
  const tabs = [];
  tabs.push({ id: "dashboard", label: "داشبورد" });
  if (perms.patientRead) tabs.push({ id: "patients", label: "بیماران" });
  tabs.push({ id: "appointments", label: "نوبت‌ها" });
  tabs.push({ id: "doctors", label: "پزشکان" });
  tabs.push({ id: "services", label: "خدمات" });
  if (perms.patientRead) tabs.push({ id: "schedules", label: "برنامه پزشکان" });
  if (perms.adminOnly) tabs.push({ id: "users", label: "کاربران" });
  tabs.push({ id: "agent", label: "دستیار" });
  return tabs;
}

let currentTab = null;

async function activateTab(id) {
  currentTab = id;
  for (const button of $("panelNav").children) {
    button.classList.toggle("active", button.dataset.tab === id);
  }
  for (const section of document.querySelectorAll("section[id^='tab-']")) {
    section.hidden = section.id !== `tab-${id}`;
  }
  notice("globalNotice", "");
  if (id === "dashboard") await renderDashboard();
  if (id === "appointments") await renderAppointmentsView();
  if (id === "patients") await renderPatientsView();
  if (id === "doctors") await renderDoctorsView();
  if (id === "services") await renderServicesView();
  if (id === "schedules") await renderSchedulesView();
  if (id === "users") await renderUsersView();
}

function buildNavigation() {
  const nav = $("panelNav");
  nav.textContent = "";
  for (const tab of activeTabs()) {
    const button = el("button", {
      type: "button",
      "data-tab": tab.id,
      text: tab.label,
      onClick: () => activateTab(tab.id).catch(showApiError),
    });
    nav.append(button);
  }
  $("panelUserName").textContent = state.me.full_name;
  $("panelUserRole").textContent = ROLE_LABELS[state.me.role] || state.me.role;
}

function showApiError(error) {
  if (error && error.status === 401) {
    const message = "نشست شما منقضی شده است؛ دوباره وارد شوید.";
    resetAppState();
    showLogin(message);
    return;
  }
  const message = error.message || "خطای نامشخص سامانه.";
  const box = currentTab === "agent" ? "chatNotice" : "globalNotice";
  notice(box, message, "error");
}

/* =================== dashboard =================== */

async function renderDashboard() {
  const role = state.me.role;
  const cards = [];

  if (["admin", "receptionist"].includes(role)) {
    const patients = await api("/patients/");
    cards.push({ num: toFa(patients.length), lbl: "بیماران ثبت‌شده" });
    if (permissions().adminOnly) {
      const users = await api("/users/");
      cards.push({ num: toFa(users.length), lbl: "حساب‌های سامانه" });
    }
  } else if (role === "patient" && !state.me.patient) {
    cards.push({
      num: "—",
      lbl: "پرونده‌ای به حساب شما پیوست نشده؛ با پذیرش تماس بگیرید.",
    });
  }

  const [doctors, services] = await Promise.all([
    api("/doctors/"),
    api("/dental-services/"),
  ]);
  cards.push({ num: toFa(doctors.length), lbl: "پزشکان فعال" });
  cards.push({ num: toFa(services.length), lbl: "خدمات کلینیک" });

  let appointmentRows = [];
  if (role === "patient") {
    appointmentRows = state.me.patient
      ? await api("/appointments/me").catch(() => [])
      : [];
  } else {
    appointmentRows = await api("/appointments/").catch(() => []);
  }
  appointmentRows = appointmentRows
    .filter((row) => row.status === "scheduled")
    .slice(0, 8);

  const cardsBox = $("dashboardCards");
  cardsBox.textContent = "";
  for (const card of cards) {
    cardsBox.append(
      el("div", { class: "stat-card" }, [
        el("div", { class: "num", text: card.num }),
        el("div", { class: "lbl", text: card.lbl }),
      ])
    );
  }
  renderAppointmentRows($("dashboardAppointments"), appointmentRows, false);
}

/* =================== appointments =================== */

/* Reusable "add new" button so repeated renders never duplicate controls. */
function ensureButton(id, text, onClick, beforeId) {
  let button = $(id);
  if (!button) {
    button = el("button", { class: "btn secondary", type: "button", id });
    const anchor = $(beforeId);
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(button, anchor);
    } else {
      document.body.append(button);
    }
  }
  button.textContent = text;
  button.onclick = onClick;
  button.hidden = false;
  return button;
}

function renderAppointmentRows(container, rows, withActions = false) {
  const wrap = el("div", { class: "table-wrap" });
  if (!rows.length) {
    container.textContent = "";
    container.append(el("div", { class: "empty-state", text: "نوبتی برای نمایش وجود ندارد." }));
    return;
  }
  const table = el("table");
  const thead = el("thead");
  const headRow = el("tr");
  for (const title of ["بیمار", "پزشک", "خدمت", "تاریخ", "ساعت", "وضعیت", ""]) {
    if (state.me.role === "patient" && title === "بیمار") continue;
    headRow.append(el("th", { text: title }));
  }
  thead.append(headRow);
  table.append(thead);
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    if (state.me.role !== "patient") {
      tr.append(el("td", { text: row.patient_name || "" }));
    }
    tr.append(
      el("td", { text: row.doctor_name || "" }),
      el("td", { text: row.service_name || "" }),
      el("td", { text: row.appointment_date || "" }),
      el("td", { text: row.appointment_time || "" }),
      el("td", {}, [
        el("span", {
          class: `status-badge status-${row.status}`,
          text: STATUS_LABELS[row.status] || row.status,
        }),
      ]),
    );
    if (withActions) {
      const actionsCell = el("td");
      if (row.status === "scheduled") {
        actionsCell.append(
          el("button", {
            class: "btn ghost",
            type: "button",
            text: "لغو",
            onClick: () => openCancelForm(row),
          }),
          el("button", {
            class: "btn ghost",
            type: "button",
            text: "جابه‌جایی",
            onClick: () => openRescheduleForm(row),
          })
        );
      }
      tr.append(actionsCell);
    }
    tbody.append(tr);
  }
  table.append(tbody);
  wrap.append(table);
  container.textContent = "";
  container.append(wrap);
}

async function renderAppointmentsView() {
  const perms = permissions();
  const filters = $("appointmentsFilters");
  filters.textContent = "";

  const isPatient = state.me.role === "patient";
  $("appointmentsTitle").textContent = isPatient ? "نوبت‌های من" : "نوبت‌های کلینیک";
  $("bookingCard").hidden = !perms.appointmentWrite;

  if (isPatient) {
    const rows = state.me.patient ? await api("/appointments/me").catch(() => []) : [];
    renderAppointmentRows($("appointmentsTable"), rows, true);
    return;
  }

  if (perms.appointmentWrite) {
    // The booking form needs fresh selectors and the patient datalist.
    await Promise.all([fillBookingSelectors(), renderBookingDatalist()]);
  }

  const doctorFilter = el("select", { id: "filterDoctor" });
  doctorFilter.append(el("option", { value: "", text: "همه پزشکان" }));
  const doctors = await api("/doctors/");
  for (const doctor of doctors) {
    doctorFilter.append(el("option", { value: doctor.id, text: doctor.full_name }));
  }
  if (state.me.role === "doctor") {
    doctorFilter.value = state.me.doctor ? String(state.me.doctor.id) : "";
    doctorFilter.disabled = true;
  }
  const statusFilter = el("select", { id: "filterStatus" });
  statusFilter.append(el("option", { value: "", text: "همه وضعیت‌ها" }));
  statusFilter.append(el("option", { value: "scheduled", text: "فعال" }));
  statusFilter.append(el("option", { value: "cancelled", text: "لغوشده" }));
  const dateFilter = el("input", { id: "filterDate", placeholder: "1405/08/01" });
  const loadBtn = el("button", {
    class: "btn secondary",
    type: "button",
    text: "نمایش",
    onClick: () => loadAppointments().catch(showApiError),
  });
  filters.append(doctorFilter, statusFilter, dateFilter, loadBtn);

  await loadAppointments();
}

async function loadAppointments() {
  const params = new URLSearchParams();
  const doctor = $("filterDoctor");
  const status = $("filterStatus");
  const date = $("filterDate");
  if (doctor && doctor.value) params.set("doctor_id", doctor.value);
  if (status && status.value) params.set("status", status.value);
  if (date && date.value.trim()) params.set("appointment_date", date.value.trim());
  const query = params.toString();
  const rows = await api(`/appointments/${query ? "?" + query : ""}`);
  renderAppointmentRows($("appointmentsTable"), rows, permissions().appointmentWrite);
}

function closeAppointmentActionForm() {
  const box = $("appointmentActionForm");
  box.hidden = true;
  box.textContent = "";
  box.dataset.appointmentId = "";
}

function openCancelForm(row) {
  const box = $("appointmentActionForm");
  box.dataset.appointmentId = row.id;
  box.hidden = false;
  box.textContent = "";
  box.append(
    el("p", {
      text: `لغو نوبت «${row.service_name}» با ${row.doctor_name} در تاریخ ${row.appointment_date} ساعت ${row.appointment_time} — از ${row.patient_name}؟`,
    }),
    el("div", { class: "actions-row" }, [
      el("button", {
        class: "btn danger",
        type: "button",
        text: "لغو نوبت",
        onClick: () => cancelAppointment(row).catch(showApiError),
      }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: closeAppointmentActionForm,
      }),
    ])
  );
}

async function cancelAppointment(row) {
  await api(`/appointments/${row.id}/cancel`, { method: "POST" });
  closeAppointmentActionForm();
  notice("globalNotice", `نوبت «${row.service_name}» لغو شد.`, "ok");
  await activateTab("appointments");
}

function openRescheduleForm(row) {
  const box = $("appointmentActionForm");
  box.dataset.appointmentId = row.id;
  box.hidden = false;
  box.textContent = "";
  const dateInput = el("input", { id: "rescheduleDate", placeholder: "1405/08/01" });
  const slotSelect = el("select", { id: "rescheduleSlot" });
  slotSelect.append(el("option", { value: "", text: "ابتدا ساعت‌ها را دریافت کنید" }));
  const form = el("form", { class: "stack" });
  form.append(
    el("p", {
      text: `جابه‌جایی نوبت «${row.service_name}» با ${row.doctor_name} — تاریخ و ساعت جدید:`,
    }),
    el("div", { class: "filters-row" }, [
      labelField("تاریخ جدید (جلالی)", dateInput),
      labelSelectField("ساعت جدید", slotSelect),
    ]),
    el("div", { class: "actions-row" }, [
      el("button", {
        class: "btn secondary",
        type: "button",
        text: "ساعت‌های آزاد",
        onClick: () =>
          loadRescheduleSlots(row, dateInput.value, slotSelect).catch(showApiError),
      }),
      el("button", { class: "btn", type: "submit", text: "جابه‌جایی" }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: closeAppointmentActionForm,
      }),
    ])
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    rescheduleAppointment(row, dateInput.value, slotSelect.value).catch(showApiError);
  });
  box.append(form);
}

function labelInput(text, attrs) {
  const input = el("input", attrs);
  return { input, wrap: labelWith(text, input) };
}

function labelWith(text, control, extra) {
  const wrap = el("label", { class: "field" });
  wrap.append(el("span", { text }), control);
  if (extra) wrap.append(extra);
  return wrap;
}

function labelField(text, control, extra) {
  return labelWith(text, control, extra);
}
function labelSelectField(text, control) {
  return labelWith(text, control);
}

async function loadRescheduleSlots(row, jalaliDate, slotSelect) {
  const clean = (jalaliDate || "").trim();
  if (!clean) throw { message: "تاریخ جدید را وارد کنید." };
  const data = await api(
    `/appointments/available-slots/?doctor_id=${row.doctor_id}&appointment_date=${encodeURIComponent(clean)}`
  );
  slotSelect.textContent = "";
  if (!data.available_slots.length) {
    slotSelect.append(
      el("option", { value: "", text: "ساعت آزادی برای این روز نیست" })
    );
    return;
  }
  slotSelect.append(el("option", { value: "", text: "انتخاب ساعت" }));
  for (const slot of data.available_slots) {
    slotSelect.append(el("option", { value: slot, text: slot }));
  }
}

async function rescheduleAppointment(row, jalaliDate, slotTime) {
  const cleanDate = (jalaliDate || "").trim();
  if (!cleanDate || !slotTime) throw { message: "تاریخ و ساعت جدید را انتخاب کنید." };
  const updated = await api(`/appointments/${row.id}/reschedule`, {
    method: "POST",
    body: { appointment_date: cleanDate, appointment_time: slotTime },
  });
  closeAppointmentActionForm();
  notice(
    "globalNotice",
    `نوبت «${row.service_name}» به ${updated.appointment_date} ساعت ${updated.appointment_time} منتقل شد.`,
    "ok"
  );
  await activateTab("appointments");
}

async function renderBookingDatalist() {
  const patients = await api("/patients/");
  const list = $("bookingPatientOptions");
  list.textContent = "";
  for (const patient of patients) {
    list.append(
      el("option", {
        value: `${patient.full_name} — ${patient.phone} — ${patient.national_id}`,
      })
    );
  }
}

async function fillBookingSelectors() {
  const [doctors, selected] = await Promise.all([
    api("/doctors/"),
    api("/dental-services/"),
  ]);
  const doctorSelect = $("bookingDoctor");
  doctorSelect.textContent = "";
  for (const doctor of doctors) {
    doctorSelect.append(el("option", { value: doctor.id, text: doctor.full_name }));
  }
  const serviceSelect = $("bookingService");
  serviceSelect.textContent = "";
  serviceSelect.append(el("option", { value: "", text: "انتخاب خدمت" }));
  for (const service of selected) {
    serviceSelect.append(el("option", { value: service.id, text: service.name }));
  }
}

/* =================== patients =================== */

async function renderPatientsView() {
  const perms = permissions();
  const search = $("patientSearch");
  await loadPatients(search.value.trim());
}

async function loadPatients(term) {
  const query = term ? `?search=${encodeURIComponent(term)}` : "";
  const rows = await api(`/patients/${query}`);
  const container = $("patientsTable");
  if (!rows.length) {
    container.textContent = "";
    container.append(el("div", { class: "empty-state", text: "بیماری برای نمایش وجود ندارد." }));
    return;
  }
  const table = el("table");
  const headRow = el("tr");
  for (const title of ["نام", "شماره تلفن", "کد ملی", ""]) {
    if (
      title === "کد ملی" &&
      !["admin", "receptionist"].includes(state.me.role)
    ) {
      continue;
    }
    headRow.append(el("th", { text: title }));
  }
  table.append(el("thead", {}, [headRow]));
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    tr.append(el("td", { text: row.full_name }), el("td", { text: row.phone }));
    if (["admin", "receptionist"].includes(state.me.role)) {
      tr.append(el("td", { text: row.national_id }));
    }
    const actions = el("td");
    if (permissions().patientWrite) {
      actions.append(
        el("button", {
          class: "btn ghost",
          type: "button",
          text: "ویرایش",
          onClick: () => openPatientForm(row).catch(showApiError),
        })
      );
    }
    tr.append(actions);
    tbody.append(tr);
  }
  table.append(tbody);
  container.textContent = "";
  container.append(table);

  if (permissions().patientWrite) {
    ensureButton("addPatientBtn", "ثبت بیمار جدید", () =>
      openPatientForm(null).catch(showApiError), "appointmentActionForm");
    await renderBookingDatalist();
  }
}

function openPatientForm(patient) {
  const box = $("patientForm");
  box.hidden = false;
  box.textContent = "";
  const isCreate = patient === null;
  const nameInput = el("input", {
    id: "patientName",
    value: isCreate ? "" : patient.full_name,
  });
  const phoneInput = el("input", {
    id: "patientPhone",
    inputmode: "tel",
    value: isCreate ? "" : patient.phone,
  });
  const nationalInput = el("input", {
    id: "patientNationalId",
    inputmode: "numeric",
    maxlength: "10",
  });
  const form = el("form", { class: "stack" });
  form.append(
    el("h3", {
      text: isCreate ? "ثبت بیمار جدید" : `ویرایش بیمار: ${patient.full_name}`,
    }),
    labelWith("نام و نام خانوادگی", nameInput),
    labelWith("شماره تلفن", phoneInput)
  );
  if (isCreate) form.append(labelWith("کد ملی (۱۰ رقم)", nationalInput));
  form.append(
    el("div", { class: "actions-row" }, [
      el("button", { class: "btn", type: "submit", text: "ذخیره" }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: () => {
          box.hidden = true;
          box.textContent = "";
        },
      }),
    ])
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isCreate) {
      await api("/patients/", {
        method: "POST",
        body: {
          full_name: nameInput.value.trim(),
          phone: phoneInput.value.trim(),
          national_id: nationalInput.value.trim(),
        },
      });
      notice("globalNotice", "بیمار جدید ثبت شد.", "ok");
    } else {
      await api(`/patients/${patient.id}`, {
        method: "PUT",
        body: {
          full_name: nameInput.value.trim(),
          phone: phoneInput.value.trim(),
        },
      });
      notice("globalNotice", "اطلاعات بیمار به‌روزرسانی شد.", "ok");
    }
    box.hidden = true;
    box.textContent = "";
    await activateTab("patients");
  });
  box.append(form);
}

/* =================== doctors & services =================== */

async function renderDoctorsView() {
  const perms = permissions();
  const rows = await api("/doctors/", {});
  const container = $("doctorsTable");
  const table = el("table");
  table.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "نام پزشک" }),
    el("th", { text: "تخصص" }),
    el("th", { text: "وضعیت" }),
    el("th", { text: "خدمات ارائه‌شده" }),
    ...(perms.adminOnly ? [el("th", { text: "" })] : []),
  ])]));
  const tbody = el("tbody");
  for (const row of rows) {
    let services = [];
    try {
      const list = await api(`/doctors/${row.id}/services`);
      services = list.map((service) => service.name);
    } catch (error) {
      services = [];
    }
    const tr = el("tr");
    tr.append(
      el("td", { text: row.full_name }),
      el("td", { text: row.specialty }),
      el("td", {}, [
        el("span", {
          class: `status-badge ${row.is_active ? "status-scheduled" : "status-cancelled"}`,
          text: row.is_active ? "فعال" : "غیرفعال",
        }),
      ]),
      el("td", { text: services.join("، ") || "—" })
    );
    if (perms.adminOnly) {
      const actions = el("td");
      actions.append(
        el("button", {
          class: "btn ghost",
          type: "button",
          text: "ویرایش",
          onClick: () => openDoctorForm(row).catch(showApiError),
        })
      );
      tr.append(actions);
    }
    tbody.append(tr);
  }
  table.append(tbody);
  container.textContent = "";
  container.append(table);
  if (perms.adminOnly) {
    ensureButton("addDoctorBtn", "پزشک جدید", () =>
      openDoctorForm(null).catch(showApiError), "doctorForm");
  }
}

async function openDoctorForm(doctor) {
  const box = $("doctorForm");
  box.hidden = false;
  box.textContent = "";
  const isCreate = doctor === null;
  const services = await api("/dental-services/");
  const nameInput = el("input", { value: isCreate ? "" : doctor.full_name });
  const specialtyInput = el("input", { value: isCreate ? "" : doctor.specialty });
  // The public catalog never carries the phone, so on update the admin must
  // re-enter the contact number explicitly instead of it being wiped silently.
  const phoneInput = el("input", {
    id: isCreate ? "doctorCreatePhone" : "doctorEditPhone",
    placeholder: isCreate
      ? "شماره تماس پزشک"
      : "شماره تماس پزشک (برای تغییر، دوباره بنویسید)",
  });
  const serviceBoxes = [];
  const serviceList = el("div", { class: "stack" });
  for (const service of services) {
    let selectedIds = [];
    if (!isCreate) {
      try {
        const current = await api(`/doctors/${doctor.id}/services`);
        selectedIds = current.map((service) => service.id);
      } catch (error) {
        selectedIds = [];
      }
    }
    const checkbox = el("input", {
      type: "checkbox",
      value: service.id,
      checked: selectedIds.includes(service.id) ? "checked" : null,
    });
    serviceBoxes.push(checkbox);
    serviceList.append(labelWith(service.name, checkbox));
  }
  const form = el("form", { class: "stack" });
  form.append(
    el("h3", { text: isCreate ? "پزشک جدید" : `ویرایش پزشک ${doctor.full_name}` }),
    labelWith("نام پزشک", nameInput),
    labelWith("تخصص", specialtyInput),
    labelWith("شماره تماس", phoneInput),
    el("div", {}, [el("h3", { text: "خدمات" }), serviceList]),
    el("div", { class: "actions-row" }, [
      el("button", { class: "btn", type: "submit", text: "ذخیره" }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: () => {
          box.hidden = true;
          box.textContent = "";
        },
      }),
    ])
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const service_ids = serviceBoxes
      .filter((box) => box.checked)
      .map((box) => Number(box.value));
    const phoneValue = phoneInput.value.trim();
    if (!phoneValue) {
      notice("globalNotice", "شماره تماس پزشک لازم است.", "error");
      return;
    }
    if (isCreate) {
      await api("/doctors/", {
        method: "POST",
        body: {
          full_name: nameInput.value.trim(),
          specialty: specialtyInput.value.trim(),
          phone: phoneValue,
          service_ids,
        },
      });
      notice("globalNotice", "پزشک جدید ثبت شد.", "ok");
    } else {
      await api(`/doctors/${doctor.id}`, {
        method: "PUT",
        body: {
          full_name: nameInput.value.trim(),
          specialty: specialtyInput.value.trim(),
          phone: phoneValue,
          is_active: true,
          service_ids,
        },
      });
      notice("globalNotice", "اطلاعات پزشک به‌روزرسانی شد.", "ok");
    }
    box.hidden = true;
    box.textContent = "";
    await activateTab("doctors");
  });
  box.append(form);
}

async function renderServicesView() {
  const rows = await api("/dental-services/");
  const container = $("servicesTable");
  const table = el("table");
  table.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "خدمت" }),
    el("th", { text: "توضیح" }),
    el("th", { text: "وضعیت" }),
    ...(permissions().adminOnly ? [el("th", { text: "" })] : []),
  ])]));
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    tr.append(
      el("td", { text: row.name }),
      el("td", { text: row.description || "—" }),
      el("td", {}, [
        el("span", {
          class: `status-badge ${row.is_active ? "status-scheduled" : "status-cancelled"}`,
          text: row.is_active ? "فعال" : "غیرفعال",
        }),
      ])
    );
    if (permissions().adminOnly) {
      tr.append(el("td", {}, [
        el("button", {
          class: "btn ghost",
          type: "button",
          text: "ویرایش",
          onClick: () => openServiceForm(row).catch(showApiError),
        }),
      ]));
    }
    tbody.append(tr);
  }
  table.append(tbody);
  container.textContent = "";
  container.append(table);
  if (permissions().adminOnly) {
    ensureButton("addServiceBtn", "خدمت جدید", () =>
      openServiceForm(null).catch(showApiError), "serviceForm");
  }
}

async function openServiceForm(service) {
  const box = $("serviceForm");
  box.hidden = false;
  box.textContent = "";
  const isCreate = service === null;
  const nameInput = el("input", { value: isCreate ? "" : service.name });
  const descInput = el("input", { value: isCreate ? "" : service.description || "" });
  const form = el("form", { class: "stack" });
  form.append(
    el("h3", { text: isCreate ? "خدمت جدید" : `ویرایش خدمت ${service.name}` }),
    labelWith("نام خدمت", nameInput),
    labelWith("توضیح", descInput),
    el("div", { class: "actions-row" }, [
      el("button", { class: "btn", type: "submit", text: "ذخیره" }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: () => {
          box.hidden = true;
          box.textContent = "";
        },
      }),
    ])
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isCreate) {
      await api("/dental-services/", {
        method: "POST",
        body: {
          name: nameInput.value.trim(),
          description: descInput.value.trim() || null,
        },
      });
      notice("globalNotice", "خدمت جدید ثبت شد.", "ok");
    } else {
      await api(`/dental-services/${service.id}`, {
        method: "PUT",
        body: {
          name: nameInput.value.trim(),
          description: descInput.value.trim() || null,
          is_active: true,
        },
      });
      notice("globalNotice", "خدمت به‌روزرسانی شد.", "ok");
    }
    box.hidden = true;
    box.textContent = "";
    await activateTab("services");
  });
  box.append(form);
}

/* =================== schedules =================== */

async function renderSchedulesView() {
  const select = $("scheduleDoctor");
  let doctorOptions = null;
  if (!select.options.length) {
    const doctors = await api("/doctors/");
    doctorOptions = doctors;
    for (const doctor of doctors) {
      select.append(el("option", { value: doctor.id, text: doctor.full_name }));
    }
    $("scheduleLoad").addEventListener("click", () =>
      loadSchedules().catch(showApiError)
    );
    if (permissions().adminOnly) {
      const openForm = () => openScheduleForm(doctorOptions).catch(showApiError);
      if (!$("addScheduleBtn")) {
        const button = el("button", {
          class: "btn secondary",
          type: "button",
          id: "addScheduleBtn",
          text: "برنامه جدید",
        });
        button.addEventListener("click", openForm);
        $("scheduleForm").before(button);
      }
    }
  }
  await loadSchedules();
}

async function loadSchedules() {
  const doctorId = $("scheduleDoctor").value;
  const rows = doctorId ? await api(`/doctor-schedules/${doctorId}`) : [];
  const container = $("schedulesTable");
  if (!rows.length) {
    container.textContent = "";
    container.append(el("div", { class: "empty-state", text: "برنامه‌ای ثبت نشده است." }));
    return;
  }
  const table = el("table");
  const head = ["روز", "از", "تا", "مدت هر نوبت (دقیقه)", "وضعیت"];
  table.append(el("thead", {}, [
    el("tr", {}, head.map((title) => el("th", { text: title }))),
  ]));
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    tr.append(
      el("td", { text: DAY_LABELS[row.day_of_week] || row.day_of_week }),
      el("td", { text: row.start_time.slice(0, 5) }),
      el("td", { text: row.end_time.slice(0, 5) }),
      el("td", { text: String(row.slot_duration_minutes) }),
      el("td", {}, [
        el("span", {
          class: `status-badge ${row.is_active ? "status-scheduled" : "status-cancelled"}`,
          text: row.is_active ? "فعال" : "غیرفعال",
        }),
      ])
    );
    if (permissions().adminOnly) {
      tr.append(el("td", {}, [
        el("button", {
          class: "btn ghost",
          type: "button",
          text: "حذف",
          onClick: () => deleteSchedule(row).catch(showApiError),
        }),
      ]));
    }
    tbody.append(tr);
  }
  table.append(tbody);
  container.textContent = "";
  container.append(table);
}

async function deleteSchedule(row) {
  await api(`/doctor-schedules/${row.id}`, { method: "DELETE" });
  notice("globalNotice", "برنامه حذف شد.", "ok");
  await loadSchedules();
}

async function openScheduleForm(presetDoctors = null) {
  const box = $("scheduleForm");
  box.hidden = false;
  box.textContent = "";
  const doctorSelect = el("select");
  const doctors = presetDoctors || (await api("/doctors/"));
  for (const doctor of doctors) {
    doctorSelect.append(el("option", { value: doctor.id, text: doctor.full_name }));
  }
  const daySelect = el("select");
  DAY_LABELS.forEach((label, index) => {
    daySelect.append(el("option", { value: index, text: label }));
  });
  const startInput = el("input", { placeholder: "09:00" });
  const endInput = el("input", { placeholder: "12:00" });
  const durationInput = el("input", { value: "30", inputmode: "numeric" });
  const form = el("form", { class: "stack" });
  form.append(
    el("h3", { text: "برنامه جدید" }),
    el("div", { class: "filters-row" }, [
      labelWith("پزشک", doctorSelect),
      labelWith("روز", daySelect),
      labelWith("از ساعت", startInput),
      labelWith("تا ساعت", endInput),
      labelWith("مدت (دقیقه)", durationInput),
    ]),
    el("div", { class: "actions-row" }, [
      el("button", { class: "btn", type: "submit", text: "ذخیره" }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: () => {
          box.hidden = true;
          box.textContent = "";
        },
      }),
    ])
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/doctor-schedules/", {
      method: "POST",
      body: {
        doctor_id: Number(doctorSelect.value),
        day_of_week: Number(daySelect.value),
        start_time: startInput.value.trim(),
        end_time: endInput.value.trim(),
        slot_duration_minutes: Number(durationInput.value),
      },
    });
    notice("globalNotice", "برنامه ثبت شد.", "ok");
    box.hidden = true;
    box.textContent = "";
    await loadSchedules();
  });
  box.append(form);
}

/* =================== users (admin) =================== */

async function renderUsersView() {
  const rows = await api("/users/");
  const container = $("usersTable");
  const table = el("table");
  table.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "نام" }),
    el("th", { text: "شماره تلفن" }),
    el("th", { text: "نقش" }),
    el("th", { text: "وضعیت" }),
    el("th", { text: "" }),
  ])]));
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    tr.append(
      el("td", { text: row.full_name }),
      el("td", { text: row.phone }),
      el("td", {}, [
        el("span", { class: "role-badge", text: ROLE_LABELS[row.role] || row.role }),
      ]),
      el("td", {}, [
        el("span", {
          class: `status-badge ${row.is_active ? "status-scheduled" : "status-cancelled"}`,
          text: row.is_active ? "فعال" : "غیرفعال",
        }),
      ])
    );
    const actions = el("td");
    actions.append(
      el("button", {
        class: "btn ghost",
        type: "button",
        text: row.is_active ? "غیرفعال کردن" : "فعال کردن",
        onClick: () =>
          toggleUserActive(row).catch(showApiError),
      })
    );
    tr.append(actions);
    tbody.append(tr);
  }
  table.append(tbody);
  container.textContent = "";
  container.append(table);
  if (permissions().adminOnly) {
    ensureButton("addUserBtn", "کاربر جدید", () =>
      openUserForm().catch(showApiError), "userForm");
  }
}

async function toggleUserActive(row) {
  await api(`/users/${row.id}`, {
    method: "PUT",
    body: { is_active: !row.is_active },
  });
  notice(
    "globalNotice",
    `حساب ${row.full_name} ${row.is_active ? "غیرفعال" : "فعال"} شد.`,
    "ok"
  );
  await activateTab("users");
}

async function openUserForm() {
  const box = $("userForm");
  box.hidden = false;
  box.textContent = "";
  const nameInput = el("input");
  const phoneInput = el("input", { inputmode: "tel" });
  const passwordInput = el("input", { type: "password" });
  const roleSelect = el("select");
  for (const [role, label] of Object.entries(ROLE_LABELS)) {
    roleSelect.append(el("option", { value: role, text: label }));
  }
  const form = el("form", { class: "stack" });
  form.append(
    el("h3", { text: "کاربر جدید" }),
    el("div", { class: "filters-row" }, [
      labelWith("نام", nameInput),
      labelWith("شماره تلفن", phoneInput),
      labelWith("رمز عبور", passwordInput),
      labelWith("نقش", roleSelect),
    ]),
    el("div", { class: "actions-row" }, [
      el("button", { class: "btn", type: "submit", text: "ایجاد حساب" }),
      el("button", {
        class: "btn ghost",
        type: "button",
        text: "بستن",
        onClick: () => {
          box.hidden = true;
          box.textContent = "";
        },
      }),
    ])
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/users/", {
      method: "POST",
      body: {
        full_name: nameInput.value.trim(),
        phone: phoneInput.value.trim(),
        password: passwordInput.value,
        role: roleSelect.value,
      },
    });
    notice("globalNotice", "کاربر جدید ایجاد شد.", "ok");
    box.hidden = true;
    box.textContent = "";
    await activateTab("users");
  });
  box.append(form);
}

/* =================== agent chat =================== */

const QUICK_ACTIONS = [
  { prompt: "نزدیک‌ترین نوبت‌های آزاد کلینیک را نشان بده.", label: "نزدیک‌ترین نوبت‌ها" },
  { prompt: "نوبت‌های من را نشان بده.", label: "نوبت‌های من" },
];

function renderChatIntro() {
  const box = $("chatMessages");
  box.textContent = "";
  box.append(
    el("div", { class: "message-row assistant" }, [
      el("div", {
        class: "bubble",
        text:
          "سلام و خوش آمدید! من دستیار کلینیک هستم. می‌توانید نزدیک‌ترین نوبت‌ها را بپرسید، نوبت رزرو کنید یا نوبت‌های خود را ببینید.",
      }),
    ])
  );
  const actions = $("quickActions");
  actions.textContent = "";
  for (const action of QUICK_ACTIONS) {
    actions.append(
      el("button", {
        class: "btn secondary",
        "data-prompt": action.prompt,
        type: "button",
        text: action.label,
        onClick: () => sendMessage(action.prompt).catch(showApiError),
      })
    );
  }
  $("chatNotice").hidden = true;
  $("confirmationPane").hidden = true;
  $("messageInput").disabled = false;
  $("sendBtn").disabled = false;
}

function addMessage(role, text) {
  const box = $("chatMessages");
  box.append(
    el("div", { class: `message-row ${role}` }, [
      el("div", { class: "bubble", text }),
    ])
  );
  box.scrollTop = box.scrollHeight;
}

async function sendMessage(text, confirmation = null) {
  notice("chatNotice", "");
  $("quickActions").hidden = true;
  $("messageInput").disabled = true;
  $("sendBtn").disabled = true;
  let history = [...state.history];
  if (confirmation) {
    // Retry with the pending token; no duplicated user turn in history.
    history = history.filter((item) => item.content !== text);
  } else {
    addMessage("user", text);
    history = history.slice(-18);
    history = [...history, { role: "user", content: text }];
  }
  const body = {
    message: text,
    history,
  };
  if (state.sessionId) body.session_id = state.sessionId;
  if (confirmation) body.confirmation = confirmation;

  try {
    const data = await api("/agent/chat", { method: "POST", body });
    state.sessionId = data.session_id;
    if (!confirmation) state.history = history;
    $("messageInput").value = "";
    applyAgentResponse(data);
  } catch (error) {
    if (error.network) {
      notice("chatNotice", "ارتباط برقرار نیست؛ می‌توانید دوباره تلاش کنید.", "error");
    } else if (error.status === 409) {
      notice(
        "chatNotice",
        (error.message || "این درخواست منقضی شده است.") + " «درخواست دوباره» لازم است.",
        "error"
      );
      state.pendingConfirmation = null;
    } else {
      state.history = state.history.filter((item) => item.content !== text);
      throw error;
    }
  } finally {
    // Keep the composer locked while a write confirmation is still pending;
    // a new message over an open approval could invalidate or hide it.
    const locked = state.pendingConfirmation !== null;
    $("messageInput").disabled = locked;
    $("sendBtn").disabled = locked;
  }
}

function applyAgentResponse(data) {
  addMessage("assistant", data.reply || "پاسخی دریافت نشد.");
  state.pendingConfirmation = null;
  $("confirmationPane").hidden = true;
  if (data.confirmation_required && data.confirmation_token) {
    state.pendingConfirmation = {
      token: data.confirmation_token,
      session_id: data.session_id,
    };
    $("confirmationPrompt").textContent = data.confirmation_prompt || "تأیید لازم است.";
    $("confirmationPane").hidden = false;
    $("messageInput").disabled = true;
    $("sendBtn").disabled = true;
    return;
  }
  const slots = data.slots || [];
  if (slots.length) {
    const list = el("div", { class: "slot-list" });
    for (const slot of slots) {
      const button = el("button", {
        class: "slot",
        type: "button",
        text: `${slot.doctor_name} — ${slot.service_name}\n${slot.appointment_date} ساعت ${slot.appointment_time}`,
        onClick: () => {
          for (const node of list.children) node.disabled = true;
          sendMessage(
            `سلام. برای ${slot.doctor_name} با خدمت ${slot.service_name} در تاریخ ${slot.appointment_date} ساعت ${slot.appointment_time} نوبت می‌خواهم.`
          ).catch(showApiError);
        },
      });
      list.append(button);
    }
    $("chatMessages").append(list);
    $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  }
}

async function decideConfirmation(decision) {
  const pending = state.pendingConfirmation;
  if (!pending) return;
  state.pendingConfirmation = null;
  $("confirmationPane").hidden = true;
  const message = decision === "approved" ? "تأیید شد" : "درخواست لغو شد";
  addMessage("user", message);
  try {
    const data = await api("/agent/chat", {
      method: "POST",
      body: {
        message: "تأیید عملیات",
        history: state.history.filter((item) => item.content !== "تأیید عملیات"),
        session_id: pending.session_id,
        confirmation: { token: pending.token, decision },
      },
    });
    state.sessionId = data.session_id;
    $("messageInput").value = "";
    applyAgentResponse(data);
  } catch (error) {
    if (error.network) {
      notice(
        "chatNotice",
        "نتیجهٔ این تأیید مشخص نیست؛ لطفاً نتیجه را از بخش «نوبت‌ها» یا دستیار دوباره بررسی کنید.",
        "warn"
      );
    } else if (error.status === 409) {
      notice("chatNotice", error.message, "error");
    } else {
      throw error;
    }
  }
}

/* =================== booking slot loader =================== */

async function loadBookingSlots() {
  const doctorId = $("bookingDoctor").value;
  const dateValue = $("bookingDate").value.trim();
  const slotSelect = $("bookingSlot");
  if (!doctorId || !dateValue) {
    throw { message: "پزشک و تاریخ را انتخاب کنید." };
  }
  const data = await api(
    `/appointments/available-slots/?doctor_id=${doctorId}&appointment_date=${encodeURIComponent(dateValue)}`
  );
  slotSelect.textContent = "";
  if (!data.available_slots.length) {
    slotSelect.append(el("option", { value: "", text: "ساعت آزادی موجود نیست" }));
    return;
  }
  slotSelect.append(el("option", { value: "", text: "انتخاب ساعت" }));
  for (const slot of data.available_slots) {
    slotSelect.append(el("option", { value: slot, text: slot }));
  }
}

/* =================== listen & boot =================== */

function bindLoginEvents() {
  const passwordForm = $("passwordLoginForm");
  const otpForm = $("otpLoginForm");
  $("tabLoginPassword").addEventListener("click", () => {
    passwordForm.hidden = false;
    otpForm.hidden = true;
    $("tabLoginPassword").classList.add("active");
    $("tabLoginPassword").classList.remove("ghost");
    $("tabLoginOtp").classList.remove("active");
    $("tabLoginOtp").classList.add("ghost");
  });
  $("tabLoginOtp").addEventListener("click", () => {
    passwordForm.hidden = true;
    otpForm.hidden = false;
    $("tabLoginOtp").classList.add("active");
    $("tabLoginOtp").classList.remove("ghost");
    $("tabLoginPassword").classList.remove("active");
    $("tabLoginPassword").classList.add("ghost");
  });

  passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    notice("loginError", "");
    try {
      await loginWithPassword(
        $("loginPhone").value.trim(),
        $("loginPassword").value
      );
    } catch (error) {
      notice("loginError", error.message || "ورود انجام نشد.", "error");
    }
  });

  $("requestOtp").addEventListener("click", async () => {
    try {
      const data = await api("/auth/otp/request", {
        method: "POST",
        body: { phone: $("otpPhone").value.trim() },
      });
      if (data.dev_otp) {
        $("otpCode").value = data.dev_otp;
        notice(
          "loginNotice",
          "کد توسعه در فیلد کد وارد شد (فقط محیط توسعه).",
          "info"
        );
      } else {
        notice("loginNotice", "کد پیامکی ارسال شد.", "info");
      }
      $("otpCodeWrap").hidden = false;
    } catch (error) {
      notice("loginError", error.message || "درخواست کد انجام نشد.", "error");
    }
  });

  $("verifyOtp").addEventListener("click", async () => {
    try {
      const data = await api("/auth/otp/verify", {
        method: "POST",
        body: {
          phone: $("otpPhone").value.trim(),
          code: $("otpCode").value.trim(),
        },
      });
      state.token = data.access_token;
      state.me = await api("/auth/me");
      enterPanel();
    } catch (error) {
      notice("loginError", error.message || "کد تأیید نشد.", "error");
    }
  });

  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("messageInput").value.trim();
    if (!text) return;
    sendMessage(text).catch(showApiError);
  });

  $("approve").addEventListener("click", () =>
    decideConfirmation("approved").catch(showApiError)
  );
  $("reject").addEventListener("click", () =>
    decideConfirmation("rejected").catch(showApiError)
  );

  $("logoutBtn").addEventListener("click", () => logout().catch(showApiError));

  $("bookingForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitBooking();
  });

  $("bookingLoadSlots").addEventListener("click", () =>
    loadBookingSlots().catch(showApiError)
  );
}

async function submitBooking() {
  const patientValue = $("bookingPatientSearch").value;
  const doctorId = $("bookingDoctor").value;
  const serviceId = $("bookingService").value;
  const date = $("bookingDate").value.trim();
  const time = $("bookingSlot").value;
  const reason = $("bookingReason").value.trim();
  if (!patientValue || !doctorId || !serviceId || !date || !time) {
    throw { message: "بیمار، پزشک، خدمت، تاریخ و ساعت را کامل انتخاب کنید." };
  }
  // Datalist text keeps phone + national id; split them out safely.
  const parts = patientValue.split("—").map((part) => part.trim());
  const full_name = parts.length >= 3 ? parts[0] : patientValue.trim();
  const phone = parts.length >= 3 ? parts[1] : "";
  const national_id = parts.length >= 3 ? parts[2] : "";
  const payload = {
    doctor_id: Number(doctorId),
    service_id: Number(serviceId),
    appointment_date: date,
    appointment_time: time,
    reason: reason || null,
  };
  if (national_id) {
    payload.national_id = national_id;
    payload.full_name = full_name;
    payload.phone = phone;
  }
  const created = await api("/appointments/", { method: "POST", body: payload });
  notice(
    "globalNotice",
    `نوبت با ${created.appointment_date} ساعت ${created.appointment_time} ثبت شد.`,
    "ok"
  );
  $("bookingPatientSearch").value = "";
  $("bookingSlot").textContent = "";
  await activateTab("appointments");
}

boot();
async function boot() {
  bindLoginEvents();
}
