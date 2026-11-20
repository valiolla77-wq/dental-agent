import test from 'node:test';
import assert from 'node:assert/strict';
import { intervalsOverlap, timeToMinutes, minutesToTime, checkAppointmentConflict } from './conflictChecker';
import { Appointment } from '../types';

test('time conversion helpers work correctly', () => {
  assert.equal(timeToMinutes('10:30'), 630);
  assert.equal(minutesToTime(630), '10:30');
});

test('intervalsOverlap catches direct and partial overlaps', () => {
  // Overlapping
  assert.equal(intervalsOverlap('10:00', '11:00', '10:30', '11:30'), true);
  assert.equal(intervalsOverlap('10:00', '11:00', '09:30', '10:30'), true);
  assert.equal(intervalsOverlap('10:00', '11:00', '10:15', '10:45'), true);

  // Adjacent (should not overlap)
  assert.equal(intervalsOverlap('10:00', '11:00', '11:00', '12:00'), false);
  assert.equal(intervalsOverlap('10:00', '11:00', '09:00', '10:00'), false);
});

test('checkAppointmentConflict flags collision with existing doctor appointment', () => {
  const existing: Appointment[] = [
    {
      id: 1,
      doctor_id: 1,
      doctor_name: 'دکتر تهرانی',
      patient_id: 1,
      patient_name: 'رضا کمالی',
      service_id: 1,
      service_name: 'معاینه اولیه',
      appointment_date: '2026-10-25',
      appointment_time: '10:00:00',
      status: 'confirmed',
      reason: 'ویزیت اولیه',
    },
  ];

  const conflict = checkAppointmentConflict(existing, {
    doctor_id: 1,
    date: '2026-10-25',
    start_time: '10:15',
    end_time: '10:45',
  });

  assert.equal(conflict.hasConflict, true);
  assert.equal(conflict.conflictingAppointment?.id, 1);
  assert.ok(conflict.suggestedAlternativeTimes && conflict.suggestedAlternativeTimes.length > 0);

  // Different time slot - no conflict
  const noConflict = checkAppointmentConflict(existing, {
    doctor_id: 1,
    date: '2026-10-25',
    start_time: '11:30',
    end_time: '12:00',
  });

  assert.equal(noConflict.hasConflict, false);
});
