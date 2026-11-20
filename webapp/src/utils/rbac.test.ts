import test from 'node:test';
import assert from 'node:assert/strict';
import { hasPermission } from './rbac';

test('admin role has full permissions', () => {
  assert.equal(hasPermission('admin', 'manage_doctors'), true);
  assert.equal(hasPermission('admin', 'manage_services'), true);
  assert.equal(hasPermission('admin', 'manage_settings'), true);
});

test('patient cannot manage doctors or settings', () => {
  assert.equal(hasPermission('patient', 'manage_doctors'), false);
  assert.equal(hasPermission('patient', 'manage_settings'), false);
  assert.equal(hasPermission('patient', 'book_appointment'), true);
});

test('receptionist has appointment management but not settings', () => {
  assert.equal(hasPermission('receptionist', 'manage_appointments'), true);
  assert.equal(hasPermission('receptionist', 'manage_settings'), false);
});
