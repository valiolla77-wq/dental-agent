import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatCount,
  formatTimeFa,
  formatToJalali,
  gregorianToJalali,
  jalaliToGregorian,
  toLatinDigits,
  toPersianDigits,
} from './persianDate';

test('toPersianDigits converts digits accurately', () => {
  assert.equal(toPersianDigits(12345), '۱۲۳۴۵');
  assert.equal(toPersianDigits('2026-10-23'), '۲۰۲۶-۱۰-۲۳');
});

test('toLatinDigits converts Persian and Arabic digits back to Latin', () => {
  assert.equal(toLatinDigits('۱۲۳۴۵'), '12345');
  assert.equal(toLatinDigits('٠٩١٢'), '0912');
  assert.equal(toLatinDigits('شماره ۱۲۳'), 'شماره 123');
});

test('formatCount renders a Persian thousands separator', () => {
  assert.equal(formatCount(1284), '۱٬۲۸۴');
  assert.equal(formatCount(0), '۰');
});

test('formatTimeFa keeps HH:MM and uses Persian digits', () => {
  assert.equal(formatTimeFa('09:30:00'), '۰۹:۳۰');
  assert.equal(formatTimeFa('14:05'), '۱۴:۰۵');
  assert.equal(formatTimeFa(null), '—');
});

test('gregorianToJalali accurately converts known Gregorian dates to Solar Hijri', () => {
  // 2024-03-20 is 1403-01-01 (Nowruz)
  const [jy1, jm1, jd1] = gregorianToJalali(2024, 3, 20);
  assert.equal(jy1, 1403);
  assert.equal(jm1, 1);
  assert.equal(jd1, 1);

  // 2026-10-23
  const [jy2, jm2, jd2] = gregorianToJalali(2026, 10, 23);
  assert.equal(jy2, 1405);
  assert.equal(jm2, 8);
  assert.equal(jd2, 1);
});

test('jalaliToGregorian matches known Solar Hijri dates', () => {
  assert.deepEqual(jalaliToGregorian(1403, 1, 1), [2024, 3, 20]);
  assert.deepEqual(jalaliToGregorian(1405, 8, 4), [2026, 10, 26]);
  assert.deepEqual(jalaliToGregorian(1399, 12, 30), [2021, 3, 20]);
});

test('formatToJalali formats date strings with Persian digits', () => {
  assert.equal(formatToJalali('2024-03-20'), '۱۴۰۳/۰۱/۰۱');
  // Backend Jalali strings are padded, never double-converted.
  assert.equal(formatToJalali('1403/8/5'), '۱۴۰۳/۰۸/۰۵');
  assert.equal(formatToJalali('not-a-date'), 'تاریخ نامعتبر');
});

test('formatToJalali can include the Persian weekday and month name', () => {
  assert.equal(formatToJalali('2024-03-20', true), 'چهارشنبه ۱ فروردین ۱۴۰۳');
  assert.equal(formatToJalali('1405/08/04', true), 'دوشنبه ۴ آبان ۱۴۰۵');
});
