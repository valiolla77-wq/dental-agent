import assert from 'node:assert/strict';
import { after, afterEach, describe, it, mock } from 'node:test';
import React, { act } from 'react';
import { createRoot, Root } from 'react-dom/client';
import { LoginView } from '../../src/components/auth/LoginView';

/**
 * The two enforced doors: the patient portal is OTP-first with a password
 * fallback, the staff portal is password-only. Both cross-link each other
 * and never mix copy.
 */

let root: Root | null = null;
const text = () => document.body.textContent || '';

async function render(node: React.ReactElement) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(node);
  });
}

function setAuth(portal: 'patient' | 'staff', loginWithPassword = mock.fn(async () => {})) {
  (globalThis as any).__auth = {
    currentUser: null,
    portal,
    loginWithPassword,
    requestOtp: async () => undefined,
    verifyOtp: async () => {},
  };
  return { loginWithPassword };
}

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

describe('the two login portals are separate doors', () => {
  it('patient portal: OTP-first, staff door is one link away', async () => {
    setAuth('patient');
    await render(<LoginView />);
    assert.ok(text().includes('درگاه بیماران'), 'patient portal chip');
    // The staff-door mention must come only from the cross-link, never as
    // this portal's own identity chip.
    const staffChipCount = text().split('درگاه پرسنل').length - 1;
    assert.equal(staffChipCount, 1, 'staff door referenced only by the cross-link');
    const otpTab = document.querySelector('[role="tab"][aria-selected="true"]');
    assert.ok(otpTab && (otpTab.textContent || '').includes('یک‌بارمصرف'), 'OTP tab is default');
    const crossLink = Array.from(document.querySelectorAll('a')).find((a) =>
      (a.getAttribute('href') || '') === '/staff'
    );
    assert.ok(crossLink, 'links to the staff portal');
    assert.ok((crossLink!.textContent || '').includes('پرسنل'));
  });

  it('staff portal: password-only with no OTP tab', async () => {
    setAuth('staff');
    await render(<LoginView />);
    assert.ok(text().includes('درگاه پرسنل'), 'staff portal chip');
    assert.ok(!text().includes('یک‌بارمصرف'), 'no OTP tab for staff');
    const tabs = document.querySelectorAll('[role="tab"]');
    assert.equal(tabs.length, 0, 'no method tabs at all');
    assert.ok(document.getElementById('login-password'), 'password field present');
    const crossLink = Array.from(document.querySelectorAll('a')).find((a) =>
      (a.getAttribute('href') || '') === '/app'
    );
    assert.ok(crossLink, 'links back to the patient portal');
  });

  it('staff portal submits the password through the shared login hook', async () => {
    const { loginWithPassword } = setAuth('staff');
    await render(<LoginView />);
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value'
    )!.set!;
    const phone = document.getElementById('login-phone') as HTMLInputElement;
    const password = document.getElementById('login-password') as HTMLInputElement;
    await act(async () => {
      nativeSetter.call(phone, '09121234500');
      phone.dispatchEvent(new window.Event('input', { bubbles: true }));
      nativeSetter.call(password, 'ClinicAdmin!1404');
      password.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    const form = phone.closest('form')!;
    await act(async () => {
      form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    });
    assert.equal(loginWithPassword.mock.callCount(), 1);
    const [payload] = loginWithPassword.mock.calls[0].arguments as unknown as [
      Record<string, string>,
    ];
    assert.deepEqual(payload, { phone: '09121234500', password: 'ClinicAdmin!1404' });
  });
});
