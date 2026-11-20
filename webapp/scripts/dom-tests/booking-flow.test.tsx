import assert from 'node:assert/strict';
import { after, afterEach, describe, it } from 'node:test';
import React, { act } from 'react';
import { createRoot, Root } from 'react-dom/client';
import { AppointmentBookingModal } from '../../src/components/appointments/AppointmentBookingModal';
import { upcomingDays } from '../../src/utils/analytics';

const days = upcomingDays(12);
const DOCTORS = [
  { id: 1, full_name: 'دکتر مینا رضایی', specialty: 'ارتودنسی', is_active: true },
  { id: 2, full_name: 'دکتر علی صادقی', specialty: 'ایمپلنت', is_active: true },
];
const SERVICES = [
  { id: 10, name: 'جرم‌گیری', description: 'پاکسازی', is_active: true },
  { id: 11, name: 'ترمیم', description: null, is_active: true },
];
const PATIENTS = [
  { id: 100, national_id: '0012345678', full_name: 'سارا احمدی', phone: '09121111111', is_account_holder: true, record_status: 'complete' },
  { id: 101, national_id: '0087654321', full_name: 'رضا کریمی', phone: '09122222222', record_status: 'complete' },
];

type SlotFn = (doctorId: number, date: string) => Promise<string[]>;

// Day 0 is full, day 1 has two slots, every later day has one.
const defaultSlots: SlotFn = async (_doctor, date) => {
  const index = days.findIndex((day) => day.jalali === date);
  if (index === 0) return [];
  if (index === 1) return ['09:00:00', '10:30'];
  return ['11:00'];
};

let root: Root | null = null;
let container: HTMLElement | null = null;
const calls = { slots: [] as Array<[number, string]>, booked: [] as any[] };

async function settle() {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function mount(opts: {
  role?: 'patient' | 'receptionist';
  patients?: typeof PATIENTS;
  slots?: SlotFn;
  book?: (payload: any) => Promise<void>;
  props?: Partial<React.ComponentProps<typeof AppointmentBookingModal>>;
} = {}) {
  const slotFn = opts.slots ?? defaultSlots;
  calls.slots = [];
  calls.booked = [];
  (globalThis as any).__clinic = {
    doctors: DOCTORS,
    services: SERVICES,
    patients: opts.patients ?? PATIENTS,
    getAvailableSlots: (doctorId: number, date: string) => {
      calls.slots.push([doctorId, date]);
      return slotFn(doctorId, date);
    },
    bookAppointment: async (payload: any) => {
      calls.booked.push(payload);
      if (opts.book) await opts.book(payload);
    },
  };
  (globalThis as any).__auth = {
    currentUser: { role: opts.role ?? 'receptionist', patient: { id: 100 }, full_name: 'کاربر' },
  };
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(<AppointmentBookingModal isOpen onClose={() => {}} {...opts.props} />);
  });
  await settle();
}

const buttons = () => Array.from(document.querySelectorAll('button'));
const byText = (text: string) => buttons().find((b) => (b.textContent || '').includes(text));
async function click(el: Element | undefined | null) {
  assert.ok(el, 'element to click was not found');
  await act(async () => {
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  });
  await settle();
}
const submitButton = () => byText('ثبت نوبت') as HTMLButtonElement;
const text = () => document.body.textContent || '';

// React's scheduler and jsdom keep the event loop alive, so finish explicitly
// (after the reporter has flushed) with the right exit status.
let anyFailed = false;
after(() => {
  window.close();
  setTimeout(() => process.exit(anyFailed ? 1 : 0), 300);
});

afterEach(async (t) => {
  if ((t as any).passed === false) anyFailed = true;
  await act(async () => root?.unmount());
  document.body.innerHTML = '';
  root = null;
});

