import { Appointment, DentalService, Doctor, Patient } from '../types';
import {
  JALALI_MONTH_NAMES,
  PERSIAN_WEEKDAYS,
  formatCount,
  formatToJalali,
  gregorianToJalali,
  jalaliToGregorian,
  toPersianDigits,
  todayJalaliString,
} from './persianDate';

export const ACTIVE_APPOINTMENT_STATUSES = ['scheduled', 'confirmed', 'in_progress'];

export interface DayMeta {
  /** Gregorian ISO date, used for native date calculations. */
  iso: string;
  /** Backend Jalali date string, used for filtering API rows. */
  jalali: string;
  weekday: string;
  day: number;
  month: number;
  monthName: string;
  year: number;
  isToday: boolean;
  isPast: boolean;
  /** e.g. «چهارشنبه ۶ آبان» */
  label: string;
  /** e.g. «۶ آبان» */
  shortLabel: string;
}

export function normalizeTime(time: string | null | undefined): string {
  return (time || '').slice(0, 5);
}

export function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function jalaliToDate(jalali: string): Date | null {
  const match = /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})/.exec(jalali || '');
  if (!match) return null;
  const [gy, gm, gd] = jalaliToGregorian(
    Number(match[1]),
    Number(match[2]),
    Number(match[3])
  );
  return new Date(gy, gm - 1, gd);
}

export function dayMetaFromDate(date: Date, today = new Date()): DayMeta {
  const [jy, jm, jd] = gregorianToJalali(
    date.getFullYear(),
    date.getMonth() + 1,
    date.getDate()
  );
  const jalali = `${jy}/${String(jm).padStart(2, '0')}/${String(jd).padStart(2, '0')}`;
  const weekday = PERSIAN_WEEKDAYS[date.getDay()];
  const monthName = JALALI_MONTH_NAMES[jm - 1];
  const isToday = toIsoDate(date) === toIsoDate(today);
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return {
    iso: toIsoDate(date),
    jalali,
    weekday,
    day: jd,
    month: jm,
    monthName,
    year: jy,
    isToday,
    isPast: startOfDate.getTime() < startOfToday.getTime(),
    label: `${weekday} ${toPersianDigits(jd)} ${monthName}`,
    shortLabel: `${weekday} ${toPersianDigits(jd)}`,
  };
}

/** Today and the next `count - 1` days (used by the booking wizard). */
export function upcomingDays(count = 14): DayMeta[] {
  const today = new Date();
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + index);
    return dayMetaFromDate(date, today);
  });
}

/** Saturday → Friday of the week containing `anchor`. */
export function currentWeekDays(anchor = new Date()): DayMeta[] {
  const day = anchor.getDay(); // 0 = Sunday … 6 = Saturday
  const daysSinceSaturday = (day + 1) % 7;
  const start = new Date(
    anchor.getFullYear(),
    anchor.getMonth(),
    anchor.getDate() - daysSinceSaturday
  );
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
    return dayMetaFromDate(date, anchor);
  });
}

/** Today and the previous `count - 1` days, oldest first. */
export function lastDays(count: number): DayMeta[] {
  const today = new Date();
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(
      today.getFullYear(),
      today.getMonth(),
      today.getDate() - (count - 1 - index)
    );
    return dayMetaFromDate(date, today);
  });
}

export function jalaliDaysAgo(days: number): string {
  const today = new Date();
  const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days);
  return dayMetaFromDate(date, today).jalali;
}

export function formatWeekRange(days: DayMeta[]): string {
  if (!days.length) return '';
  const first = days[0];
  const last = days[days.length - 1];
  if (first.month === last.month && first.year === last.year) {
    return `${toPersianDigits(first.day)} تا ${toPersianDigits(last.day)} ${last.monthName} ${toPersianDigits(last.year)}`;
  }
  return `${toPersianDigits(first.day)} ${first.monthName} تا ${toPersianDigits(last.day)} ${last.monthName} ${toPersianDigits(last.year)}`;
}

export function isActiveAppointment(appointment: Appointment): boolean {
  return appointment.status !== 'cancelled';
}

export function sortAppointments(appointments: Appointment[]): Appointment[] {
  return [...appointments].sort((a, b) => {
    const byDate = (a.appointment_date || '').localeCompare(b.appointment_date || '');
    if (byDate !== 0) return byDate;
    return normalizeTime(a.appointment_time).localeCompare(normalizeTime(b.appointment_time));
  });
}

export function isUpcoming(appointment: Appointment, today = todayJalaliString()): boolean {
  return appointment.appointment_date >= today && appointment.status !== 'cancelled';
}

export function isToday(appointment: Appointment, today = todayJalaliString()): boolean {
  return appointment.appointment_date === today;
}

