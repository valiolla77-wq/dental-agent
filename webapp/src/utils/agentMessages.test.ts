import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isOutcomeUncertain, repeatsConfirmationPrompt } from './agentMessages';

const PROMPT = 'ثبت نوبت برای «معاینه» با دکتر سارا احمدی را تأیید می‌کنید؟';

test('hides the bubble text when it only repeats the card prompt', () => {
  assert.equal(repeatsConfirmationPrompt(PROMPT, PROMPT, true), true);
  assert.equal(repeatsConfirmationPrompt(`  ${PROMPT}\n`, PROMPT, true), true);
});

test('keeps the text when it says something more than the card', () => {
  assert.equal(repeatsConfirmationPrompt(`لطفاً بررسی کنید. ${PROMPT}`, PROMPT, true), false);
});

test('never hides text when there is no confirmation card or prompt', () => {
  assert.equal(repeatsConfirmationPrompt(PROMPT, PROMPT, false), false);
  assert.equal(repeatsConfirmationPrompt(PROMPT, null, true), false);
  assert.equal(repeatsConfirmationPrompt('', '', true), false);
});

test('an unreachable or failing server leaves the outcome unknown; a refusal does not', () => {
  for (const status of [0, 408, 500, 502, 504]) {
    assert.equal(isOutcomeUncertain(status), true, `status ${status}`);
  }
  for (const status of [400, 401, 403, 404, 409, 422]) {
    assert.equal(isOutcomeUncertain(status), false, `status ${status}`);
  }
});
