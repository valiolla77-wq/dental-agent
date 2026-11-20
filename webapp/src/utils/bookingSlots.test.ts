import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  findEarliestSlot,
  groupSlotsByDayPart,
  initialsOf,
  matchesQuery,
  normalizeSlots,
  type DayAvailability,
} from './bookingSlots';

test('normalizeSlots trims seconds, dedupes, sorts and drops junk', () => {
  assert.deepEqual(normalizeSlots(['10:30:00', '09:00', '10:30', 'x', '25:00', null]), [
    '09:00',
    '10:30',
  ]);
  assert.deepEqual(normalizeSlots(undefined), []);
});

test('groupSlotsByDayPart keeps only non-empty groups in order', () => {
  const groups = groupSlotsByDayPart(['09:00', '11:30', '12:00', '15:30', '16:00', '18:30']);
  assert.deepEqual(
    groups.map((group) => [group.part, group.slots]),
    [
      ['morning', ['09:00', '11:30']],
      ['afternoon', ['12:00', '15:30']],
      ['evening', ['16:00', '18:30']],
    ]
  );
  assert.deepEqual(groupSlotsByDayPart(['17:00']).map((group) => group.part), ['evening']);
  assert.deepEqual(groupSlotsByDayPart([]), []);
});

test('findEarliestSlot waits for earlier days before answering', () => {
  const days = ['d1', 'd2', 'd3'];
  const ready = (...slots: string[]): DayAvailability => ({ status: 'ready', slots });
  assert.equal(findEarliestSlot(days, {}), 'pending');
  // d3 has slots but d1/d2 are unknown: the answer could still change.
  assert.equal(findEarliestSlot(days, { d3: ready('09:00') }), 'pending');
  assert.equal(findEarliestSlot(days, { d1: { status: 'loading' } }), 'pending');
  assert.deepEqual(findEarliestSlot(days, { d1: ready(), d2: ready('10:00', '11:00') }), {
    dayKey: 'd2',
    slot: '10:00',
  });
});

test('findEarliestSlot skips failed days and reports none when all are empty', () => {
  const days = ['d1', 'd2'];
  assert.deepEqual(
    findEarliestSlot(days, {
      d1: { status: 'error', message: 'x' },
      d2: { status: 'ready', slots: ['08:30'] },
    }),
    { dayKey: 'd2', slot: '08:30' }
  );
  assert.equal(
    findEarliestSlot(days, {
      d1: { status: 'ready', slots: [] },
      d2: { status: 'ready', slots: [] },
    }),
    null
  );
});

test('initialsOf ignores the doctor title', () => {
  assert.equal(initialsOf('دکتر مینا رضایی'), 'م\u200cر');
  assert.equal(initialsOf('علی'), 'ع');
});

test('matchesQuery matches Persian/Latin digits and ignores spaces', () => {
  assert.equal(matchesQuery(['علی رضایی', '09121234567'], '۰۹۱۲'), true);
  assert.equal(matchesQuery(['علی رضایی', '09121234567'], 'رضایی'), true);
  assert.equal(matchesQuery(['علی رضایی', null], 'حسینی'), false);
  assert.equal(matchesQuery(['x'], '   '), true);
});
