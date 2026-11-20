import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { ReportsDashboard, VisitRatingSummary, Appointment } from '../../types';
import { formatCount, formatTimeFa, toPersianDigits, todayJalaliString } from '../../utils/persianDate';
import {
  countByDay,
  getServiceBreakdown,
  lastDays,
  sortAppointments,
} from '../../utils/analytics';
import { useClinic } from '../../context/ClinicContext';
import { Button } from '../common/Button';
import { AppointmentStatusBadge } from '../common/Badge';
import {
  BarChart,
  DonutChart,
  ErrorBanner,
  InfoBanner,
  ProgressBar,
  SectionCard,
  StatCard,
} from '../common/ui';
import { AppointmentDetailsModal } from '../appointments/AppointmentDetailsModal';
import {
  Ban,
  CalendarDays,
  ChevronLeft,
  Clock,
  FileBarChart2,
  Sparkles,
  Star,
  Stethoscope,
  UserCog,
  Users,
  AlertTriangle,
  TrendingUp,
} from 'lucide-react';

interface AdminDashboardPanelProps {
  onNavigate: (view: string) => void;
  onBook: () => void;
  onOpenAgent: () => void;
}

/**
 * Admin dashboard: whole-clinic numbers come from the real
 * ``GET /reports/dashboard`` SQL aggregates. Schedule, service and doctor
 * breakdowns are computed from the appointments the server returned; nothing
 * here is demo data. The “تحلیل امروز” panel is a deterministic calculation
 * on those rows, not an LLM-generated claim.
 */
