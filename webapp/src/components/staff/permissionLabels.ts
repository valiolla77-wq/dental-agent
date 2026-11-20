/**
 * Persian labels and helpers for the staff management surface.
 * Action keys mirror the backend permission catalog (app/auth/permissions.py).
 */

import { UserRole } from '../../types';
import { formatToJalali, formatTimeFa, toPersianDigits } from '../../utils/persianDate';

export const ACTION_LABELS: Record<string, string> = {
  'patient:read': 'مشاهدهٔ پروندهٔ بیماران',
  'patient:create': 'ثبت پروندهٔ بیمار جدید',
  'patient:update': 'ویرایش اطلاعات بیماران',
  'patient:delete': 'حذف پروندهٔ بیمار',
  'patient:link': 'اتصال پرونده به حساب کاربری',
  'patient:search': 'جست‌وجوی بیماران توسط دستیار هوشمند',
  'appointment:read': 'مشاهدهٔ نوبت‌ها',
  'appointment:create': 'ثبت نوبت جدید',
  'appointment:cancel': 'لغو نوبت',
  'appointment:reschedule': 'جابه‌جایی نوبت',
  'clinical:read': 'مشاهدهٔ پروندهٔ بالینی بیماران',
  'clinical:write': 'ثبت یادداشت درمانی و وضعیت دندان',
  'visit_rating:create': 'ثبت رضایت پس از ویزیت',
  'user:create': 'ایجاد حساب کاربری جدید',
  'clinic:read': 'مشاهدهٔ اطلاعات عمومی کلینیک',
  'report:appointments': 'گزارش نوبت‌های کلینیک',
  'report:overview': 'گزارش جامع و آمار کلینیک',
  'report:feedback': 'مرور بازخوردهای کاربران',
};

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  'user.create': 'ایجاد حساب',
  'user.update': 'ویرایش حساب',
  'user.delete': 'حذف حساب',
  'user.self_update': 'به‌روزرسانی حساب توسط کاربر',
  'user.permissions.update': 'تغییر دسترسی‌ها',
  'patient.delete': 'حذف پروندهٔ بیمار',
  'doctor.create': 'ثبت پزشک',
  'doctor.update': 'ویرایش پزشک',
  'doctor.link_user': 'اتصال حساب پزشک',
  'service.create': 'ثبت خدمت',
  'service.update': 'ویرایش خدمت',
  'service.delete': 'حذف خدمت',
  'clinical.entry_create': 'ثبت یادداشت بالینی',
  'clinical.tooth_status': 'ثبت وضعیت دندان',
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] || action;
}

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] || action;
}

/** Roles selectable in the promotion dialog, in display order. */
export const STAFF_ROLE_ORDER: UserRole[] = ['receptionist', 'doctor', 'admin'];

export const STAFF_ROLE_HINTS: Record<string, string> = {
  receptionist: 'پذیرش و نوبت‌دهی؛ ثبت و ویرایش بیماران؛ بدون مدیریت پرسنل.',
  doctor: 'مشاهدهٔ بیماران مجاز و برنامهٔ کاری؛ دسترسی مطالعه.',
  admin: 'دسترسی کامل مدیریتی شامل پرسنل، دسترسی‌ها و گزارش‌ها.',
  patient: 'بیمار؛ فقط درگاه بیماران — در این فهرست مدیریت نمی‌شود.',
};

/**
 * Naive-UTC ISO timestamps (no zone suffix) from the API must be read as UTC
 * before local Jalali rendering, otherwise every zone shows shifted times.
 */
export function utcIsoToJalali(iso: string | null | undefined, withTime = true): string {
  if (!iso) return '—';
  const withZone = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(withZone);
  if (Number.isNaN(date.getTime())) return '—';
  const day = formatToJalali(date, false);
  if (!withTime) return day;
  const hhmm = `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes()
  ).padStart(2, '0')}`;
  return `${day} - ${formatTimeFa(hhmm)}`;
}

/** Persian digit helper re-exported for the staff tables. */
export { toPersianDigits };