export interface AppointmentStats {
  today: number;
  upcoming: number;
  completed: number;
  cancelled: number;
  scheduled: number;
  total: number;
}

export function getAppointmentStats(
  appointments: Appointment[],
  today = todayJalaliString()
): AppointmentStats {
  let stats: AppointmentStats = {
    today: 0,
    upcoming: 0,
    completed: 0,
    cancelled: 0,
    scheduled: 0,
    total: appointments.length,
  };
  for (const appointment of appointments) {
    if (appointment.appointment_date === today && appointment.status !== 'cancelled') {
      stats.today += 1;
    }
    if (isUpcoming(appointment, today)) stats.upcoming += 1;
    if (appointment.status === 'completed') stats.completed += 1;
    if (appointment.status === 'cancelled') stats.cancelled += 1;
    if (appointment.status === 'scheduled' || appointment.status === 'confirmed') {
      stats.scheduled += 1;
    }
  }
  return stats;
}

export interface ServiceMetric {
  serviceId: number;
  name: string;
  total: number;
  completed: number;
  cancelled: number;
  upcoming: number;
}

export function getServiceBreakdown(
  appointments: Appointment[],
  services: DentalService[] = [],
  today = todayJalaliString()
): ServiceMetric[] {
  const map = new Map<number, ServiceMetric>();
  for (const service of services) {
    map.set(service.id, {
      serviceId: service.id,
      name: service.name,
      total: 0,
      completed: 0,
      cancelled: 0,
      upcoming: 0,
    });
  }
  for (const appointment of appointments) {
    const current =
      map.get(appointment.service_id) ||
      {
        serviceId: appointment.service_id,
        name: appointment.service_name || 'خدمت بدون عنوان',
        total: 0,
        completed: 0,
        cancelled: 0,
        upcoming: 0,
      };
    current.total += 1;
    if (appointment.status === 'completed') current.completed += 1;
    if (appointment.status === 'cancelled') current.cancelled += 1;
    if (isUpcoming(appointment, today)) current.upcoming += 1;
    map.set(appointment.service_id, current);
  }
  return Array.from(map.values())
    .filter((metric) => metric.total > 0)
    .sort((a, b) => b.total - a.total);
}

export interface DoctorLoad {
  doctorId: number;
  name: string;
  count: number;
}

export function getDoctorLoad(
  appointments: Appointment[],
  doctors: Doctor[] = []
): DoctorLoad[] {
  const map = new Map<number, DoctorLoad>();
  for (const doctor of doctors) {
    map.set(doctor.id, { doctorId: doctor.id, name: doctor.full_name, count: 0 });
  }
  for (const appointment of appointments) {
    if (appointment.status === 'cancelled') continue;
    const current =
      map.get(appointment.doctor_id) ||
      {
        doctorId: appointment.doctor_id,
        name: appointment.doctor_name || 'پزشک',
        count: 0,
      };
    current.count += 1;
    map.set(appointment.doctor_id, current);
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count);
}

export function countByDay(appointments: Appointment[], days: DayMeta[]): number[] {
  const counts = new Map(days.map((day) => [day.jalali, 0]));
  for (const appointment of appointments) {
    if (appointment.status === 'cancelled') continue;
    if (counts.has(appointment.appointment_date)) {
      counts.set(appointment.appointment_date, (counts.get(appointment.appointment_date) || 0) + 1);
    }
  }
  return days.map((day) => counts.get(day.jalali) || 0);
}

export function lastVisitForPatient(
  appointments: Appointment[],
  patient: Patient,
  today = todayJalaliString()
): Appointment | null {
  const rows = appointments
    .filter(
      (appointment) =>
        (appointment.patient_id === patient.id ||
          appointment.patient_name === patient.full_name) &&
        appointment.appointment_date <= today &&
        appointment.status !== 'cancelled'
    )
    .sort((a, b) => b.appointment_date.localeCompare(a.appointment_date));
  return rows[0] || null;
}

export function nextVisitForPatient(
  appointments: Appointment[],
  patient: Patient,
  today = todayJalaliString()
): Appointment | null {
  return (
    sortAppointments(
      appointments.filter(
        (appointment) =>
          (appointment.patient_id === patient.id ||
            appointment.patient_name === patient.full_name) &&
          appointment.appointment_date >= today &&
          appointment.status !== 'cancelled'
      )
    )[0] || null
  );
}

export function formatAppointmentDate(date: string): string {
  return formatToJalali(date);
}

export function formatDateWithWeekday(date: string): string {
  return formatToJalali(date, true);
}

export function formatPercent(value: number, total: number): string {
  if (!total) return '۰٪';
  return `${toPersianDigits(Math.round((value / total) * 100))}٪`;
}

export function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

export function formatNumber(value: number): string {
  return formatCount(value);
}
