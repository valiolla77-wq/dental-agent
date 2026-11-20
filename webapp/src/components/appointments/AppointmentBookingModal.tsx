import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Plus } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { upcomingDays } from '../../utils/analytics';
import { formatTimeFa } from '../../utils/persianDate';
import { EarliestSlot, findEarliestSlot } from '../../utils/bookingSlots';
import { AppointmentCreate } from '../../types';
import { BookingTicket } from './booking/BookingTicket';
import { FlowSection, FOCUS_RING } from './booking/FlowSection';
import { DoctorPicker, PatientPicker, ServicePicker, WhenPicker } from './booking/Pickers';
import { useDoctorAvailability } from './booking/useDoctorAvailability';

interface AppointmentBookingModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialDoctorId?: number | null;
  initialServiceId?: number | null;
}

type SectionId = 'patient' | 'service' | 'doctor' | 'when';

const BOOKING_DAYS = 12;

interface Confirmed {
  patientName: string;
  doctorName: string;
  serviceName: string;
  dayKey: string;
  time: string;
  notes: string;
}

/**
 * Manual booking. One continuous flow (patient → service → doctor → day and
 * time) builds an appointment card on the side. Free slots come only from
 * ``GET /appointments/available-slots``; when the server has none (or fails)
 * we say so instead of inventing times.
 */
