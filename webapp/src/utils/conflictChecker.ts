import { Appointment } from '../types';

export interface ConflictResult {
  hasConflict: boolean;
  conflictingAppointment?: Appointment;
  message?: string;
  suggestedAlternativeTimes?: string[];
}

// Convert "HH:MM" or "HH:MM:SS" to total minutes from midnight
export function timeToMinutes(timeStr: string): number {
  if (!timeStr) return 0;
  const parts = timeStr.split(':');
  const h = parseInt(parts[0], 10) || 0;
  const m = parseInt(parts[1], 10) || 0;
  return h * 60 + m;
}

// Convert total minutes to "HH:MM"
export function minutesToTime(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

// Check if two time intervals overlap: [s1, e1) and [s2, e2)
export function intervalsOverlap(
  start1: string,
  end1: string,
  start2: string,
  end2: string
): boolean {
  const s1 = timeToMinutes(start1);
  const e1 = timeToMinutes(end1);
  const s2 = timeToMinutes(start2);
  const e2 = timeToMinutes(end2);
  return s1 < e2 && e1 > s2;
}

// Get standardized [start, end] for an appointment
export function getAppointmentInterval(app: Appointment, defaultDurationMinutes = 30): { start: string; end: string } {
  const start = app.appointment_time.slice(0, 5);
  const startMins = timeToMinutes(start);
  const end = minutesToTime(startMins + defaultDurationMinutes);
  return { start, end };
}

// Check for conflicts against existing appointments
export function checkAppointmentConflict(
  appointments: Appointment[],
  newAppointment: {
    doctor_id: number;
    patient_id?: number | null;
    date: string;
    start_time: string;
    end_time: string;
    excludeAppointmentId?: number;
  }
): ConflictResult {
  const sameDayAppointments = appointments.filter(
    (app) =>
      app.appointment_date === newAppointment.date &&
      app.status !== 'cancelled' &&
      app.id !== newAppointment.excludeAppointmentId
  );

  // Check doctor overlap
  const doctorConflict = sameDayAppointments.find((app) => {
    if (app.doctor_id !== newAppointment.doctor_id) return false;
    const interval = getAppointmentInterval(app);
    return intervalsOverlap(
      interval.start,
      interval.end,
      newAppointment.start_time,
      newAppointment.end_time
    );
  });

  if (doctorConflict) {
    const conflictInterval = getAppointmentInterval(doctorConflict);
    const duration =
      timeToMinutes(newAppointment.end_time) - timeToMinutes(newAppointment.start_time);
    const suggested: string[] = [];
    const clinicStart = 9 * 60; // 09:00
    const clinicEnd = 18 * 60;  // 18:00

    for (let slot = clinicStart; slot + duration <= clinicEnd; slot += 30) {
      const slotStart = minutesToTime(slot);
      const slotEnd = minutesToTime(slot + duration);
      const hasSlotConflict = sameDayAppointments.some((app) => {
        if (app.doctor_id !== newAppointment.doctor_id) return false;
        const interval = getAppointmentInterval(app);
        return intervalsOverlap(interval.start, interval.end, slotStart, slotEnd);
      });
      if (!hasSlotConflict && slotStart !== newAppointment.start_time) {
        suggested.push(slotStart);
        if (suggested.length >= 3) break;
      }
    }

    return {
      hasConflict: true,
      conflictingAppointment: doctorConflict,
      message: `تداخل زمانی: پزشک در ساعت ${conflictInterval.start} تا ${conflictInterval.end} نوبت دیگری دارد.`,
      suggestedAlternativeTimes: suggested,
    };
  }

  // Check patient overlap if patient_id is provided
  if (newAppointment.patient_id) {
    const patientConflict = sameDayAppointments.find((app) => {
      if (app.patient_id !== newAppointment.patient_id) return false;
      const interval = getAppointmentInterval(app);
      return intervalsOverlap(
        interval.start,
        interval.end,
        newAppointment.start_time,
        newAppointment.end_time
      );
    });

    if (patientConflict) {
      const pInterval = getAppointmentInterval(patientConflict);
      return {
        hasConflict: true,
        conflictingAppointment: patientConflict,
        message: `تداخل زمانی: بیمار در ساعت ${pInterval.start} تا ${pInterval.end} نوبت همزمان دارد.`,
      };
    }
  }

  return { hasConflict: false };
}