describe('manual booking flow', () => {
  it('staff must pick the patient: nothing is preselected and submit is disabled', async () => {
    await mount({ role: 'receptionist' });
    assert.ok(byText('سارا احمدی'), 'patient options are shown first');
    assert.equal(submitButton().disabled, true);
    assert.match(text(), /بیمار را انتخاب کنید/);
    assert.equal(calls.slots.length, 0, 'no availability is requested before a doctor is chosen');
  });

  it('a patient account with one record skips the patient step', async () => {
    await mount({ role: 'patient', patients: [PATIENTS[0]] });
    assert.ok(!document.getElementById('booking-patient-header'), 'no patient section');
    assert.ok(byText('جرم‌گیری'), 'service options are open');
  });

  it('nearest free slot sets day and time in one tap, then books exactly that', async () => {
    await mount({ role: 'patient', patients: [PATIENTS[0]] });
    await click(byText('جرم‌گیری'));
    await click(byText('دکتر مینا رضایی'));

    assert.equal(calls.slots.length, days.length, 'every day is looked up once');
    assert.ok(calls.slots.every(([doctor]) => doctor === 1));

    const shortcut = byText('نزدیک‌ترین زمان خالی');
    assert.ok(shortcut, 'shortcut is offered');
    assert.match(shortcut!.textContent!, /۰۹:۰۰/, 'earliest is day 1 at 09:00, not the full day 0');
    await click(shortcut);
    assert.equal(submitButton().disabled, false);

    await click(submitButton());
    assert.equal(calls.booked.length, 1);
    assert.deepEqual(calls.booked[0], {
      doctor_id: 1,
      service_id: 10,
      appointment_date: days[1].jalali,
      appointment_time: '09:00',
      patient_id: 100,
      reason: undefined,
    });
    assert.match(text(), /ثبت شد/);
    assert.ok(byText('بستن'));
  });

  it('days without free slots cannot be selected', async () => {
    await mount({ role: 'patient', patients: [PATIENTS[0]], props: { initialDoctorId: 1, initialServiceId: 10 } });
    const group = document.querySelector('[aria-label="روز نوبت"]')!;
    const dayButtons = Array.from(group.querySelectorAll('button'));
    assert.equal(dayButtons[0].disabled, true, 'day 0 is full');
    assert.equal(dayButtons[1].disabled, false);
  });

  it('initial doctor and service open the day-and-time step directly', async () => {
    await mount({ role: 'patient', patients: [PATIENTS[0]], props: { initialDoctorId: 2, initialServiceId: 11 } });
    assert.ok(byText('نزدیک‌ترین زمان خالی'));
    assert.ok(calls.slots.every(([doctor]) => doctor === 2));
  });

  it('a conflict on submit shows the reason, clears the time and re-reads that day', async () => {
    await mount({
      role: 'patient',
      patients: [PATIENTS[0]],
      props: { initialDoctorId: 1, initialServiceId: 10 },
      book: async () => {
        throw new Error('این زمان دیگر خالی نیست.');
      },
    });
    await click(byText('نزدیک‌ترین زمان خالی'));
    const before = calls.slots.length;
    await click(submitButton());

    const alert = document.querySelector('[role="alert"]');
    assert.ok(alert, 'an alert is shown');
    assert.match(alert!.textContent!, /این زمان دیگر خالی نیست/);
    assert.match(alert!.textContent!, /ساعت دیگری انتخاب کنید/);
    assert.equal(submitButton().disabled, true, 'time was cleared, so submit is disabled again');
    assert.ok(calls.slots.length > before, 'the day was looked up again');
    assert.equal(calls.booked.length, 1);
  });

  it('a failing day shows an error state and does not block the others', async () => {
    await mount({
      role: 'patient',
      patients: [PATIENTS[0]],
      props: { initialDoctorId: 1, initialServiceId: 10 },
      slots: async (doctor, date) => {
        if (date === days[1].jalali) throw new Error('سرور پاسخ نداد.');
        return defaultSlots(doctor, date);
      },
    });
    const shortcut = byText('نزدیک‌ترین زمان خالی');
    assert.ok(shortcut, 'the nearest answer skips the failed day');
    assert.match(shortcut!.textContent!, /۱۱:۰۰/);
    const group = document.querySelector('[aria-label="روز نوبت"]')!;
    assert.match(group.querySelectorAll('button')[1].textContent!, /خطا/);
  });

  it('says so when the doctor has no free time at all', async () => {
    await mount({
      role: 'patient',
      patients: [PATIENTS[0]],
      props: { initialDoctorId: 1, initialServiceId: 10 },
      slots: async () => [],
    });
    assert.match(text(), /زمان خالی پیدا نشد/);
    assert.ok(!byText('نزدیک‌ترین زمان خالی'));
  });

  it('staff can search a long patient list', async () => {
    const many = Array.from({ length: 9 }, (_, i) => ({
      id: 200 + i,
      national_id: `00000000${i}${i}`,
      full_name: i === 4 ? 'نگین حسینی' : `بیمار ${i}`,
      phone: `0912000000${i}`,
      record_status: 'complete',
    }));
    await mount({ role: 'receptionist', patients: many as any });
    const input = document.querySelector('input[type="search"]') as HTMLInputElement;
    assert.ok(input, 'search box appears for long lists');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
      setter.call(input, 'نگین');
      input.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    assert.ok(byText('نگین حسینی'));
    assert.ok(!byText('بیمار 0'));
  });
});