export const AdminDashboardPanel: React.FC<AdminDashboardPanelProps> = ({
  onNavigate,
  onBook,
  onOpenAgent,
}) => {
  const { appointments, services, patients } = useClinic();
  const [reports, setReports] = useState<ReportsDashboard | null>(null);
  const [ratings, setRatings] = useState<VisitRatingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingReports, setLoadingReports] = useState(true);
  const [selected, setSelected] = useState<Appointment | null>(null);

  const loadReports = useCallback(async () => {
    setLoadingReports(true);
    try {
      setReports(await apiClient.getReportsDashboard());
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت گزارش کلینیک ناکام ماند');
      setReports(null);
    } finally {
      setLoadingReports(false);
    }
  }, []);

  // Satisfaction summary is admin-only; a failure must not block the dashboard.
  const loadRatings = useCallback(async () => {
    try {
      setRatings(await apiClient.getVisitRatingSummary());
    } catch {
      setRatings(null);
    }
  }, []);

  useEffect(() => {
    loadReports();
    loadRatings();
  }, [loadReports, loadRatings]);

  const today = todayJalaliString();
  const overview = reports?.overview;
  const reportAppointments = reports?.appointments;

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

  const days = useMemo(() => lastDays(7), []);
  const weekCounts = useMemo(() => countByDay(appointments, days), [appointments, days]);
  const weekData = days.map((day, index) => ({
    label: day.shortLabel.replace(day.weekday, day.weekday.slice(0, 1)),
    value: weekCounts[index],
    highlight: day.isToday,
  }));

  const serviceBreakdown = useMemo(
    () => getServiceBreakdown(appointments, services, today),
    [appointments, services, today]
  );

  const topServices = serviceBreakdown.slice(0, 3);
  const otherCount = serviceBreakdown.slice(3).reduce((total, item) => total + item.total, 0);
  const donutData = [
    ...topServices.map((item, index) => ({
      label: item.name,
      value: item.total,
      color: ['#087F83', '#6260B6', '#B8DDDC'][index] || '#E3E9F0',
    })),
    ...(otherCount > 0 ? [{ label: 'سایر خدمات', value: otherCount, color: '#E3E9F0' }] : []),
  ];
  const serviceTotal = serviceBreakdown.reduce((total, item) => total + item.total, 0);

  const doctorLoad = reportAppointments?.doctor_load ?? [];
  const maxLoad = Math.max(1, ...doctorLoad.map((doctor) => doctor.scheduled_count));
  const busiestDoctor = doctorLoad[0];
  const incomplete = overview?.patients_incomplete ?? 0;

  if (loadingReports && !reports) {
    return (
      <div className="space-y-5">
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="d-stat">
              <div className="d-skeleton h-10 w-10 rounded-full" />
              <div className="d-skeleton h-7 w-20" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <div className="d-card xl:col-span-2 h-80 d-skeleton" />
          <div className="d-card h-80 d-skeleton" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {error && <ErrorBanner message={error} onRetry={loadReports} />}

      {/* KPI row — /reports/dashboard overview */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4">
        <StatCard
          icon={<CalendarDays className="w-[18px] h-[18px]" />}
          label="نوبت‌های امروز"
          value={toPersianDigits(overview?.appointments_today ?? todayAppointments.length)}
          hint={
            overview
              ? `${toPersianDigits(overview.appointments_upcoming)} نوبت در پیش‌رو`
              : 'در حال دریافت گزارش'
          }
        />
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="بیماران پرونده‌دار"
          value={toPersianDigits(overview?.patients_total ?? patients.length)}
          hint={
            incomplete > 0
              ? `${toPersianDigits(incomplete)} پرونده نیازمند تکمیل`
              : 'همه پرونده‌ها کامل هستند'
          }
          tone="soft"
        />
        <StatCard
          icon={<Stethoscope className="w-[18px] h-[18px]" />}
          label="پزشکان فعال"
          value={toPersianDigits(overview?.doctors_total ?? 0)}
          hint={`${toPersianDigits(overview?.services_total ?? services.length)} خدمت فعال`}
        />
        <StatCard
          icon={<Ban className="w-[18px] h-[18px]" />}
          label="لغو در ۳۰ روز اخیر"
          value={toPersianDigits(overview?.cancellations_30d ?? 0)}
          hint={
            reportAppointments
              ? `${toPersianDigits(reportAppointments.upcoming_cancelled)} لغو در بازه پیش‌رو`
              : undefined
          }
          tone="danger"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* Today schedule */}
        <SectionCard
          className="xl:col-span-2"
          title="برنامه امروز کلینیک"
          subtitle={`${toPersianDigits(todayAppointments.length)} نوبت فعال برای امروز ثبت شده است`}
          action={
            <button type="button" className="d-link" onClick={() => onNavigate('appointments')}>
              همه نوبت‌ها
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
          }
        >
          {todayAppointments.length === 0 ? (
            <div className="d-empty">
              <div className="d-empty-icon">
                <CalendarDays className="w-5 h-5" />
              </div>
              <h4 className="text-body font-bold text-ink mb-1">امروز نوبتی ثبت نشده است</h4>
              <p className="text-small text-muted leading-6 mb-4">
                می‌توانید از همین‌جا نوبت جدید ثبت کنید یا با دستیار گفتگو کنید.
              </p>
              <Button size="sm" onClick={onBook} icon={<CalendarDays className="w-3.5 h-3.5" />}>
                رزرو نوبت
              </Button>
            </div>
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

        {/* Deterministic daily analysis (not an AI-generated summary) */}
        <section className="d-ai-card p-5 sm:p-6 flex flex-col">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-1.5 text-small font-bold text-ai">
                <Sparkles className="w-3.5 h-3.5" />
                تحلیل امروز
              </div>
              <p className="text-caption text-muted mt-1">محاسبه‌شده از داده‌های ثبت‌شده — بدون تولید متن حدسی</p>
            </div>
            <span className="w-7 h-7 rounded-full bg-surface/70 border border-ai-line text-ai flex items-center justify-center">
              <TrendingUp className="w-3.5 h-3.5" />
            </span>
          </div>

          <div className="mt-4 space-y-2.5 flex-1">
            <div className="bg-surface/75 border border-ai-line rounded-[12px] p-3">
              <div className="text-small font-bold text-ink">
                {toPersianDigits(todayAppointments.length)} نوبت برای امروز
              </div>
              <p className="text-caption text-muted mt-1 leading-5">
                {overview?.appointments_upcoming
                  ? `${toPersianDigits(overview.appointments_upcoming)} نوبت آینده در سامانه ثبت شده است.`
                  : 'نوبت آینده‌ای در سامانه ثبت نشده است.'}
              </p>
            </div>

            <div className="bg-surface/75 border border-ai-line rounded-[12px] p-3">
              <div className="text-small font-bold text-ink flex items-center gap-1.5">
                {incomplete > 0 && <AlertTriangle className="w-3.5 h-3.5 text-warn" />}
                {incomplete > 0
                  ? `${toPersianDigits(incomplete)} پرونده نیازمند تکمیل`
                  : 'همه پرونده‌ها کامل هستند'}
              </div>
              <p className="text-caption text-muted mt-1 leading-5">
                {incomplete > 0
                  ? 'این پرونده‌ها کد ملی ندارند و برای پذیرش کامل نیاز به اقدام دارند.'
                  : 'هیچ پرونده ناقصی در پایگاه داده گزارش نشده است.'}
              </p>
              {incomplete > 0 && (
                <button
                  type="button"
                  onClick={() => onNavigate('patients')}
                  className="d-link mt-2 text-caption"
                >
                  بررسی پرونده‌ها
                  <ChevronLeft className="w-3 h-3" />
                </button>
              )}
            </div>

            <div className="bg-surface/75 border border-ai-line rounded-[12px] p-3">
              <div className="text-small font-bold text-ink">
                {busiestDoctor
                  ? `بیشترین بار کاری: ${busiestDoctor.doctor_name}`
                  : 'بار کاری پزشکان ثبت نشده است'}
              </div>
              <p className="text-caption text-muted mt-1 leading-5">
                {busiestDoctor
                  ? `${toPersianDigits(busiestDoctor.scheduled_count)} نوبت در ${toPersianDigits(
                      reportAppointments?.window_days ?? 7
                    )} روز آینده.`
                  : 'برای این بازه نوبتی به پزشکان اختصاص داده نشده است.'}
              </p>
            </div>
            <div className="bg-surface/75 border border-ai-line rounded-[12px] p-3">
              <div className="text-small font-bold text-ink flex items-center gap-1.5">
                <Star className="w-3.5 h-3.5 text-[#F0B429]" />
                {ratings && ratings.count > 0
                  ? `رضایت بیماران: ${toPersianDigits(ratings.average.toFixed(1))} از ۵`
                  : 'رضایت بیماران هنوز ثبت نشده'}
              </div>
              <p className="text-caption text-muted mt-1 leading-5">
                {ratings && ratings.count > 0
                  ? `بر اساس ${toPersianDigits(ratings.count)} امتیاز ثبت‌شده پس از ویزیت. میانگین ۳۰ روز اخیر: ${toPersianDigits(ratings.average_30d.toFixed(1))}.`
                  : 'بیماران پس از ویزیت می‌توانند از جزئیات نوبت، امتیاز ۱ تا ۵ ثبت کنند.'}
              </p>
            </div>
          </div>

          <Button
            variant="ai"
            size="sm"
            className="w-full mt-4"
            onClick={onOpenAgent}
            icon={<Sparkles className="w-3.5 h-3.5" />}
          >
            گفتگو با دستیار
          </Button>
        </section>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <SectionCard
          title="روند نوبت‌های ۷ روز گذشته"
          subtitle="تعداد نوبت‌های غیرلغوشده در هر روز"
        >
          <BarChart
            data={weekData}
            height={150}
            valueFormatter={(value) => toPersianDigits(value)}
          />
          <div className="flex items-center justify-between mt-4 pt-3 border-t border-line-soft text-caption text-muted">
            <span>مجموع بازه</span>
            <span className="font-bold text-ink">
              {toPersianDigits(weekCounts.reduce((total, value) => total + value, 0))} نوبت
            </span>
          </div>
        </SectionCard>

        <SectionCard title="ترکیب خدمات" subtitle="بر اساس نوبت‌های ثبت‌شده در سامانه">
          {serviceTotal === 0 ? (
            <div className="d-empty py-8">
              <div className="d-empty-icon">
                <Stethoscope className="w-5 h-5" />
              </div>
              <p className="text-small text-muted">هنوز نوبتی برای محاسبه ترکیب خدمات ثبت نشده است.</p>
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row xl:flex-col items-center gap-4">
              <DonutChart
                data={donutData}
                centerValue={formatCount(serviceTotal)}
                centerLabel="نوبت"
                size={132}
              />
              <div className="w-full space-y-2">
                {donutData.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-2 text-caption">
                    <span className="flex items-center gap-2 min-w-0">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: item.color }}
                      />
                      <span className="text-ink truncate">{item.label}</span>
                    </span>
                    <span className="text-muted tabular-nums shrink-0">
                      {toPersianDigits(item.value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard
          title="بار کاری پزشکان"
          subtitle={
            reportAppointments
              ? `${toPersianDigits(reportAppointments.window_days)} روز آینده`
              : 'در حال دریافت گزارش'
          }
        >
          {doctorLoad.length === 0 ? (
            <div className="d-empty py-8">
              <div className="d-empty-icon">
                <Stethoscope className="w-5 h-5" />
              </div>
              <p className="text-small text-muted">هیچ نوبت آینده‌ای برای پزشکان ثبت نشده است.</p>
            </div>
          ) : (
            <div className="space-y-3.5">
              {doctorLoad.slice(0, 5).map((doctor) => (
                <div key={doctor.doctor_id}>
                  <div className="flex items-center justify-between text-caption mb-1.5">
                    <span className="text-ink truncate">{doctor.doctor_name}</span>
                    <span className="text-muted tabular-nums shrink-0">
                      {toPersianDigits(doctor.scheduled_count)} نوبت
                    </span>
                  </div>
                  <ProgressBar value={doctor.scheduled_count} max={maxLoad} />
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      {/* Quick access */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          {
            title: 'گزارش‌ها و تحلیل',
            description: 'نمای کامل عملکرد کلینیک بر پایه داده‌های واقعی',
            icon: FileBarChart2,
            onClick: () => onNavigate('reports'),
          },
          {
            title: 'کاربران و دسترسی‌ها',
            description: 'مدیریت نقش‌ها و وضعیت حساب‌های کلینیک',
            icon: UserCog,
            onClick: () => onNavigate('users'),
          },
          {
            title: 'پزشکان و خدمات',
            description: 'فهرست کادر درمان و خدمات قابل ارائه',
            icon: Stethoscope,
            onClick: () => onNavigate('team'),
          },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.title}
              type="button"
              onClick={item.onClick}
              className="d-card p-4 text-right hover:border-primary-line hover:bg-[#FBFDFD] transition-colors flex items-start gap-3"
            >
              <span className="d-icon-ring">
                <Icon className="w-4 h-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-small font-bold text-ink">{item.title}</span>
                <span className="block text-caption text-muted mt-1 leading-5">{item.description}</span>
              </span>
              <ChevronLeft className="w-4 h-4 text-line-strong shrink-0 mt-1" />
            </button>
          );
        })}
      </div>

      {!loadingReports && appointments.length > 0 && (
        <InfoBanner tone="info" icon={<Clock className="w-4 h-4" />}>
          همه اعداد این صفحه از پاسخ‌های واقعی سرور محاسبه می‌شوند؛ برای تازه‌سازی، دکمه
          <button type="button" className="mx-1 underline font-bold" onClick={loadReports}>
            به‌روزرسانی گزارش
          </button>
          را بزنید.
        </InfoBanner>
      )}

      <AppointmentDetailsModal
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        appointment={selected}
      />
    </div>
  );
};
