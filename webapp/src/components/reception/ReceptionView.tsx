import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { WorklistItem } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { useClinic } from '../../context/ClinicContext';
import { PageHeader, ErrorBanner, InfoBanner, LoadingPanel, SectionCard } from '../common/ui';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { formatTimeFa, toPersianDigits, todayJalaliString } from '../../utils/persianDate';
import {
  AlarmClock,
  CalendarCheck2,
  CheckCircle2,
  Clock,
  DoorOpen,
  Phone,
  PlayCircle,
  RefreshCw,
  Stethoscope,
  UserRound,
  UserX,
} from 'lucide-react';

type FlowKey = 'booked' | 'waiting' | 'in_treatment' | 'completed' | 'no_show' | 'cancelled';

const FLOW_META: Record<
  FlowKey,
  { label: string; tone: 'info' | 'warning' | 'teal' | 'success' | 'danger' | 'neutral' }
> = {
  booked: { label: 'رزرو شده', tone: 'info' },
  waiting: { label: 'در انتظار', tone: 'warning' },
  in_treatment: { label: 'در حال درمان', tone: 'teal' },
  completed: { label: 'تکمیل‌شده', tone: 'success' },
  no_show: { label: 'عدم مراجعه', tone: 'danger' },
  cancelled: { label: 'لغوشده', tone: 'neutral' },
};

function flowKey(item: WorklistItem): FlowKey {
  if (item.status === 'cancelled') return 'cancelled';
  if (item.status === 'completed') return 'completed';
  if (item.status === 'no_show') return 'no_show';
  if (item.status === 'in_progress' || item.started_at) return 'in_treatment';
  if (item.checked_in_at) return 'waiting';
  return 'booked';
}

function clockOf(value?: string | null): string {
  return value && value.length >= 16 ? value.slice(11, 16) : '';
}

/**
 * Reception / daily clinic flow.
 *
 * The screen the front desk actually lives on: today's list in time order,
 * one obvious next action per row, and live counts for waiting, in-treatment
 * and finished patients. All transitions are server-authoritative; the view
 * only reflects the returned worklist row.
 */
