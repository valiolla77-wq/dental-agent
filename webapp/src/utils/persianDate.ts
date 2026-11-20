/**
 * Precise Persian (Solar Hijri / Jalali) Date & Number Utilities
 */

const PERSIAN_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
const LATIN_DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

/**
 * Renders Latin numerals with Persian glyphs. Vazirmatn (bundled with the app)
 * includes the full Arabic-Indic digit set, so this is safe in every UI locale.
 */
export function toPersianDigits(num: number | string): string {
  const value = String(num);
  return value.replace(/[0-9]/g, (digit) => PERSIAN_DIGITS[LATIN_DIGITS.indexOf(digit)]);
}

/** Converts Persian/Arabic digits back to Latin (useful before API calls). */
export function toLatinDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, (digit) => String(PERSIAN_DIGITS.indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit)));
}

/** Persian thousands separator, e.g. ۱٬۲۸۴. */
export function formatCount(value: number): string {
  return toPersianDigits(new Intl.NumberFormat('en-US').format(value)).replace(/,/g, '٬');
}

/** HH:MM:SS / HH:MM → ۱۰:۳۰ */
export function formatTimeFa(time: string | null | undefined): string {
  if (!time) return '—';
  return toPersianDigits(String(time).slice(0, 5));
}

// Format numbers as Persian currency (Toman)
export function formatToman(amount: number): string {
  const formatted = new Intl.NumberFormat('en-US').format(amount);
  return `${toPersianDigits(formatted)} تومان`;
}


// Gregorian to Jalali conversion algorithm
export function gregorianToJalali(gy: number, gm: number, gd: number): [number, number, number] {
  const g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  let jy: number;
  if (gy > 1600) {
    jy = 979;
    gy -= 1600;
  } else {
    jy = 0;
    gy -= 621;
  }
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days =
    365 * gy +
    Math.floor((gy2 + 3) / 4) -
    Math.floor((gy2 + 99) / 100) +
    Math.floor((gy2 + 399) / 400) -
    80 +
    gd +
    g_d_m[gm - 1];
  jy += 33 * Math.floor(days / 12053);
  days %= 12053;
  jy += 4 * Math.floor(days / 1461);
  days %= 1461;
  if (days > 365) {
    jy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }
  let jm: number;
  let jd: number;
  if (days < 186) {
    jm = 1 + Math.floor(days / 31);
    jd = 1 + (days % 31);
  } else {
    jm = 7 + Math.floor((days - 186) / 30);
    jd = 1 + ((days - 186) % 30);
  }
  return [jy, jm, jd];
}

