import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useClinic } from '../../context/ClinicContext';
import { apiClient } from '../../api/client';
import { Appointment } from '../../types';
import { formatTimeFa, toPersianDigits, formatToJalali, todayJalaliString } from '../../utils/persianDate';
import {
  isUpcoming,
  sortAppointments,
} from '../../utils/analytics';
import { AppointmentStatusBadge } from '../common/Badge';
import { Button } from '../common/Button';
import { AppointmentDetailsModal } from '../appointments/AppointmentDetailsModal';
import {
  CalendarDays,
  CalendarPlus,
  CheckCircle2,
  ClipboardList,
  HeartPulse,
  RefreshCw,
  Sparkles,
  Stethoscope,
  UserRound,
  XCircle,
} from 'lucide-react';
import {
  ErrorBanner,
  InfoBanner,
  LoadingPanel,
  SectionCard,
  StatCard,
} from '../common/ui';

interface PatientDashboardPanelProps {
  onNavigate: (view: string) => void;
  onBook: () => void;
}

/**
 * Patient home: the patient sees only their own appointments from
 * ``GET /appointments/me`` (server-derived from the authenticated account).
 * No medical advice or invented content is shown here.
 */
export const PatientDashboardPanel: React.FC<PatientDashboardPanelProps> = ({
  onNavigate,
  onBook,
}) => {
  const { currentUser } = useAuth();
  const { appointments: clinicAppointments } = useClinic();
  const patientRecords =
    currentUser?.patients && currentUser.patients.length > 0
      ? currentUser.patients
      : currentUser?.patient
        ? [currentUser.patient]
        : [];
  const hasRecords = patientRecords.length > 0;

  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Appointment | null>(null);

  const today = todayJalaliString();

  const load = useCallback(async () => {
    if (!hasRecords) {
      // The account is not linked to a patient record. Calling
      // `/appointments/me` here would return an expected 403 on every load.
      setAppointments([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      // The endpoint already scopes to every record owned by this account.
      const list = await apiClient.getMyAppointments();
      setAppointments(list);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت نوبت‌های شما ناکام ماند');
      setAppointments(null);
    } finally {
      setLoading(false);
    }
  }, [hasRecords]);

  useEffect(() => {
    load();
  }, [load]);

  // The booking modal and the agent both refresh the clinic-wide appointment
  // list in context. Mirror that live list so a newly booked family
  // appointment appears without a page reload.
  useEffect(() => {
    if (hasRecords) {
      setAppointments(clinicAppointments);
    }
  }, [hasRecords, clinicAppointments]);

  const rows = appointments ?? [];
  const upcoming = useMemo(
    () => sortAppointments(rows.filter((appointment) => isUpcoming(appointment, today))),
    [rows, today]
  );
  const past = useMemo(
    () =>
      [...rows]
        .filter((appointment) => appointment.appointment_date < today || appointment.status === 'completed')
        .sort((a, b) => b.appointment_date.localeCompare(a.appointment_date))
        .slice(0, 5),
    [rows, today]
  );
  const completed = rows.filter((appointment) => appointment.status === 'completed').length;
  const cancelled = rows.filter((appointment) => appointment.status === 'cancelled').length;
  const next = upcoming[0] || null;

  if (!hasRecords) {
    return (
      <div className="space-y-4">
        <InfoBanner
          tone="warning"
          icon={<ClipboardList className="w-4 h-4" />}
          title="حساب شما هنوز پرونده ندارد"
        >
          حساب شما ساخته شده اما پرونده‌ای به آن متصل نیست. برای ثبت‌نام، در گفتگو با دستیار نام،
          کد ملی و شماره تلفن را ثبت کنید؛ فرم ثبت‌نام به‌صورت خودکار باز می‌شود. تا تکمیل پرونده،
          رزرو نوبت و گفتگو غیرفعال است.
        </InfoBanner>
        <Button
          variant="ai"
          size="md"
          onClick={() => onNavigate('agent')}
          icon={<Sparkles className="w-4 h-4" />}
        >
          ثبت‌نام در گفتگو با دستیار
        </Button>
      </div>
    );
  }

  if (loading && appointments === null) {
    return <LoadingPanel message="در حال دریافت نوبت‌های شما..." />;
  }

  return (
    <div className="space-y-5">
      {error && <ErrorBanner message={error} onRetry={load} />}

      {/* Next appointment highlight */}
      <section className="d-card overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-[1.6fr_1fr]">
          <div className="p-5 sm:p-6">
            <div className="flex items-center gap-2 text-caption font-bold text-primary">
              <CalendarDays className="w-4 h-4" />
              نوبت بعدی شما
            </div>

            {next ? (
              <>
                <div className="mt-4 flex items-start gap-4">
                  <div className="w-[76px] shrink-0 rounded-[14px] bg-primary-soft border border-primary-line text-center py-3">
                    <div className="text-caption text-primary-deep opacity-75">ساعت</div>
                    <div className="text-[19px] font-extrabold text-primary-deep tabular-nums leading-7">
                      {formatTimeFa(next.appointment_time)}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-[17px] font-extrabold text-ink leading-7">
                      {next.service_name}
                    </h2>
                    <p className="text-small text-muted mt-1.5 flex items-center gap-1.5">
                      <UserRound className="w-3.5 h-3.5" />
                      {next.patient_name}
                    </p>
                    <p className="text-small text-muted mt-1.5 flex items-center gap-1.5">
                      <Stethoscope className="w-3.5 h-3.5" />
                      {next.doctor_name}
                    </p>
                    <p className="text-small text-muted mt-1.5 flex items-center gap-1.5">
                      <CalendarDays className="w-3.5 h-3.5" />
                      {formatToJalali(next.appointment_date, true)}
                    </p>
                    <div className="mt-2.5">
                      <AppointmentStatusBadge status={next.status} />
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-5 flex-wrap">
                  <Button size="sm" onClick={() => setSelected(next)}>
                    جزئیات و مدیریت نوبت
                  </Button>
                  <Button size="sm" variant="outline" onClick={onBook} icon={<CalendarPlus className="w-3.5 h-3.5" />}>
                    رزرو نوبت جدید
                  </Button>
                </div>
              </>
            ) : (
              <>
                <h2 className="text-[17px] font-extrabold text-ink mt-4">
                  نوبت فعالی در پیش ندارید
                </h2>
                <p className="text-small text-muted mt-2 leading-6 max-w-md">
                  برای انتخاب خدمت، پزشک و ساعت، از دکمه رزرو استفاده کنید. زمان‌های نمایش‌داده‌شده
                  مستقیماً از سرور خوانده می‌شوند.
                </p>
                <Button
                  size="sm"
                  className="mt-4"
                  onClick={onBook}
                  icon={<CalendarPlus className="w-3.5 h-3.5" />}
                >
                  رزرو نوبت جدید
                </Button>
              </>
            )}
          </div>

          <div className="relative bg-primary p-5 sm:p-6 text-on-accent flex flex-col justify-between overflow-hidden">
            <div className="absolute -left-8 -top-10 w-36 h-36 rounded-full border border-surface/10" />
            <div className="absolute -left-3 -top-4 w-24 h-24 rounded-full border border-surface/10" />
            <div className="relative">
              <Sparkles className="w-5 h-5 text-primary-line" />
              <h3 className="text-body font-bold mt-3 leading-6">دستیار شخصی شما</h3>
              <p className="text-caption text-on-accent/75 mt-1.5 leading-6">
                رزرو، تغییر زمان یا لغو نوبت با گفتگوی فارسی؛ همه اقدام‌ها پیش از ثبت، از شما تأیید
                می‌گیرند.
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              className="mt-5 w-full bg-surface text-primary-deep border-surface hover:bg-canvas"
              onClick={() => onNavigate('agent')}
              icon={<Sparkles className="w-3.5 h-3.5" />}
            >
              گفتگو با دستیار
            </Button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4">
        <StatCard
          icon={<CalendarDays className="w-[18px] h-[18px]" />}
          label="نوبت‌های پیش‌رو"
          value={toPersianDigits(upcoming.length)}
          hint="به ترتیب نزدیک‌ترین زمان"
        />
        <StatCard
          icon={<CheckCircle2 className="w-[18px] h-[18px]" />}
          label="ویزیت‌های تکمیل‌شده"
          value={toPersianDigits(completed)}
          hint="ثبت‌شده در پرونده شما"
          tone="soft"
        />
        <StatCard
          icon={<XCircle className="w-[18px] h-[18px]" />}
          label="نوبت‌های لغوشده"
          value={toPersianDigits(cancelled)}
          hint="با امکان رزرو مجدد"
          tone="danger"
        />
        <StatCard
          icon={<UserRound className="w-[18px] h-[18px]" />}
          label="پرونده‌های این حساب"
          value={toPersianDigits(patientRecords.length)}
          hint={
            patientRecords.length > 1
              ? 'صاحب حساب و اعضای خانواده'
              : patientRecords[0]?.full_name || undefined
          }
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <SectionCard
          className="xl:col-span-2"
          title="نوبت‌های پیش‌رو"
          subtitle="همه نوبت‌های فعال حساب شما"
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
          {upcoming.length === 0 ? (
            <div className="d-empty">
              <div className="d-empty-icon">
                <CalendarDays className="w-5 h-5" />
              </div>
              <h4 className="text-body font-bold text-ink mb-1">نوبت فعالی ندارید</h4>
              <p className="text-small text-muted leading-6 mb-4">
                برای رزرو نوبت جدید از دکمه زیر استفاده کنید.
              </p>
              <Button size="sm" onClick={onBook}>
                رزرو نوبت
              </Button>
            </div>
          ) : (
            <div className="space-y-2.5">
              {upcoming.map((appointment) => (
                <button
                  key={appointment.id}
                  type="button"
                  onClick={() => setSelected(appointment)}
                  className="w-full text-right flex items-center gap-3 p-3 rounded-[12px] border border-line-soft hover:border-primary-line hover:bg-[#FBFDFD] transition-colors"
                >
                  <div className="w-[58px] shrink-0 rounded-[10px] bg-canvas border border-line text-ink py-2 text-center">
                    <div className="text-small font-extrabold tabular-nums">
                      {formatTimeFa(appointment.appointment_time)}
                    </div>
                    <div className="text-caption text-faint mt-0.5">ساعت</div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-small font-bold text-ink truncate">
                      {appointment.service_name}
                    </div>
                    <div className="text-caption text-muted mt-1 flex items-center gap-2 flex-wrap">
                      <span>{formatToJalali(appointment.appointment_date)}</span>
                      <span className="text-line-strong">•</span>
                      <span>{appointment.doctor_name}</span>
                      <span className="text-line-strong">•</span>
                      <span className="font-semibold text-primary">
                        {appointment.patient_name}
                      </span>
                    </div>
                  </div>
                  <AppointmentStatusBadge status={appointment.status} />
                </button>
              ))}
            </div>
          )}
        </SectionCard>

        <div className="space-y-5">
          <SectionCard title="دسترسی سریع">
            <div className="grid grid-cols-2 gap-2.5">
              {[
                { label: 'رزرو نوبت', icon: CalendarPlus, onClick: onBook },
                { label: 'نوبت‌های من', icon: CalendarDays, onClick: () => onNavigate('appointments') },
                { label: 'پرونده سلامت', icon: HeartPulse, onClick: () => onNavigate('health') },
                { label: 'دستیار من', icon: Sparkles, onClick: () => onNavigate('agent') },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.label}
                    type="button"
                    onClick={item.onClick}
                    className="rounded-[12px] border border-line bg-surface p-3 text-center hover:border-primary-line hover:bg-[#FBFDFD] transition-colors"
                  >
                    <Icon className="w-4 h-4 text-primary mx-auto mb-2" />
                    <span className="text-caption font-semibold text-ink">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </SectionCard>

          <SectionCard
            title="بیماران این حساب"
            subtitle="نوبت‌ها برای هر پرونده جداگانه ثبت می‌شوند"
          >
            <div className="space-y-2">
              {patientRecords.map((patient) => (
                <div
                  key={patient.id}
                  className="flex items-center gap-2 rounded-[10px] border border-line-soft bg-surface-muted px-3 py-2"
                >
                  <div className="w-7 h-7 rounded-full bg-primary-soft text-primary flex items-center justify-center shrink-0">
                    <UserRound className="w-3.5 h-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-caption font-bold text-ink truncate">
                      {patient.full_name}
                    </div>
                    <div className="text-caption text-faint mt-0.5">
                      {patient.is_account_holder ? 'صاحب حساب' : 'عضو خانواده'}
                    </div>
                  </div>
                </div>
              ))}
              <Button
                size="sm"
                variant="outline"
                className="w-full mt-1"
                onClick={() => onNavigate('agent')}
                icon={<CalendarPlus className="w-3.5 h-3.5" />}
              >
                افزودن بیمار دیگر
              </Button>
            </div>
          </SectionCard>

          <SectionCard
            title="آخرین مراجعات"
            subtitle="پنج رکورد اخیر پرونده شما"
            noPadding
          >
            {past.length === 0 ? (
              <div className="p-5 text-center text-caption text-muted">
                هنوز مراجعه‌ای در پرونده شما ثبت نشده است.
              </div>
            ) : (
              <div className="divide-y divide-line-soft">
                {past.map((appointment) => (
                  <button
                    key={appointment.id}
                    type="button"
                    onClick={() => setSelected(appointment)}
                    className="w-full text-right px-4 py-3 hover:bg-surface-muted transition-colors flex items-center justify-between gap-2"
                  >
                    <span className="min-w-0">
                      <span className="block text-caption font-semibold text-ink truncate">
                        {appointment.service_name}
                      </span>
                      <span className="block text-caption text-muted mt-1">
                        {formatToJalali(appointment.appointment_date)}
                      </span>
                    </span>
                    <AppointmentStatusBadge status={appointment.status} />
                  </button>
                ))}
              </div>
            )}
          </SectionCard>
        </div>
      </div>

      <AppointmentDetailsModal
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        appointment={selected}
      />
    </div>
  );
};
