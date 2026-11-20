import { UserRole } from '../types';

export type Permission =
  | 'view_dashboard'
  | 'manage_appointments'
  | 'view_my_appointments'
  | 'book_appointment'
  | 'cancel_appointment'
  | 'reschedule_appointment'
  | 'manage_patients'
  | 'view_patient_dossier'
  | 'view_own_health_record'
  | 'view_clinical_records'
  | 'manage_clinical_records'
  | 'rate_visits'
  | 'manage_doctors'
  | 'view_doctors'
  | 'manage_services'
  | 'view_services'
  | 'manage_staff'
  | 'use_agent'
  | 'view_api_spec'
  | 'manage_settings';

export const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  admin: [
    'view_dashboard',
    'manage_appointments',
    'view_my_appointments',
    'book_appointment',
    'cancel_appointment',
    'reschedule_appointment',
    'manage_patients',
    'view_patient_dossier',
    'view_clinical_records',
    'manage_clinical_records',
    'manage_doctors',
    'view_doctors',
    'manage_services',
    'view_services',
    'manage_staff',
    'use_agent',
    'view_api_spec',
    'manage_settings',
  ],
  receptionist: [
    'view_dashboard',
    'manage_appointments',
    'view_my_appointments',
    'book_appointment',
    'cancel_appointment',
    'reschedule_appointment',
    'manage_patients',
    'view_patient_dossier',
    'view_clinical_records',
    'view_doctors',
    'view_services',
    'use_agent',
  ],
  doctor: [
    'view_dashboard',
    'view_my_appointments',
    'view_patient_dossier',
    'view_clinical_records',
    'manage_clinical_records',
    'view_doctors',
    'view_services',
    'use_agent',
  ],
  patient: [
    'view_dashboard',
    'view_my_appointments',
    'book_appointment',
    'cancel_appointment',
    'reschedule_appointment',
    'view_own_health_record',
    'rate_visits',
    'view_doctors',
    'view_services',
    'use_agent',
  ],
};

export const ROLE_LABELS: Record<UserRole, { title: string; subtitle: string }> = {
  admin: {
    title: 'مدیر کلینیک',
    subtitle: 'دسترسی کامل مدیریتی و نظارت سیستمی',
  },
  receptionist: {
    title: 'کارشناس پذیرش',
    subtitle: 'مدیریت پرونده‌ها، نوبت‌دهی و پذیرش بیماران',
  },
  doctor: {
    title: 'دندانپزشک متخصص',
    subtitle: 'مشاهده برنامه‌کاری و سوابق درمانی مراجعین',
  },
  patient: {
    title: 'بیمار',
    subtitle: 'پیگیری نوبت‌ها، پرونده سلامت و دریافت مشاوره از دستیار',
  },
};

export function hasPermission(role: UserRole, permission: Permission): boolean {
  const permissions = ROLE_PERMISSIONS[role];
  return permissions ? permissions.includes(permission) : false;
}