// Jalali to Gregorian conversion algorithm (for weekday lookups). This is the
// well-tested JDF formula; simpler variants can drift by one day around leap
// years, which produced wrong weekday labels in booking summaries.
export function jalaliToGregorian(jy: number, jm: number, jd: number): [number, number, number] {
  let gy = jy <= 979 ? 621 : 1600;
  jy -= jy <= 979 ? 0 : 979;
  let days =
    365 * jy +
    Math.floor(jy / 33) * 8 +
    Math.floor(((jy % 33) + 3) / 4) +
    78 +
    jd +
    (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
  gy += 400 * Math.floor(days / 146097);
  days %= 146097;
  if (days > 36524) {
    days -= 1;
    gy += 100 * Math.floor(days / 36524);
    days %= 36524;
    if (days >= 365) days += 1;
  }
  gy += 4 * Math.floor(days / 1461);
  days %= 1461;
  if (days > 365) {
    gy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }
  let gd = days + 1;
  const leap = (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0;
  const g_d_m = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let gm = 0;
  for (gm = 0; gm < 13 && gd > g_d_m[gm]; gm++) gd -= g_d_m[gm];
  return [gy, gm, gd];
}

// Jalali Month Names
export const JALALI_MONTH_NAMES = [
  'فروردین',
  'اردیبهشت',
  'خرداد',
  'تیر',
  'مرداد',
  'شهریور',
  'مهر',
  'آبان',
  'آذر',
  'دی',
  'بهمن',
  'اسفند',
];

export const PERSIAN_WEEKDAYS = [
  'یکشنبه',
  'دوشنبه',
  'سه‌شنبه',
  'چهارشنبه',
  'پنج‌شنبه',
  'جمعه',
  'شنبه',
];

// Format "today" in backend Jalali string form (e.g. "1405/08/01"). The API
// speaks Jalali for appointment_date end to end.
export function todayJalaliString(): string {
  const d = new Date();
  const [jy, jm, jd] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  return `${jy}/${String(jm).padStart(2, '0')}/${String(jd).padStart(2, '0')}`;
}

// Convert a Gregorian ISO date (YYYY-MM-DD, e.g. from <input type="date">)
// into the backend's Jalali string (without Persian digits).
export function toBackendJalali(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim());
  if (!match) return isoDate;
  const [gy, gm, gd] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const [jy, jm, jd] = gregorianToJalali(gy, gm, gd);
  return `${jy}/${String(jm).padStart(2, '0')}/${String(jd).padStart(2, '0')}`;
}

const JALALI_STRING_RE = /^\s*(1[1-5]\d{2})\/(\d{1,2})\/(\d{1,2})\s*$/;
const GREGORIAN_ISO_RE = /^(\d{4})-(\d{1,2})-(\d{1,2})\s*$/;

// Convert standard date string (YYYY-MM-DD) or Date to Jalali string "1403/08/15".
// Backend Jalali strings (e.g. from the appointments API) are passed through
// instead of being double-converted, with any missing zero-padding restored.
export function formatToJalali(dateInput: string | Date, includeWeekday = false): string {
  if (typeof dateInput === 'string') {
    const jalaliMatch = JALALI_STRING_RE.exec(dateInput);
    if (jalaliMatch) {
      const jy = Number(jalaliMatch[1]);
      const jm = Number(jalaliMatch[2]);
      const jd = Number(jalaliMatch[3]);
      if (jm < 1 || jm > 12 || jd < 1 || jd > 31) return 'تاریخ نامعتبر';
      const monthName = JALALI_MONTH_NAMES[jm - 1];
      const padded = `${toPersianDigits(jy)}/${toPersianDigits(
        String(jm).padStart(2, '0')
      )}/${toPersianDigits(String(jd).padStart(2, '0'))}`;
      if (includeWeekday) {
        const [gy, gm, gd] = jalaliToGregorian(jy, jm, jd);
        const weekday = PERSIAN_WEEKDAYS[new Date(gy, gm - 1, gd).getDay()];
        return `${weekday} ${toPersianDigits(jd)} ${monthName} ${toPersianDigits(jy)}`;
      }
      return padded;
    }
  }

  let d: Date;
  const gregorianMatch = typeof dateInput === 'string' ? GREGORIAN_ISO_RE.exec(dateInput) : null;
  if (gregorianMatch) {
    // Avoid new Date("YYYY-MM-DD") which parses as UTC and shifts the day.
    d = new Date(Number(gregorianMatch[1]), Number(gregorianMatch[2]) - 1, Number(gregorianMatch[3]));
  } else {
    d = typeof dateInput === 'string' ? new Date(dateInput) : dateInput;
  }
  if (isNaN(d.getTime())) return 'تاریخ نامعتبر';

  const [jy, jm, jd] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const monthName = JALALI_MONTH_NAMES[jm - 1];

  if (includeWeekday) {
    const weekday = PERSIAN_WEEKDAYS[d.getDay()];
    return `${weekday} ${toPersianDigits(jd)} ${monthName} ${toPersianDigits(jy)}`;
  }

  const mm = String(jm).padStart(2, '0');
  const dd = String(jd).padStart(2, '0');
  return `${toPersianDigits(jy)}/${toPersianDigits(mm)}/${toPersianDigits(dd)}`;
}

// Calculate standard duration display
export function formatMinutes(mins: number): string {
  return `${toPersianDigits(mins)} دقیقه`;
}
