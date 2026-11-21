import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { ReportsDashboard } from '../../types';
import { formatCount, toPersianDigits, todayJalaliString } from '../../utils/persianDate';
import { lastDays, getServiceBreakdown, getDoctorLoad, formatPercent } from '../../utils/analytics';
import { useClinic } from '../../context/ClinicContext';
import {
  BarChart,
  DonutChart,
  ErrorBanner,
  InfoBanner,
  LoadingPanel,
  PageHeader,
  ProgressBar,
  SectionCard,
  Segmented,
  StatCard,
} from '../common/ui';
import {
  AlertTriangle,
  CalendarCheck2,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  Clock,
  Sparkles,
  Stethoscope,
  TrendingUp,
  XCircle,
} from 'lucide-react';

interface ReportsViewProps {
  onNavigate: (view: string) => void;
}

type RangeValue = '7' | '30' | '90';

function buildBuckets(days: { label: string; jalali: string }[], values: number[], size: number) {
  if (size <= 1) {
    return days.map((day, index) => ({ label: day.label, value: values[index] }));
  }
  const buckets: { label: string; value: number }[] = [];
  for (let index = 0; index < days.length; index += size) {
    const chunk = values.slice(index, index + size);
    buckets.push({
      label: days[index].label,
      value: chunk.reduce((total, value) => total + value, 0),
    });
  }
  return buckets;
}

