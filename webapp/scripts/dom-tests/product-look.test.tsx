import assert from 'node:assert/strict';
import { after, afterEach, describe, it, mock } from 'node:test';
import React, { act } from 'react';
import { createRoot, Root } from 'react-dom/client';
import { LoginView } from '../../src/components/auth/LoginView';
import { Header } from '../../src/components/layout/Header';
import { ConnectionLostView } from '../../src/components/common/ConnectionLostView';

// Words that must never reach a person using the product.
const FORBIDDEN = [
  'دمو',
  'Demo',
  'نمایشی',
  'آزمایشی',
  'داده نمونه',
  'داده‌های نمونه',
  'FastAPI',
  'بک‌اند',
  'OpenAPI',
  'سپید',
  'demoPassword',
];

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

function setContexts(health: 'connected' | 'disconnected' | 'connecting' = 'connected') {
  const refreshHealth = mock.fn(async () => {});
  (globalThis as any).__auth = {
    currentUser: { role: 'receptionist', full_name: 'پذیرش', patient: null },
    loginWithPassword: async () => {},
    requestOtp: async () => undefined,
    verifyOtp: async () => {},
  };
  (globalThis as any).__clinic = {
    healthState: { status: health },
    refreshHealth,
    setAgentDrawerOpen: () => {},
  };
  return { refreshHealth };
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

describe('the product has no demo look', () => {
  it('sign-in page: no mode switch, no demo shortcuts, neutral brand', async () => {
    setContexts();
    await render(<LoginView />);
    for (const word of FORBIDDEN) {
      assert.ok(!text().includes(word), `sign-in page must not contain «${word}»`);
    }
    assert.ok(text().includes('Dental Agent'), 'defaults to the product name');
    assert.ok(!text().includes('حالت اتصال'), 'no connection-mode switch');
    const labels = Array.from(document.querySelectorAll('button')).map((b) => b.textContent || '');
    assert.ok(!labels.some((label) => /09\d{9}/.test(label)), 'no phone-number shortcuts');
  });

  it('header: shows nothing about the connection while the server is reachable', async () => {
    setContexts('connected');
    await render(<Header currentView="dashboard" onSelectView={() => {}} onOpenMobileMenu={() => {}} />);
    for (const word of FORBIDDEN) {
      assert.ok(!text().includes(word), `header must not contain «${word}»`);
    }
    assert.ok(!text().includes('ارتباط با سرور قطع است'));
    assert.ok(!text().includes('تغییر نقش'), 'no role switcher');
  });

  it('header: a down server is announced and the pill re-checks on click', async () => {
    const { refreshHealth } = setContexts('disconnected');
    await render(<Header currentView="dashboard" onSelectView={() => {}} onOpenMobileMenu={() => {}} />);
    const pill = Array.from(document.querySelectorAll('button')).find((b) =>
      (b.getAttribute('aria-label') || '').includes('ارتباط با سرور قطع است')
    );
    assert.ok(pill, 'connection pill is shown');
    await act(async () => {
      pill!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    });
    assert.equal(refreshHealth.mock.callCount(), 1);
  });

  it('connection-lost page keeps the session promise and retries on demand', async () => {
    const onRetry = mock.fn(async () => {});
    await render(<ConnectionLostView onRetry={onRetry} />);
    assert.match(text(), /ارتباط با سرور برقرار نشد/);
    assert.match(text(), /نشست شما حفظ شده است/);
    const retry = Array.from(document.querySelectorAll('button')).find((b) =>
      (b.textContent || '').includes('تلاش دوباره')
    );
    await act(async () => {
      retry!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    });
    assert.equal(onRetry.mock.callCount(), 1);
  });
});
