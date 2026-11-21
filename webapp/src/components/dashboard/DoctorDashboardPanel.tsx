import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { apiClient } from '../../api/client';
import { Appointment } from '../../types';
import { formatTimeFa, toPersianDigits, formatToJalali, todayJalaliString } from '../../utils/persianDate';
import {
  countByDay,
  currentWeekDays,
  sortAppointments,
} from '../../utils/analytics';
import { AppointmentStatusBadge } from '../common/Badge';
import { Button } from '../common/Button';
import { AppointmentDetailsModal } from '../appointments/AppointmentDetailsModal';
import {
  BarChart,
  ErrorBanner,
  InfoBanner,
  LoadingPanel,
  SectionCard,
  StatCard,
} from '../common/ui';
import {
  Bot,
  CalendarCheck2,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  Clock,
  RefreshCw,
  Sparkles,
  Stethoscope,
  XCircle,
} from 'lucide-react';

interface DoctorDashboardPanelProps {
  onNavigate: (view: string) => void;
}

/**
 * Doctor dashboard: the physician sees only their own appointments, filtered
 * by the authenticated doctor id. All counts are computed from server rows.
 */
export const DoctorDashboardPanel: React.FC<DoctorDashboardPanelProps> = ({ onNavigate }) => {
  const { currentUser } = useAuth();
  const doctorId = currentUser?.doctor?.id ?? null;

  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Appointment | null>(null);

  const today = todayJalaliString();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await apiClient.getAppointments(doctorId ? { doctor_id: doctorId } : undefined);
      setAppointments(
        doctorId
          ? list.filter(
              (appointment) =>
                appointment.doctor_id === doctorId ||
                appointment.doctor_name === currentUser?.full_name
            )
          : list
      );
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت برنامه ناکام ماند');
      setAppointments(null);
    } finally {
      setLoading(false);
    }
  }, [doctorId, currentUser?.full_name]);

  useEffect(() => {
    if (doctorId === null) {
      setLoading(false);
      setAppointments([]);
      return;
    }
    load();
  }, [doctorId, load]);

  const rows = appointments ?? [];

  const todayAppointments = useMemo(
    () =>
      sortAppointments(
        rows.filter(
          (appointment) =>
            appointment.appointment_date === today && appointment.status !== 'cancelled'
        )
      ),
    [rows, today]
  );

  const upcomingAppointments = useMemo(
    () =>
      sortAppointments(
        rows.filter(
          (appointment) =>
            appointment.appointment_date > today && appointment.status !== 'cancelled'
        )
      ),
    [rows, today]
  );

  const completedCount = rows.filter((appointment) => appointment.status === 'completed').length;
  const cancelledCount = rows.filter((appointment) => appointment.status === 'cancelled').length;

  const weekDays = useMemo(() => currentWeekDays(), []);
  const weekCounts = useMemo(() => countByDay(rows, weekDays), [rows, weekDays]);
  const weekData = weekDays.map((day, index) => ({
    label: day.weekday,
    value: weekCounts[index],
    highlight: day.isToday,
  }));

  if (doctorId === null) {
    return (
      <InfoBanner tone="warning" title="حساب پزشک به پرونده متصل نیست">
        حساب شما به هیچ پرونده پزشکی متصل نیست. از مدیر کلینیک بخواهید حساب شما را به پزشک متصل
        کند؛ تا آن زمان برنامه‌ای برای نمایش وجود ندارد.
      </InfoBanner>
    );
  }

  if (loading && appointments === null) {
    return <LoadingPanel message="در حال دریافت برنامه پزشک..." />;
  }

  return (
    <div className="space-y-5">
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="d-stat-band grid grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<CalendarDays className="w-[18px] h-[18px]" />}
          label="نوبت‌های امروز"
          value={toPersianDigits(todayAppointments.length)}
          hint="به ترتیب ساعت مراجعه"
        />
        <StatCard
          icon={<CalendarCheck2 className="w-[18px] h-[18px]" />}
          label="نوبت‌های پیش‌رو"
          value={toPersianDigits(upcomingAppointments.length)}
          hint="از فردا به بعد"
          tone="soft"
        />
        <StatCard
          icon={<CheckCircle2 className="w-[18px] h-[18px]" />}
          label="ویزیت‌های تکمیل‌شده"
          value={toPersianDigits(completedCount)}
          hint="ثبت‌شده در سامانه"
        />
        <StatCard
          icon={<XCircle className="w-[18px] h-[18px]" />}
          label="نوبت‌های لغوشده"
          value={toPersianDigits(cancelledCount)}
          hint="لغو توسط مراجع یا کلینیک"
          tone="danger"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <SectionCard
          className="xl:col-span-2"
          title="برنامه امروز"
          subtitle={`${toPersianDigits(todayAppointments.length)} نوبت برای ${formatToJalali(today, true)}`}
          action={
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="p-1.5 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
              aria-label="به‌روزرسانی برنامه"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          }
        >
          {todayAppointments.length === 0 ? (
            <div className="d-empty">
              <div className="d-empty-icon">
                <CalendarDays className="w-5 h-5" />
              </div>
              <h4 className="text-body font-bold text-ink mb-1">امروز نوبتی ندارید</h4>
              <p className="text-small text-muted leading-6">
                برنامه امروز شما خالی است. نوبت‌های پیش‌رو در پایین همین صفحه فهرست شده‌اند.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {todayAppointments.map((appointment) => (
                <button
                  key={appointment.id}
                  type="button"
                  onClick={() => setSelected(appointment)}
                  className="w-full text-right flex items-center gap-3 p-3 rounded-[4px] border border-line-soft hover:border-primary-line hover:bg-[#fbf8f2] transition-colors"
                >
                  <div className="w-[62px] shrink-0 rounded-[3px] bg-primary-soft border border-line text-ink-soft py-2 text-center">
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
                      <Stethoscope className="w-3 h-3" />
                      <span>{appointment.service_name}</span>
                    </div>
                  </div>
                  <AppointmentStatusBadge status={appointment.status} />
                </button>
              ))}
            </div>
          )}
        </SectionCard>

        <div className="space-y-5">
          <SectionCard title="برنامه هفته" subtitle="تعداد نوبت‌ها در هفته جاری">
            <BarChart
              data={weekData}
              height={140}
              valueFormatter={(value) => toPersianDigits(value)}
            />
          </SectionCard>

          <section className="d-card p-5">
            <div className="flex items-center gap-1.5 text-small font-bold text-ai">
              <Sparkles className="w-3.5 h-3.5" />
              دستیار پزشک
            </div>
            <p className="text-caption text-muted mt-2 leading-6">
              گزارش نوبت‌های هفته، بار کاری و فهرست بیماران را با گفتگو بخواهید. هیچ تغییری بدون
              تأیید شما ثبت نمی‌شود.
            </p>
            <div className="mt-4 pt-3 border-t border-line-soft">
              <Button
                variant="ai"
                size="sm"
                className="w-full"
                onClick={() => onNavigate('agent')}
                icon={<Bot className="w-3.5 h-3.5" />}
              >
                گفتگو با دستیار
              </Button>
            </div>
          </section>
        </div>
      </div>

      <SectionCard
        title="نوبت‌های پیش‌رو"
        subtitle="پنج نوبت نزدیک به ترتیب تاریخ و ساعت"
        action={
          <button type="button" className="d-link" onClick={() => onNavigate('patients')}>
            بیماران مجاز
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
        }
        noPadding
      >
        {upcomingAppointments.length === 0 ? (
          <div className="p-6">
            <div className="d-empty">
              <div className="d-empty-icon">
                <Clock className="w-5 h-5" />
              </div>
              <p className="text-small text-muted">نوبت آینده‌ای برای شما ثبت نشده است.</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="d-table">
              <thead>
                <tr>
                  <th>تاریخ</th>
                  <th>ساعت</th>
                  <th>بیمار</th>
                  <th>خدمت</th>
                  <th>وضعیت</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {upcomingAppointments.slice(0, 5).map((appointment) => (
                  <tr key={appointment.id}>
                    <td>{formatToJalali(appointment.appointment_date)}</td>
                    <td className="tabular-nums">{formatTimeFa(appointment.appointment_time)}</td>
                    <td className="font-semibold">{appointment.patient_name}</td>
                    <td className="text-muted">{appointment.service_name}</td>
                    <td>
                      <AppointmentStatusBadge status={appointment.status} />
                    </td>
                    <td className="text-left">
                      <button
                        type="button"
                        className="d-link"
                        onClick={() => setSelected(appointment)}
                      >
                        جزئیات
                        <ChevronLeft className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <AppointmentDetailsModal
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        appointment={selected}
      />
    </div>
  );
};