export const AppointmentBookingModal: React.FC<AppointmentBookingModalProps> = ({
  isOpen,
  onClose,
  initialDoctorId = null,
  initialServiceId = null,
}) => {
  const { doctors, services, patients, bookAppointment, getAvailableSlots } = useClinic();
  const { currentUser } = useAuth();

  const isPatientRole = currentUser?.role === 'patient';
  const activeDoctors = useMemo(() => doctors.filter((doctor) => doctor.is_active), [doctors]);
  const activeServices = useMemo(() => services.filter((service) => service.is_active), [services]);
  const days = useMemo(() => upcomingDays(BOOKING_DAYS), []);

  const [openSection, setOpenSection] = useState<SectionId | null>('service');
  const [patientId, setPatientId] = useState('');
  const [serviceId, setServiceId] = useState('');
  const [doctorId, setDoctorId] = useState('');
  const [dayKey, setDayKey] = useState('');
  const [startTime, setStartTime] = useState('');
  const [notes, setNotes] = useState('');
  const [notesOpen, setNotesOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Confirmed | null>(null);

  const { byDay, refreshDay } = useDoctorAvailability(
    isOpen && !!doctorId,
    doctorId ? Number(doctorId) : null,
    days,
    getAvailableSlots
  );

  // Reset only when the dialog opens, so late-arriving lists never wipe choices.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (isOpen && !wasOpen.current) {
      const preferred =
        patients.find((item) => item.is_account_holder) ||
        patients.find((item) => item.id === currentUser?.patient?.id) ||
        patients[0];
      // A patient account books for itself by default. Staff must choose, so a
      // booking is never made for whoever happens to be first in the list.
      const defaultPatient = isPatientRole && preferred ? String(preferred.id) : '';
      const service =
        initialServiceId && activeServices.some((item) => item.id === initialServiceId)
          ? String(initialServiceId)
          : '';
      const doctor =
        initialDoctorId && activeDoctors.some((item) => item.id === initialDoctorId)
          ? String(initialDoctorId)
          : '';
      setPatientId(defaultPatient);
      setServiceId(service);
      setDoctorId(doctor);
      setDayKey('');
      setStartTime('');
      setNotes('');
      setNotesOpen(false);
      setError(null);
      setConfirmed(null);
      setOpenSection(!defaultPatient ? 'patient' : !service ? 'service' : !doctor ? 'doctor' : 'when');
    }
    wasOpen.current = isOpen;
  }, [isOpen, patients, currentUser?.patient?.id, isPatientRole, initialServiceId, initialDoctorId, activeServices, activeDoctors]);

  const selectedDay = days.find((day) => day.jalali === dayKey) || null;
  const selectedDoctor = activeDoctors.find((item) => String(item.id) === doctorId) || null;
  const selectedService = activeServices.find((item) => String(item.id) === serviceId) || null;
  const selectedPatient = patients.find((item) => String(item.id) === patientId) || null;

  // Drop a chosen time that the latest server answer no longer offers.
  const selectedEntry = selectedDay ? byDay[selectedDay.jalali] : undefined;
  useEffect(() => {
    if (selectedEntry?.status === 'ready' && startTime && !selectedEntry.slots.includes(startTime)) {
      setStartTime('');
    }
  }, [selectedEntry, startTime]);

  const earliest = useMemo(
    () =>
      doctorId
        ? findEarliestSlot(
            days.map((day) => day.jalali),
            byDay
          )
        : 'pending',
    [doctorId, days, byDay]
  );

  const blocked = patients.length === 0 || activeDoctors.length === 0 || activeServices.length === 0;
  const patientStepVisible = !isPatientRole || patients.length > 1;

  const pickService = (id: string) => {
    setServiceId(id);
    setError(null);
    setOpenSection(!patientId ? 'patient' : !doctorId ? 'doctor' : startTime ? null : 'when');
  };
  const pickDoctor = (id: string) => {
    if (id !== doctorId) setStartTime('');
    setDoctorId(id);
    setError(null);
    setOpenSection('when');
  };
  const pickPatient = (id: string) => {
    setPatientId(id);
    setError(null);
    setOpenSection(!serviceId ? 'service' : !doctorId ? 'doctor' : 'when');
  };
  const pickEarliest = (target: EarliestSlot) => {
    setDayKey(target.dayKey);
    setStartTime(target.slot);
    setError(null);
  };
  const toggle = (id: SectionId) => setOpenSection((current) => (current === id ? null : id));

  const missing = !patientId
    ? 'بیمار را انتخاب کنید'
    : !serviceId
    ? 'خدمت را انتخاب کنید'
    : !doctorId
    ? 'پزشک را انتخاب کنید'
    : !selectedDay
    ? 'روز نوبت را انتخاب کنید'
    : !startTime
    ? 'ساعت نوبت را انتخاب کنید'
    : null;
  const canSubmit = !missing && !blocked;

  const submit = async () => {
    if (!canSubmit || !selectedDay || !selectedDoctor || !selectedService) return;
    const payload: AppointmentCreate = {
      doctor_id: Number(doctorId),
      service_id: Number(serviceId),
      appointment_date: selectedDay.jalali,
      appointment_time: startTime,
      patient_id: Number(patientId),
      reason: notes.trim() || undefined,
    };
    setSubmitting(true);
    setError(null);
    try {
      await bookAppointment(payload);
      setConfirmed({
        patientName: selectedPatient?.full_name || '',
        doctorName: selectedDoctor.full_name,
        serviceName: selectedService.name,
        dayKey: selectedDay.jalali,
        time: startTime,
        notes: notes.trim(),
      });
    } catch (err: unknown) {
      // The most common cause is someone else taking the slot first, so
      // re-read the day and let the person pick again.
      const reason = err instanceof Error && err.message ? err.message : 'ثبت نوبت انجام نشد.';
      setError(`${reason} زمان‌های این روز دوباره خوانده شد؛ ساعت دیگری انتخاب کنید.`);
      setStartTime('');
      refreshDay(selectedDay);
      setOpenSection('when');
    } finally {
      setSubmitting(false);
    }
  };

  const ticketProps = {
    day: selectedDay,
    time: startTime,
    serviceName: selectedService?.name,
    doctorName: selectedDoctor?.full_name,
    patientName: selectedPatient?.full_name,
    notes: notes.trim(),
  };

  const submitBlock = (
    <div>
      <Button
        type="button"
        size="lg"
        className="w-full"
        onClick={submit}
        isLoading={submitting}
        disabled={!canSubmit}
        icon={<CheckCircle2 className="h-4 w-4" />}
      >
        ثبت نوبت
      </Button>
      {missing && !blocked && (
        <p className="mt-2 text-center text-small text-muted">{missing}</p>
      )}
    </div>
  );

  const confirmedDay = confirmed ? days.find((day) => day.jalali === confirmed.dayKey) || null : null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={confirmed ? 'نوبت ثبت شد' : 'رزرو نوبت'}
      subtitle={
        confirmed
          ? 'کارت نوبت شما آماده است.'
          : 'ساعت‌های خالی همین حالا از برنامهٔ پزشک خوانده می‌شود.'
      }
      maxWidth="4xl"
    >
      {confirmed ? (
        <div className="mx-auto max-w-sm py-1 text-center">
          <p className="mb-5 text-body leading-6 text-muted">
            نوبت در سامانه ثبت شد و در فهرست نوبت‌ها دیده می‌شود.
          </p>
          <BookingTicket
            status="confirmed"
            day={confirmedDay}
            time={confirmed.time}
            serviceName={confirmed.serviceName}
            doctorName={confirmed.doctorName}
            patientName={confirmed.patientName}
            notes={confirmed.notes}
          />
          <Button className="mt-5 w-full" size="lg" onClick={onClose}>
            بستن
          </Button>
        </div>
      ) : (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div>
            {error && (
              <div
                role="alert"
                className="d-soft-danger mb-4 flex items-start gap-2 px-3.5 py-3 text-small leading-6 text-danger"
              >
                <AlertCircle className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            {blocked && (
              <div className="d-soft-warn mb-4 px-3.5 py-3 text-small leading-6 text-warn">
                {patients.length === 0 && 'هیچ پرونده بیماری در سامانه ثبت نشده است. '}
                {activeDoctors.length === 0 && 'هیچ پزشک فعالی برای رزرو وجود ندارد. '}
                {activeServices.length === 0 && 'هیچ خدمت فعالی برای رزرو وجود ندارد. '}
                تا رفع این مورد، ثبت نوبت ممکن نیست.
              </div>
            )}

            {patientStepVisible && (
              <FlowSection
                id="booking-patient"
                title="بیمار"
                summary={selectedPatient?.full_name}
                isOpen={openSection === 'patient'}
                isDone={!!patientId}
                onToggle={() => toggle('patient')}
              >
                <PatientPicker
                  patients={patients}
                  value={patientId}
                  onChange={pickPatient}
                  isPatientRole={isPatientRole}
                />
              </FlowSection>
            )}

            <FlowSection
              id="booking-service"
              title="خدمت"
              summary={selectedService?.name}
              isOpen={openSection === 'service'}
              isDone={!!serviceId}
              onToggle={() => toggle('service')}
            >
              <ServicePicker services={activeServices} value={serviceId} onChange={pickService} />
            </FlowSection>

            <FlowSection
              id="booking-doctor"
              title="پزشک"
              summary={selectedDoctor?.full_name}
              isOpen={openSection === 'doctor'}
              isDone={!!doctorId}
              onToggle={() => toggle('doctor')}
            >
              <DoctorPicker doctors={activeDoctors} value={doctorId} onChange={pickDoctor} />
            </FlowSection>

            <FlowSection
              id="booking-when"
              title="روز و ساعت"
              summary={
                selectedDay && startTime
                  ? `${selectedDay.label}، ساعت ${formatTimeFa(startTime)}`
                  : null
              }
              hint={doctorId ? undefined : 'ابتدا پزشک را انتخاب کنید'}
              isOpen={openSection === 'when' && !!doctorId}
              isDone={!!selectedDay && !!startTime}
              disabled={!doctorId}
              isLast
              onToggle={() => toggle('when')}
            >
              <WhenPicker
                days={days}
                dayKey={dayKey}
                startTime={startTime}
                availability={byDay}
                earliest={earliest}
                onPickDay={(day) => {
                  if (day.jalali !== dayKey) setStartTime('');
                  setDayKey(day.jalali);
                  setError(null);
                }}
                onPickTime={(slot) => {
                  setStartTime(slot);
                  setError(null);
                }}
                onPickEarliest={pickEarliest}
                onRefresh={refreshDay}
              />
            </FlowSection>

            <div className="mt-1 ps-10">
              {notesOpen ? (
                <div>
                  <label htmlFor="booking-notes" className="d-label">
                    علت مراجعه یا توضیح
                  </label>
                  <textarea
                    id="booking-notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                    maxLength={500}
                    placeholder="مثلاً معاینهٔ دوره‌ای یا پیگیری درمان"
                    className="d-textarea"
                  />
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setNotesOpen(true)}
                  className={`inline-flex items-center gap-1.5 rounded-[8px] py-1 text-small font-semibold text-primary ${FOCUS_RING}`}
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  افزودن توضیح برای پزشک
                </button>
              )}
            </div>
          </div>

          {/* Desktop: the card stays in view while choosing. */}
          <aside className="hidden lg:block">
            <div className="sticky top-0 space-y-4">
              <BookingTicket status="draft" notchColor="#FFFFFF" {...ticketProps} />
              {submitBlock}
            </div>
          </aside>

          {/* Mobile: a compact bar keeps the result and the action reachable. */}
          <div className="sticky bottom-0 z-10 -mx-4 -mb-4 border-t border-line-soft bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:-mb-5 sm:px-6 lg:hidden">
            <div className="mb-2.5 min-h-5 truncate text-small text-ink">
              {selectedDay ? (
                <span className="font-semibold">
                  {selectedDay.label}
                  {startTime ? `، ساعت ${formatTimeFa(startTime)}` : ''}
                  {selectedDoctor ? `، ${selectedDoctor.full_name}` : ''}
                </span>
              ) : (
                <span className="text-muted">هنوز روز و ساعتی انتخاب نشده است.</span>
              )}
            </div>
            {submitBlock}
          </div>
        </div>
      )}
    </Modal>
  );
};
