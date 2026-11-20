import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { Appointment, Patient } from '../../types';
import { formatTimeFa, toPersianDigits, formatToJalali, todayJalaliString } from '../../utils/persianDate';
import {
  lastVisitForPatient,
  sortAppointments,
  isUpcoming,
} from '../../utils/analytics';
import { useClinic } from '../../context/ClinicContext';
import { Button } from '../common/Button';
import { AppointmentStatusBadge, RecordStatusBadge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { EmptyState } from '../common/EmptyState';
import { AppointmentDetailsModal } from '../appointments/AppointmentDetailsModal';
import {
  CalendarDays,
  CalendarPlus,
  ChevronLeft,
  FileWarning,
  RefreshCw,
  Sparkles,
  Stethoscope,
  UserPlus,
  Users,
  BadgeCheck,
  ClipboardList,
  ArrowLeft,
} from 'lucide-react';
import { ErrorBanner, LoadingPanel, SectionCard, StatCard } from '../common/ui';

interface ReceptionistDashboardPanelProps {
  onNavigate: (view: string) => void;
  onBook: () => void;
  onNewPatient: () => void;
}

/**
 * Reception desk: today's queue, patient records and the live worklist of
 * incomplete self-registrations (national id missing). Every row comes from
 * the server; completion persists through ``PUT /patients/{id}``.
 */
export const ReceptionistDashboardPanel: React.FC<ReceptionistDashboardPanelProps> = ({
  onNavigate,
  onBook,
  onNewPatient,
}) => {
  const { appointments, patients, doctors, refreshAll } = useClinic();
  const [incomplete, setIncomplete] = useState<Patient[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [completionPatient, setCompletionPatient] = useState<Patient | null>(null);
  const [nationalId, setNationalId] = useState('');
  const [saving, setSaving] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const today = todayJalaliString();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setIncomplete(await apiClient.getPatientsFiltered({ recordStatus: 'incomplete' }));
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت پرونده‌های ناقص ناکام ماند');
      setIncomplete(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const todayAppointments = useMemo(
    () =>
      sortAppointments(
        appointments.filter(
          (appointment) =>
            appointment.appointment_date === today && appointment.status !== 'cancelled'
        )
      ),
    [appointments, today]
  );

  const upcomingCount = useMemo(
    () => appointments.filter((appointment) => isUpcoming(appointment, today)).length,
    [appointments, today]
  );

  const recentPatients = useMemo(
    () => [...patients].sort((a, b) => b.id - a.id).slice(0, 5),
    [patients]
  );

  const openCompletion = (patient: Patient) => {
    setCompletionPatient(patient);
    setNationalId('');
    setModalError(null);
  };

  const closeCompletion = () => {
    setCompletionPatient(null);
    setNationalId('');
    setModalError(null);
  };

  const submitCompletion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!completionPatient) return;
    const digits = nationalId.trim().replace(/\D/g, '');
    if (digits.length !== 10) {
      setModalError('کد ملی باید دقیقاً ۱۰ رقم باشد.');
      return;
    }
    setSaving(true);
    setModalError(null);
    try {
      await apiClient.updatePatient(completionPatient.id, {
        full_name: completionPatient.full_name,
        phone: completionPatient.phone,
        national_id: digits,
      });
      closeCompletion();
      await Promise.all([load(), refreshAll()]);
    } catch (err: any) {
      setModalError(err.message || 'تکمیل پرونده ناکام ماند');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4">
        <StatCard
          icon={<CalendarDays className="w-[18px] h-[18px]" />}
          label="نوبت‌های امروز"
          value={toPersianDigits(todayAppointments.length)}
          hint={`${toPersianDigits(upcomingCount)} نوبت آینده`}
        />
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="مراجعان ثبت‌شده"
          value={toPersianDigits(patients.length)}
          hint="پرونده‌های موجود در سامانه"
          tone="soft"
        />
        <StatCard
          icon={<Stethoscope className="w-[18px] h-[18px]" />}
          label="پزشکان فعال"
          value={toPersianDigits(doctors.length)}
          hint="کادر درمان قابل انتخاب"
        />
        <StatCard
          icon={<FileWarning className="w-[18px] h-[18px]" />}
          label="پرونده نیازمند تکمیل"
          value={loading ? '…' : toPersianDigits(incomplete?.length ?? 0)}
          hint={
            incomplete && incomplete.length > 0
              ? 'کد ملی این پرونده‌ها ثبت نشده است'
              : 'همه پرونده‌ها کامل هستند'
          }
          tone={incomplete && incomplete.length > 0 ? 'warn' : 'soft'}
        />
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          {
            title: 'ثبت بیمار جدید',
            subtitle: 'ایجاد پرونده در پذیرش',
            icon: UserPlus,
            onClick: onNewPatient,
          },
          {
            title: 'رزرو نوبت',
            subtitle: 'زمان‌بندی برای مراجع',
            icon: CalendarPlus,
            onClick: onBook,
          },
          {
            title: 'پرونده‌ها',
            subtitle: 'جستجو و تکمیل اطلاعات',
            icon: ClipboardList,
            onClick: () => onNavigate('patients'),
          },
          {
            title: 'دستیار پذیرش',
            subtitle: 'گفتگو و اقدام با تأیید شما',
            icon: Sparkles,
            onClick: () => onNavigate('agent'),
          },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.title}
              type="button"
              onClick={item.onClick}
              className="d-card p-4 text-right hover:border-primary-line hover:bg-[#FBFDFD] transition-colors"
            >
              <span className="d-icon-ring mb-3">
                <Icon className="w-4 h-4" />
              </span>
              <span className="block text-small font-bold text-ink">{item.title}</span>
              <span className="block text-caption text-muted mt-1 leading-5">{item.subtitle}</span>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* Today queue */}
        <SectionCard
          className="xl:col-span-2"
          title="صف نوبت‌های امروز"
          subtitle="نوبت‌های غیرلغوشده به ترتیب ساعت"
          action={
            <button type="button" className="d-link" onClick={() => onNavigate('appointments')}>
              همه نوبت‌ها
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
          }
        >
          {todayAppointments.length === 0 ? (
            <EmptyState
              icon={<CalendarDays className="w-5 h-5" />}
              title="امروز نوبتی ثبت نشده است"
              description="برای ثبت نوبت جدید از دکمه رزرو استفاده کنید یا از دستیار پذیرش کمک بگیرید."
              actionLabel="رزرو نوبت"
              onAction={onBook}
            />
          ) : (
            <div className="space-y-2.5">
              {todayAppointments.map((appointment) => (
                <button
                  key={appointment.id}
                  type="button"
                  onClick={() => setSelected(appointment)}
                  className="w-full text-right flex items-center gap-3 p-3 rounded-[12px] border border-line-soft hover:border-primary-line hover:bg-[#FBFDFD] transition-colors"
                >
                  <div className="w-[62px] shrink-0 rounded-[10px] bg-primary-soft border border-primary-line text-primary-deep py-2 text-center">
                    <div className="text-small font-extrabold tabular-nums">
                      {formatTimeFa(appointment.appointment_time)}
                    </div>
                    <div className="text-caption opacity-70 mt-0.5">ساعت</div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-small font-bold text-ink truncate">
                      {appointment.patient_name}
                    </div>
                    <div className="text-caption text-muted mt-1 flex items-center gap-2 flex-wrap">
                      <span>{appointment.service_name}</span>
                      <span className="text-line-strong">•</span>
                      <span>{appointment.doctor_name}</span>
                    </div>
                  </div>
                  <AppointmentStatusBadge status={appointment.status} />
                </button>
              ))}
            </div>
          )}
        </SectionCard>

        {/* Incomplete records */}
        <SectionCard
          title="پرونده‌های نیازمند تکمیل"
          subtitle="ثبت‌نام‌های خودکار بدون کد ملی"
          action={
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="p-1.5 rounded-[8px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
              aria-label="به‌روزرسانی"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          }
        >
          {incomplete === null && loading ? (
            <LoadingPanel message="در حال دریافت پرونده‌ها..." />
          ) : incomplete && incomplete.length === 0 ? (
            <div className="d-soft-teal p-4 text-center">
              <BadgeCheck className="w-6 h-6 text-primary mx-auto mb-2" />
              <div className="text-small font-bold text-primary-deep">همه پرونده‌ها کامل هستند</div>
              <p className="text-caption text-muted mt-1 leading-5">
                هیچ پرونده ناقصی در پایگاه داده گزارش نشده است.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {(incomplete || []).slice(0, 5).map((patient) => (
                <div
                  key={patient.id}
                  className="rounded-[12px] border border-line-soft p-3 flex items-center justify-between gap-2"
                >
                  <div className="min-w-0">
                    <div className="text-small font-bold text-ink truncate">
                      {patient.full_name}
                    </div>
                    <div className="text-caption text-muted mt-1 tabular-nums" dir="ltr">
                      {toPersianDigits(patient.phone)}
                    </div>
                  </div>
                  <Button size="sm" variant="secondary" onClick={() => openCompletion(patient)}>
                    تکمیل
                  </Button>
                </div>
              ))}
              {(incomplete || []).length > 5 && (
                <button
                  type="button"
                  onClick={() => onNavigate('patients')}
                  className="d-link w-full justify-center pt-1"
                >
                  {toPersianDigits((incomplete?.length ?? 0) - 5)} پرونده دیگر
                  <ArrowLeft className="w-3 h-3" />
                </button>
              )}
            </div>
          )}
        </SectionCard>
      </div>

      {/* Recent patients + assistant */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <SectionCard
          className="xl:col-span-2"
          title="آخرین مراجعان"
          subtitle="پنج پرونده اخیر ثبت‌شده در سامانه"
          action={
            <button type="button" className="d-link" onClick={() => onNavigate('patients')}>
              همه پرونده‌ها
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
          }
          noPadding
        >
          {recentPatients.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<Users className="w-5 h-5" />}
                title="هنوز مراجعی ثبت نشده است"
                description="اولین پرونده را از دکمه ثبت بیمار جدید ایجاد کنید."
                actionLabel="ثبت بیمار"
                onAction={onNewPatient}
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="d-table">
                <thead>
                  <tr>
                    <th>مراجع</th>
                    <th>تماس</th>
                    <th>وضعیت پرونده</th>
                    <th>آخرین مراجعه</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {recentPatients.map((patient) => {
                    const lastVisit = lastVisitForPatient(appointments, patient, today);
                    return (
                      <tr key={patient.id}>
                        <td>
                          <div className="flex items-center gap-2.5">
                            <span className="w-7 h-7 rounded-full bg-primary-soft border border-primary-line text-primary-deep text-caption font-bold flex items-center justify-center">
                              {patient.full_name.charAt(0)}
                            </span>
                            <span className="font-semibold text-ink">{patient.full_name}</span>
                          </div>
                        </td>
                        <td className="tabular-nums text-muted" dir="ltr">
                          {toPersianDigits(patient.phone)}
                        </td>
                        <td>
                          <RecordStatusBadge status={patient.record_status} />
                        </td>
                        <td className="text-muted">
                          {lastVisit ? formatToJalali(lastVisit.appointment_date) : 'بدون مراجعه'}
                        </td>
                        <td className="text-left">
                          <button
                            type="button"
                            onClick={() => onNavigate('patients')}
                            className="d-link"
                          >
                            پرونده
                            <ChevronLeft className="w-3 h-3" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        <section className="d-ai-card p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-1.5 text-small font-bold text-ai">
              <Sparkles className="w-3.5 h-3.5" />
              دستیار پذیرش
            </div>
            <h3 className="text-body font-bold text-ink mt-2 leading-6">
              ثبت نوبت و تکمیل اطلاعات با گفتگو
            </h3>
            <p className="text-caption text-muted mt-2 leading-6">
              دستیار فقط پیشنهاد می‌دهد؛ هر تغییر پس از تأیید صریح شما در سرور ثبت می‌شود.
            </p>
            <div className="mt-4 space-y-2 text-caption text-muted">
              <div className="bg-surface/70 border border-ai-line rounded-[10px] px-3 py-2">
                «برای مراجع جدید نوبت دکتر شمس را بررسی کن»
              </div>
              <div className="bg-surface/70 border border-ai-line rounded-[10px] px-3 py-2">
                «پرونده‌های ناقص امروز را نشان بده»
              </div>
            </div>
          </div>
          <Button
            variant="ai"
            size="sm"
            className="w-full mt-5"
            onClick={() => onNavigate('agent')}
            icon={<Sparkles className="w-3.5 h-3.5" />}
          >
            شروع گفتگو
          </Button>
        </section>
      </div>

      <Modal
        isOpen={Boolean(completionPatient)}
        onClose={closeCompletion}
        title="تکمیل پرونده بیمار"
        subtitle={
          completionPatient
            ? `${completionPatient.full_name} — ${toPersianDigits(completionPatient.phone)}`
            : undefined
        }
        maxWidth="md"
      >
        <form onSubmit={submitCompletion} className="space-y-4">
          <div>
            <label className="d-label" htmlFor="completion-national-id">
              کد ملی ۱۰ رقمی
            </label>
            <input
              id="completion-national-id"
              required
              value={nationalId}
              onChange={(e) => setNationalId(e.target.value)}
              placeholder="مثلاً ۰۰۱۲۳۴۵۶۷۸"
              className="d-input tabular-nums"
              dir="ltr"
              inputMode="numeric"
            />
            <p className="text-caption text-faint mt-2 leading-5">
              پس از ثبت، سرور وضعیت پرونده را به «کامل» تغییر می‌دهد. اعداد فارسی نیز پذیرفته می‌شوند.
            </p>
          </div>
          {modalError && (
            <div className="d-soft-danger px-3 py-2 text-caption text-danger">{modalError}</div>
          )}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" size="sm" onClick={closeCompletion}>
              انصراف
            </Button>
            <Button type="submit" size="sm" isLoading={saving}>
              تکمیل پرونده
            </Button>
          </div>
        </form>
      </Modal>

      <AppointmentDetailsModal
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        appointment={selected}
      />
    </div>
  );
};