export const ReportsView: React.FC<ReportsViewProps> = ({ onNavigate }) => {
  const { appointments, services, doctors } = useClinic();
  const [range, setRange] = useState<RangeValue>('30');
  const [reports, setReports] = useState<ReportsDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReports(await apiClient.getReportsDashboard());
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت گزارش‌ها ناکام ماند');
      setReports(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const today = todayJalaliString();
  const rangeDays = Number(range);
  const days = useMemo(() => lastDays(rangeDays), [rangeDays]);
  const startJalali = days[0]?.jalali || today;

  const filtered = useMemo(
    () =>
      appointments.filter(
        (appointment) =>
          appointment.appointment_date >= startJalali &&
          appointment.appointment_date <= today
      ),
    [appointments, startJalali, today]
  );

  const completed = filtered.filter((appointment) => appointment.status === 'completed');
  const cancelled = filtered.filter((appointment) => appointment.status === 'cancelled');
  const upcoming = filtered.filter(
    (appointment) =>
      appointment.status === 'scheduled' ||
      appointment.status === 'confirmed' ||
      appointment.status === 'in_progress'
  );
  const total = filtered.length;
  const completionRate = total ? Math.round((completed.length / total) * 100) : 0;
  const cancellationRate = total ? Math.round((cancelled.length / total) * 100) : 0;

  const dailyValues = useMemo(() => {
    const counts = new Map(days.map((day) => [day.jalali, 0]));
    for (const appointment of filtered) {
      if (appointment.status === 'cancelled') continue;
      counts.set(
        appointment.appointment_date,
        (counts.get(appointment.appointment_date) || 0) + 1
      );
    }
    return days.map((day) => counts.get(day.jalali) || 0);
  }, [days, filtered]);

  const bucketSize = rangeDays <= 14 ? 1 : rangeDays <= 30 ? 3 : 7;
  const buckets = buildBuckets(
    days.map((day) => ({
      label: rangeDays <= 14 ? day.shortLabel.replace(day.weekday, day.weekday.slice(0, 1)) : day.shortLabel,
      jalali: day.jalali,
    })),
    dailyValues,
    bucketSize
  );

  const busiestIndex = dailyValues.reduce(
    (best, value, index) => (value > dailyValues[best] ? index : best),
    0
  );
  const busiestDay = days[busiestIndex];
  const busiestValue = dailyValues[busiestIndex] || 0;

  const serviceMetrics = useMemo(
    () => getServiceBreakdown(filtered, services, today),
    [filtered, services, today]
  );
  const topService = serviceMetrics[0];
  const maxService = Math.max(1, ...serviceMetrics.map((metric) => metric.total));

  const doctorMetrics = useMemo(
    () => getDoctorLoad(filtered, doctors),
    [filtered, doctors]
  );
  const topDoctor = doctorMetrics[0];
  const maxDoctor = Math.max(1, ...doctorMetrics.map((metric) => metric.count));

  const statusData = [
    { label: 'تکمیل‌شده', value: completed.length, color: '#45674d' },
    { label: 'لغوشده', value: cancelled.length, color: '#9c3a34' },
    { label: 'در انتظار / فعال', value: upcoming.length, color: '#9c4a2f' },
  ];
  const statusTotal = statusData.reduce((sum, item) => sum + item.value, 0);

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="از داده به تصمیم بهتر"
        subtitle="تصویر عملکرد کلینیک بر پایه نوبت‌های ثبت‌شده؛ همه شاخص‌ها از پاسخ سرور محاسبه می‌شوند."
        action={
          <Segmented
            options={[
              { value: '7', label: '۷ روز' },
              { value: '30', label: '۳۰ روز' },
              { value: '90', label: '۹۰ روز' },
            ]}
            value={range}
            onChange={(value) => setRange(value as RangeValue)}
          />
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}
      {loading && !reports && <LoadingPanel message="در حال دریافت گزارش‌های کلینیک..." />}

      <div className="d-stat-band grid grid-cols-2 xl:grid-cols-4 mb-5">
        <StatCard
          icon={<CalendarDays className="w-[18px] h-[18px]" />}
          label={`نوبت‌های ${toPersianDigits(rangeDays)} روز اخیر`}
          value={toPersianDigits(total)}
          hint={`${toPersianDigits(upcoming.length)} نوبت فعال`}
        />
        <StatCard
          icon={<CheckCircle2 className="w-[18px] h-[18px]" />}
          label="ویزیت‌های تکمیل‌شده"
          value={toPersianDigits(completed.length)}
          hint={`نرخ تکمیل ${toPersianDigits(completionRate)}٪`}
          tone="soft"
        />
        <StatCard
          icon={<XCircle className="w-[18px] h-[18px]" />}
          label="نوبت‌های لغوشده"
          value={toPersianDigits(cancelled.length)}
          hint={`نرخ لغو ${toPersianDigits(cancellationRate)}٪`}
          tone="danger"
        />
        <StatCard
          icon={<CalendarCheck2 className="w-[18px] h-[18px]" />}
          label="نوبت‌های امروز"
          value={toPersianDigits(reports?.overview.appointments_today ?? 0)}
          hint={`${toPersianDigits(reports?.overview.appointments_upcoming ?? 0)} نوبت آینده`}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <SectionCard
          className="xl:col-span-2"
          title="روند مراجعات"
          subtitle={`تعداد نوبت‌های غیرلغوشده در ${toPersianDigits(rangeDays)} روز اخیر`}
        >
          {total === 0 ? (
            <div className="d-empty py-10">
              <div className="d-empty-icon">
                <CalendarDays className="w-5 h-5" />
              </div>
              <p className="text-small text-muted">در این بازه نوبتی ثبت نشده است.</p>
            </div>
          ) : (
            <>
              <BarChart
                data={buckets.map((bucket, index) => ({
                  label: bucket.label,
                  value: bucket.value,
                  highlight: index === buckets.length - 1,
                }))}
                height={190}
                valueFormatter={(value) => toPersianDigits(value)}
              />
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-line-soft text-caption text-muted">
                <span>مجموع نوبت‌های غیرلغوشده</span>
                <span className="font-bold text-ink">
                  {toPersianDigits(dailyValues.reduce((sum, value) => sum + value, 0))} نوبت
                </span>
              </div>
            </>
          )}
        </SectionCard>

        <SectionCard title="وضعیت نوبت‌ها" subtitle="توزیع وضعیت‌ها در بازه انتخابی">
          {statusTotal === 0 ? (
            <div className="d-empty py-10">
              <div className="d-empty-icon">
                <Clock className="w-5 h-5" />
              </div>
              <p className="text-small text-muted">داده‌ای برای نمایش وضعیت وجود ندارد.</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4">
              <DonutChart
                data={statusData}
                centerValue={formatCount(statusTotal)}
                centerLabel="نوبت"
                size={148}
              />
              <div className="w-full space-y-2.5">
                {statusData.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-2 text-caption">
                    <span className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: item.color }} />
                      <span className="text-ink">{item.label}</span>
                    </span>
                    <span className="text-muted tabular-nums">
                      {toPersianDigits(item.value)} · {formatPercent(item.value, statusTotal)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <SectionCard
          className="xl:col-span-2"
          title="عملکرد خدمات"
          subtitle="بر اساس نوبت‌های ثبت‌شده در بازه انتخابی"
          noPadding
        >
          {serviceMetrics.length === 0 ? (
            <div className="p-6">
              <div className="d-empty">
                <div className="d-empty-icon">
                  <Stethoscope className="w-5 h-5" />
                </div>
                <p className="text-small text-muted">خدمتی در این بازه ثبت نشده است.</p>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="d-table">
                <thead>
                  <tr>
                    <th>خدمت</th>
                    <th>کل نوبت</th>
                    <th>تکمیل‌شده</th>
                    <th>لغوشده</th>
                    <th className="w-[180px]">سهم از نوبت‌ها</th>
                  </tr>
                </thead>
                <tbody>
                  {serviceMetrics.map((metric) => (
                    <tr key={metric.serviceId}>
                      <td className="font-semibold">{metric.name}</td>
                      <td className="tabular-nums">{toPersianDigits(metric.total)}</td>
                      <td className="tabular-nums text-primary-deep">
                        {toPersianDigits(metric.completed)}
                      </td>
                      <td className="tabular-nums text-danger">
                        {toPersianDigits(metric.cancelled)}
                      </td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="flex-1">
                            <ProgressBar value={metric.total} max={maxService} />
                          </div>
                          <span className="text-caption text-muted tabular-nums w-9 text-left">
                            {toPersianDigits(Math.round((metric.total / Math.max(1, total)) * 100))}٪
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        <SectionCard title="بار کاری پزشکان" subtitle="تعداد نوبت‌های ثبت‌شده در بازه">
          {doctorMetrics.length === 0 ? (
            <div className="d-empty py-10">
              <div className="d-empty-icon">
                <Stethoscope className="w-5 h-5" />
              </div>
              <p className="text-small text-muted">نوبتی برای پزشکان ثبت نشده است.</p>
            </div>
          ) : (
            <div className="space-y-3.5">
              {doctorMetrics.slice(0, 6).map((doctor) => (
                <div key={doctor.doctorId}>
                  <div className="flex items-center justify-between text-caption mb-1.5">
                    <span className="text-ink truncate">{doctor.name}</span>
                    <span className="text-muted tabular-nums shrink-0">
                      {toPersianDigits(doctor.count)} نوبت
                    </span>
                  </div>
                  <ProgressBar value={doctor.count} max={maxDoctor} />
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      {/* Deterministic data reading — explicitly not an LLM summary */}
      <section className="d-card p-5 sm:p-6">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-5">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-small font-bold text-ai">
              <Sparkles className="w-3.5 h-3.5" />
              خوانش داده
            </div>
            <p className="text-caption text-muted mt-1">
              این بخش یک محاسبه قطعی روی نوبت‌های ثبت‌شده است؛ خلاصه تولیدشده توسط مدل زبانی نیست.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-6 gap-y-4 mt-4">
              <div className="border-t border-line-soft pt-3">
                <div className="flex items-center gap-1.5 text-caption font-bold text-ink">
                  <TrendingUp className="w-3.5 h-3.5 text-primary" />
                  پرترافیک‌ترین روز
                </div>
                <p className="text-caption text-muted mt-1.5 leading-5">
                  {busiestValue > 0
                    ? `${busiestDay?.weekday} ${toPersianDigits(busiestDay?.day || 0)} ${busiestDay?.monthName} با ${toPersianDigits(busiestValue)} نوبت`
                    : 'در این بازه نوبتی ثبت نشده است.'}
                </p>
              </div>
              <div className="border-t border-line-soft pt-3">
                <div className="flex items-center gap-1.5 text-caption font-bold text-ink">
                  <Stethoscope className="w-3.5 h-3.5 text-primary" />
                  پرتقاضاترین خدمت
                </div>
                <p className="text-caption text-muted mt-1.5 leading-5">
                  {topService
                    ? `${topService.name} با ${toPersianDigits(topService.total)} نوبت`
                    : 'خدمتی در این بازه ثبت نشده است.'}
                </p>
              </div>
              <div className="border-t border-line-soft pt-3">
                <div className="flex items-center gap-1.5 text-caption font-bold text-ink">
                  <AlertTriangle className="w-3.5 h-3.5 text-warn" />
                  بار کاری پزشکان
                </div>
                <p className="text-caption text-muted mt-1.5 leading-5">
                  {topDoctor
                    ? `بیشترین نوبت: ${topDoctor.name} با ${toPersianDigits(topDoctor.count)} نوبت`
                    : 'نوبتی برای پزشکان ثبت نشده است.'}
                </p>
              </div>
            </div>
          </div>

          <div className="shrink-0 w-full lg:w-60 flex flex-col lg:border-s lg:border-line lg:ps-5">
            <button
              type="button"
              onClick={() => onNavigate('agent')}
              className="d-link justify-between py-2 border-b border-line-soft"
            >
              درخواست گزارش از دستیار
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onNavigate('users')}
              className="d-link justify-between py-2 border-b border-line-soft"
            >
              مدیریت کاربران
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </section>

      <div className="mt-5">
        <InfoBanner tone="info" icon={<Clock className="w-4 h-4" />}>
          گزارش‌های این صفحه بر اساس بازه انتخابی و نوبت‌های موجود در پایگاه داده محاسبه می‌شوند.
          داده‌ای برای درآمد، بیمه یا اتاق درمان در API فعلی وجود ندارد و در این صفحه نمایش داده
          نمی‌شود.
        </InfoBanner>
      </div>
    </div>
  );
};