export const ReceptionView: React.FC = () => {
  const { currentUser } = useAuth();
  const { doctors } = useClinic();
  const role = currentUser?.role || 'admin';

  const [items, setItems] = useState<WorklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doctorFilter, setDoctorFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<'all' | FlowKey>('all');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const today = todayJalaliString();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.getDayWorklist({
        appointment_date: today,
        doctor_id: doctorFilter === 'all' ? undefined : Number(doctorFilter),
      });
      setItems(data);
      setError(null);
      setLastUpdated(new Date());
    } catch (err: any) {
      setError(err.message || 'دریافت پذیرش امروز ناکام ماند');
    } finally {
      setLoading(false);
    }
  }, [today, doctorFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  // Light polling keeps the queue fresh on the front-desk screen without a
  // websocket. Failures are silent; the explicit refresh button reports them.
  useEffect(() => {
    const timer = setInterval(() => {
      void load();
    }, 45_000);
    return () => clearInterval(timer);
  }, [load]);

  const counts = useMemo(() => {
    const base: Record<FlowKey, number> = {
      booked: 0,
      waiting: 0,
      in_treatment: 0,
      completed: 0,
      no_show: 0,
      cancelled: 0,
    };
    items.forEach((item) => {
      base[flowKey(item)] += 1;
    });
    return base;
  }, [items]);

  const filtered = useMemo(() => {
    const visible = items.filter(
      (item) => statusFilter === 'all' || flowKey(item) === statusFilter
    );
    if (statusFilter !== 'waiting') return visible;
    // Each doctor runs their own queue, so a queue number only orders one
    // room. With a doctor filter applied we follow that room's numbers; when
    // the whole clinic is shown there is no single counter, so the waiting
    // list falls back to the real arrival clock.
    if (doctorFilter === 'all') {
      return [...visible].sort((a, b) => {
        const left = a.checked_in_at ?? '';
        const right = b.checked_in_at ?? '';
        if (left !== right) return left.localeCompare(right);
        return (a.queue_number ?? 0) - (b.queue_number ?? 0);
      });
    }
    return [...visible].sort((a, b) => {
      const left = a.queue_number ?? Number.MAX_SAFE_INTEGER;
      const right = b.queue_number ?? Number.MAX_SAFE_INTEGER;
      if (left !== right) return left - right;
      return (a.checked_in_at ?? '').localeCompare(b.checked_in_at ?? '');
    });
  }, [items, statusFilter, doctorFilter]);

  const runAction = async (
    item: WorklistItem,
    action: 'check-in' | 'start' | 'complete' | 'no-show'
  ) => {
    setBusyId(item.id);
    setError(null);
    try {
      const updated =
        action === 'check-in'
          ? await apiClient.checkInAppointment(item.id)
          : action === 'start'
          ? await apiClient.startAppointment(item.id)
          : action === 'complete'
          ? await apiClient.completeAppointment(item.id)
          : await apiClient.markAppointmentNoShow(item.id);
      setItems((current) =>
        current.map((row) => (row.id === updated.id ? { ...row, ...updated } : row))
      );
      setLastUpdated(new Date());
    } catch (err: any) {
      setError(err.message || 'تغییر وضعیت نوبت ناکام ماند');
    } finally {
      setBusyId(null);
    }
  };

  const canFlow = role === 'admin' || role === 'receptionist' || role === 'doctor';

  return (
    <div className="d-page d-fade">
      <PageHeader
        eyebrow="میز پذیرش"
        title="پذیرش و جریان روز"
        subtitle={`نوبت‌های امروز (${today}) به ترتیب ساعت؛ هر ردیف فقط یک اقدام بعدی دارد.`}
        action={
          <>
            {lastUpdated && (
              <span className="text-caption text-faint">
                آخرین به‌روزرسانی {lastUpdated.toLocaleTimeString('fa-IR')}
              </span>
            )}
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="p-2 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
              aria-label="به‌روزرسانی پذیرش"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="grid grid-cols-2 xl:grid-cols-5 gap-3 sm:gap-4 mb-5">
        {[
          { key: 'waiting' as FlowKey, label: 'در انتظار', icon: Clock, tone: 'warn' as const },
          {
            key: 'in_treatment' as FlowKey,
            label: 'در حال درمان',
            icon: Stethoscope,
            tone: 'teal' as const,
          },
          {
            key: 'booked' as FlowKey,
            label: 'رزروشده (نرسیده)',
            icon: CalendarCheck2,
            tone: 'soft' as const,
          },
          {
            key: 'completed' as FlowKey,
            label: 'تکمیل‌شده',
            icon: CheckCircle2,
            tone: 'teal' as const,
          },
          {
            key: 'no_show' as FlowKey,
            label: 'عدم مراجعه / لغو',
            icon: UserX,
            tone: 'danger' as const,
          },
        ].map((card) => {
          const Icon = card.icon;
          const value =
            card.key === 'no_show' ? counts.no_show + counts.cancelled : counts[card.key];
          return (
            <button
              key={card.key}
              type="button"
              onClick={() =>
                setStatusFilter((current) =>
                  current === card.key ? 'all' : card.key
                )
              }
              className={`d-stat text-right transition-colors ${
                statusFilter === card.key
                  ? 'bg-primary-soft border-primary-line'
                  : 'hover:bg-[#fbf8f2]'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <span
                  className={`d-icon-ring ${
                    card.tone === 'danger' ? 'danger' : card.tone === 'warn' ? 'warn' : ''
                  }`}
                >
                  <Icon className="w-4 h-4" />
                </span>
                <span className="text-caption font-medium text-muted leading-5">
                  {card.label}
                </span>
              </div>
              <div className="d-stat-value">{toPersianDigits(value)}</div>
            </button>
          );
        })}
      </div>

      {counts.waiting > 0 && (
        <InfoBanner
          tone="warning"
          icon={<AlarmClock className="w-4 h-4" />}
          title={`${toPersianDigits(counts.waiting)} بیمار در صف انتظار`}
          className="mb-5"
        >
          بیمارانی که پذیرش شده‌اند و هنوز درمانشان شروع نشده است.
        </InfoBanner>
      )}

      <SectionCard
        title="لیست پذیرش امروز"
        subtitle={
          statusFilter === 'waiting'
            ? doctorFilter === 'all'
              ? `${toPersianDigits(filtered.length)} بیمار در صف، به ترتیب ساعت پذیرش`
              : `${toPersianDigits(filtered.length)} بیمار در صف این پزشک، به ترتیب شمارهٔ صف`
            : `${toPersianDigits(filtered.length)} نوبت در نمای فعلی`
        }
        action={
          <div className="flex items-center gap-2 flex-wrap">
            {role !== 'doctor' && (
              <select
                className="d-select !h-9 !text-caption w-40"
                value={doctorFilter}
                onChange={(event) => setDoctorFilter(event.target.value)}
                aria-label="فیلتر پزشک"
              >
                <option value="all">همه پزشکان</option>
                {doctors.map((doctor) => (
                  <option key={doctor.id} value={String(doctor.id)}>
                    {doctor.full_name}
                  </option>
                ))}
              </select>
            )}
            {statusFilter !== 'all' && (
              <button
                type="button"
                onClick={() => setStatusFilter('all')}
                className="text-caption font-semibold text-primary"
              >
                پاک کردن فیلتر
              </button>
            )}
          </div>
        }
        noPadding
      >
        {loading && items.length === 0 ? (
          <LoadingPanel message="در حال دریافت نوبت‌های امروز..." />
        ) : filtered.length === 0 ? (
          <div className="d-empty py-12">
            <div className="d-empty-icon">
              <DoorOpen className="w-5 h-5" />
            </div>
            <h4 className="text-body font-bold text-ink mb-1">
              برای این نمای امروز نوبتی نیست
            </h4>
            <p className="text-small text-muted leading-6 max-w-md mx-auto">
              با پاک کردن فیلترها یا رفتن به بخش نوبت‌ها، نوبت جدید ثبت کنید.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-line-soft">
            {filtered.map((item) => {
              const key = flowKey(item);
              const meta = FLOW_META[key];
              const waited = item.waiting_minutes ?? null;
              return (
                <div
                  key={item.id}
                  className={`flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-4 ${
                    key === 'completed' || key === 'cancelled' || key === 'no_show'
                      ? 'bg-surface-muted'
                      : ''
                  }`}
                >
                  {/* Time + queue */}
                  <div className="flex items-center gap-3 sm:w-32 shrink-0">
                    <div className="w-16 text-center">
                      <div className="text-[17px] font-extrabold text-ink tabular-nums leading-6">
                        {formatTimeFa(item.appointment_time)}
                      </div>
                      <div className="text-caption text-faint">
                        {item.is_late && key === 'booked' ? 'تأخیر' : 'نوبت'}
                      </div>
                    </div>
                    {item.queue_number ? (
                      <span
                        className="inline-flex flex-col items-center justify-center w-10 h-10 rounded-[3px] bg-surface-muted border border-line text-ink-soft text-caption font-extrabold"
                        title="شماره صف امروز"
                      >
                        <UserRound className="w-3 h-3" />
                        {toPersianDigits(item.queue_number)}
                      </span>
                    ) : (
                      <span className="w-10 h-10 rounded-full border border-dashed border-line flex items-center justify-center text-line-strong">
                        <UserRound className="w-3.5 h-3.5" />
                      </span>
                    )}
                  </div>

                  {/* Patient */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-small font-bold text-ink">
                        {item.patient_name}
                      </span>
                      <Badge variant={meta.tone} dot>
                        {meta.label}
                      </Badge>
                      {item.is_late && key === 'booked' && (
                        <Badge variant="danger">تأخیر</Badge>
                      )}
                    </div>
                    <div className="text-caption text-muted mt-1 flex items-center gap-2 flex-wrap">
                      <span>{item.service_name}</span>
                      <span className="text-line-strong">•</span>
                      <span>{item.doctor_name}</span>
                      {item.patient_phone && (
                        <>
                          <span className="text-line-strong">•</span>
                          <span className="inline-flex items-center gap-1 tabular-nums" dir="ltr">
                            <Phone className="w-3 h-3" />
                            {toPersianDigits(item.patient_phone)}
                          </span>
                        </>
                      )}
                    </div>
                    {key === 'waiting' && waited !== null && (
                      <div className="text-caption text-warn mt-1">
                        {waited > 120
                          ? 'بیش از ۲ ساعت در انتظار'
                          : `${toPersianDigits(waited)} دقیقه در انتظار`}
                      </div>
                    )}
                    {key === 'in_treatment' && item.started_at && (
                      <div className="text-caption text-primary-deep mt-1">
                        درمان از {formatTimeFa(clockOf(item.started_at))} شروع شده است
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0 flex-wrap">
                    {!canFlow && <span className="text-caption text-faint">فقط مشاهده</span>}
                    {canFlow && key === 'booked' && (
                      <>
                        <Button
                          size="sm"
                          onClick={() => void runAction(item, 'check-in')}
                          isLoading={busyId === item.id}
                          icon={<DoorOpen className="w-3.5 h-3.5" />}
                        >
                          پذیرش بیمار
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void runAction(item, 'no-show')}
                          disabled={busyId === item.id}
                          className="text-danger hover:bg-danger-soft"
                        >
                          عدم مراجعه
                        </Button>
                      </>
                    )}
                    {canFlow && key === 'waiting' && (
                      <Button
                        size="sm"
                        onClick={() => void runAction(item, 'start')}
                        isLoading={busyId === item.id}
                        icon={<PlayCircle className="w-3.5 h-3.5" />}
                      >
                        شروع درمان
                      </Button>
                    )}
                    {canFlow && key === 'in_treatment' && (
                      <Button
                        size="sm"
                        onClick={() => void runAction(item, 'complete')}
                        isLoading={busyId === item.id}
                        icon={<CheckCircle2 className="w-3.5 h-3.5" />}
                      >
                        پایان ویزیت
                      </Button>
                    )}
                    {key === 'completed' && (
                      <span className="inline-flex items-center gap-1 text-caption font-semibold text-primary-deep">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        تسویه/اتمام
                      </span>
                    )}
                    {key === 'no_show' && (
                      <span className="inline-flex items-center gap-1 text-caption font-semibold text-danger">
                        <UserX className="w-3.5 h-3.5" />
                        مراجعه نکرد
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </SectionCard>
    </div>
  );
};
