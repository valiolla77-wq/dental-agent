import React, { useEffect, useMemo, useState } from 'react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { Appointment } from '../../types';
import { AppointmentStatusBadge } from '../common/Badge';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { apiClient } from '../../api/client';
import { formatTimeFa, formatToJalali, todayJalaliString } from '../../utils/persianDate';
import { upcomingDays } from '../../utils/analytics';
import {
  AlertCircle,
  AlertTriangle,
  Ban,
  Calendar,
  CheckCircle2,
  Clock,
  RefreshCw,
  Star,
  Stethoscope,
  User,
  CalendarClock,
} from 'lucide-react';

interface AppointmentDetailsModalProps {
  isOpen: boolean;
  onClose: () => void;
  appointment: Appointment | null;
}

type Mode = 'view' | 'cancel' | 'reschedule' | 'rate';

export const AppointmentDetailsModal: React.FC<AppointmentDetailsModalProps> = ({
  isOpen,
  onClose,
  appointment,
}) => {
  const { cancelAppointment, rescheduleAppointment, getAvailableSlots } = useClinic();
  const { hasPerm, currentUser } = useAuth();

  const [mode, setMode] = useState<Mode>('view');
  const [cancelling, setCancelling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Post-visit satisfaction rating (patient self-service).
  const [alreadyRated, setAlreadyRated] = useState(false);
  const [rating, setRating] = useState(0);
  const [ratingHover, setRatingHover] = useState(0);
  const [ratingComment, setRatingComment] = useState('');
  const [ratingBusy, setRatingBusy] = useState(false);

  const days = useMemo(() => upcomingDays(30), []);
  const [dateIso, setDateIso] = useState('');
  const [time, setTime] = useState('');
  const [slots, setSlots] = useState<string[]>([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [slotsError, setSlotsError] = useState<string | null>(null);
  const [slotsAttempt, setSlotsAttempt] = useState(0);

  useEffect(() => {
    if (!isOpen) return;
    setMode('view');
    setFeedback(null);
    setError(null);
    setTime('');
    setSlots([]);
    setSlotsError(null);
    setRating(0);
    setRatingHover(0);
    setRatingComment('');
    const existingDay = days.find((day) => day.jalali === appointment?.appointment_date);
    setDateIso(existingDay?.iso || days[0]?.iso || '');
  }, [isOpen, appointment?.id, days, appointment?.appointment_date]);

  // One rating per appointment: hide the survey for already-rated visits.
  useEffect(() => {
    if (!isOpen || !appointment) return;
    if (currentUser?.role !== 'patient' || !hasPerm('rate_visits')) return;
    let current = true;
    apiClient
      .getMyVisitRatings()
      .then((rows) => {
        if (current) {
          setAlreadyRated(rows.some((row) => row.appointment_id === appointment.id));
        }
      })
      .catch(() => {
        if (current) setAlreadyRated(false);
      });
    return () => {
      current = false;
    };
  }, [isOpen, appointment, currentUser?.role, hasPerm]);

  const selectedDay = days.find((day) => day.iso === dateIso) || null;

  useEffect(() => {
    if (!isOpen || mode !== 'reschedule' || !appointment || !selectedDay) return;
    let current = true;
    setSlotsLoading(true);
    setSlotsError(null);
    getAvailableSlots(appointment.doctor_id, selectedDay.jalali)
      .then((result) => {
        if (!current) return;
        const normalized = Array.from(
          new Set((result || []).map((slot) => String(slot).slice(0, 5)).filter(Boolean))
        ).sort();
        setSlots(normalized);
        setTime((prev) => (prev && normalized.includes(prev) ? prev : ''));
      })
      .catch((err: any) => {
        if (!current) return;
        setSlots([]);
        setTime('');
        setSlotsError(err?.message || 'دریافت زمان‌های خالی ناکام ماند.');
      })
      .finally(() => {
        if (current) setSlotsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [isOpen, mode, appointment, selectedDay, getAvailableSlots, slotsAttempt]);

  if (!appointment) return null;

  const isCancelled = appointment.status === 'cancelled';
  const isCompleted = appointment.status === 'completed';
  const canModify = !isCancelled && !isCompleted;

  // A past, non-cancelled slot is rateable (the server enforces the same rule).
  const today = todayJalaliString();
  const nowClock = new Date().toTimeString().slice(0, 5);
  const slotClock = appointment.appointment_time.slice(0, 5);
  const isPastVisit =
    appointment.appointment_date < today ||
    (appointment.appointment_date === today && slotClock < nowClock);
  const canRateVisit =
    currentUser?.role === 'patient' &&
    hasPerm('rate_visits') &&
    !isCancelled &&
    isPastVisit &&
    !alreadyRated;

  const submitRating = async () => {
    if (rating < 1) return;
    setRatingBusy(true);
    setError(null);
    try {
      await apiClient.submitVisitRating({
        appointment_id: appointment.id,
        rating,
        comment: ratingComment.trim() || null,
      });
      setAlreadyRated(true);
      setMode('view');
      setFeedback('نظر شما ثبت شد؛ ممنون از بازخوردتان.');
      setTimeout(() => onClose(), 1400);
    } catch (err: any) {
      setError(err?.message || 'ثبت امتیاز ناکام ماند.');
    } finally {
      setRatingBusy(false);
    }
  };

  const confirmCancel = async () => {
    setCancelling(true);
    setError(null);
    try {
      await cancelAppointment(appointment.id);
      setFeedback('نوبت با موفقیت در سرور لغو شد.');
      setMode('view');
      setTimeout(() => {
        onClose();
      }, 1200);
    } catch (err: any) {
      setError(err?.message || 'لغو نوبت ناکام ماند.');
    } finally {
      setCancelling(false);
    }
  };

  const confirmReschedule = async () => {
    if (!selectedDay || !time) {
      setError('لطفاً تاریخ و ساعت جدید را انتخاب کنید.');
      return;
    }
    if (
      selectedDay.jalali === appointment.appointment_date &&
      time === appointment.appointment_time.slice(0, 5)
    ) {
      setError('زمان انتخاب‌شده با نوبت فعلی یکسان است.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await rescheduleAppointment(appointment.id, {
        appointment_date: selectedDay.jalali,
        appointment_time: time,
      });
      setFeedback('زمان نوبت با موفقیت تغییر کرد.');
      setMode('view');
      setTimeout(() => onClose(), 1200);
    } catch (err: any) {
      setError(err?.message || 'تغییر زمان نوبت ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        mode === 'reschedule'
          ? 'تغییر زمان نوبت'
          : mode === 'cancel'
            ? 'لغو نوبت'
            : mode === 'rate'
              ? 'ثبت رضایت از ویزیت'
              : 'جزئیات نوبت'
      }
      subtitle={`شناسه نوبت: ${appointment.id}`}
      maxWidth={mode === 'reschedule' ? '2xl' : 'lg'}
    >
      <div className="space-y-4">
        {feedback && (
          <div className="d-soft-teal px-3.5 py-2.5 text-caption text-primary-deep flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            {feedback}
          </div>
        )}
        {error && (
          <div className="d-soft-danger px-3.5 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        {mode === 'view' && (
          <>
            <div className="flex items-center justify-between gap-3 p-4 rounded-[4px] bg-surface-muted border border-line">
              <div>
                <div className="text-caption text-faint">وضعیت نوبت</div>
                <div className="mt-1.5">
                  <AppointmentStatusBadge status={appointment.status} />
                </div>
              </div>
              <div className="text-left">
                <div className="text-caption text-faint">تاریخ ثبت در سرور</div>
                <div className="text-caption font-semibold text-muted mt-1.5">
                  {formatToJalali(appointment.appointment_date, true)}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                { label: 'بیمار', value: appointment.patient_name, icon: User },
                { label: 'پزشک معالج', value: appointment.doctor_name, icon: Stethoscope },
                {
                  label: 'تاریخ نوبت',
                  value: formatToJalali(appointment.appointment_date, true),
                  icon: Calendar,
                },
                {
                  label: 'ساعت نوبت',
                  value: formatTimeFa(appointment.appointment_time),
                  icon: Clock,
                },
                { label: 'خدمت', value: appointment.service_name, icon: Stethoscope },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div key={item.label} className="rounded-[4px] border border-line p-3.5">
                    <div className="flex items-center gap-1.5 text-caption text-faint">
                      <Icon className="w-3.5 h-3.5" />
                      {item.label}
                    </div>
                    <div className="text-small font-bold text-ink mt-1.5 leading-5">
                      {item.value}
                    </div>
                  </div>
                );
              })}
            </div>

            {appointment.reason && (
              <div className="rounded-[4px] border border-line p-3.5">
                <div className="text-caption text-faint mb-1">توضیحات و علت مراجعه</div>
                <p className="text-caption text-muted leading-6">{appointment.reason}</p>
              </div>
            )}

            {alreadyRated && (
              <div className="d-soft-teal px-3.5 py-2.5 text-caption text-primary-deep flex items-center gap-2">
                <Star className="w-4 h-4 shrink-0" />
                برای این ویزیت رضایت ثبت کرده‌اید؛ ممنون از بازخوردتان.
              </div>
            )}

            {canRateVisit && (
              <div className="rounded-[4px] border border-ai-line bg-ai-surface p-4">
                <div className="flex items-center gap-2 text-small font-bold text-ai">
                  <Star className="w-4 h-4" />
                  این ویزیت چطور بود؟
                </div>
                <p className="text-caption text-muted mt-1.5 leading-5">
                  رضایت شما به ارتقای کیفیت خدمات کلینیک کمک می‌کند.
                </p>
                <Button
                  size="sm"
                  variant="ai"
                  className="mt-3"
                  onClick={() => {
                    setMode('rate');
                    setError(null);
                  }}
                  icon={<Star className="w-3.5 h-3.5" />}
                >
                  ثبت رضایت
                </Button>
              </div>
            )}

            <div className="flex items-center justify-between gap-2 border-t border-line-soft pt-4 flex-wrap">
              <div className="flex items-center gap-2">
                {canModify && hasPerm('reschedule_appointment') && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setMode('reschedule');
                      setError(null);
                      setTime('');
                    }}
                    icon={<CalendarClock className="w-3.5 h-3.5" />}
                  >
                    تغییر زمان
                  </Button>
                )}
                {canModify && hasPerm('cancel_appointment') && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-danger border-danger-line hover:bg-danger-soft"
                    onClick={() => {
                      setMode('cancel');
                      setError(null);
                    }}
                    icon={<Ban className="w-3.5 h-3.5" />}
                  >
                    لغو نوبت
                  </Button>
                )}
              </div>
              <Button size="sm" onClick={onClose}>
                بستن
              </Button>
            </div>
          </>
        )}

        {mode === 'rate' && (
          <div className="space-y-4">
            <div className="text-center py-2">
              <div className="text-small font-bold text-ink">
                تجربه شما از «{appointment.service_name}» چطور بود؟
              </div>
              <div className="flex items-center justify-center gap-1.5 mt-4" dir="ltr">
                {[1, 2, 3, 4, 5].map((value) => {
                  const filled = value <= (ratingHover || rating);
                  return (
                    <button
                      key={value}
                      type="button"
                      onMouseEnter={() => setRatingHover(value)}
                      onMouseLeave={() => setRatingHover(0)}
                      onClick={() => setRating(value)}
                      aria-label={`${value} ستاره`}
                      className="p-1 transition-transform hover:scale-110"
                    >
                      <Star
                        className={`w-8 h-8 transition-colors ${
                          filled ? 'text-warn fill-[#8a6416]' : 'text-line-strong'
                        }`}
                      />
                    </button>
                  );
                })}
              </div>
              <div className="text-caption text-muted mt-2 h-5">
                {rating > 0 &&
                  ['خیلی بد', 'بد', 'متوسط', 'خوب', 'عالی'][rating - 1]}
              </div>
            </div>

            <textarea
              value={ratingComment}
              onChange={(event) => setRatingComment(event.target.value)}
              placeholder="نظر شما (اختیاری)"
              rows={3}
              maxLength={2000}
              className="w-full rounded-[4px] border border-line bg-surface px-3 py-2.5 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30"
            />

            <div className="flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setMode('view')}
                disabled={ratingBusy}
              >
                بازگشت
              </Button>
              <Button
                size="sm"
                variant="ai"
                onClick={() => void submitRating()}
                isLoading={ratingBusy}
                disabled={rating < 1}
                icon={<Star className="w-3.5 h-3.5" />}
              >
                ثبت امتیاز
              </Button>
            </div>
          </div>
        )}

        {mode === 'cancel' && (
          <div className="space-y-4">
            <div className="d-soft-danger p-4">
              <div className="flex items-center gap-2 text-small font-bold text-danger">
                <AlertTriangle className="w-4 h-4" />
                آیا از لغو این نوبت اطمینان دارید؟
              </div>
              <p className="text-caption text-muted mt-2 leading-6">
                نوبت {appointment.service_name} در تاریخ {formatToJalali(appointment.appointment_date, true)} ساعت{' '}
                {formatTimeFa(appointment.appointment_time)} لغو می‌شود. این اقدام روی سرور ثبت شده و
                قابل بازگشت خودکار نیست.
              </p>
            </div>
            <div className="flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setMode('view')}
                disabled={cancelling}
              >
                بازگشت
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={confirmCancel}
                isLoading={cancelling}
                icon={<Ban className="w-3.5 h-3.5" />}
              >
                تأیید لغو نوبت
              </Button>
            </div>
          </div>
        )}

        {mode === 'reschedule' && (
          <div className="space-y-4">
            <div className="d-soft-info px-3.5 py-2.5 text-caption text-info leading-5">
              پزشک و خدمت ثابت می‌مانند. زمان‌های قابل انتخاب مستقیماً از سرور خوانده می‌شوند.
            </div>

            <div>
              <div className="d-label">تاریخ جدید</div>
              <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
                {days.map((day) => {
                  const active = dateIso === day.iso;
                  return (
                    <button
                      key={day.iso}
                      type="button"
                      onClick={() => {
                        setDateIso(day.iso);
                        setTime('');
                      }}
                      className={`shrink-0 w-[62px] rounded-[4px] border py-2.5 text-center transition-colors ${
                        active
                          ? 'bg-primary border-primary text-on-accent'
                          : 'bg-surface border-line text-muted hover:border-primary-line'
                      }`}
                    >
                      <div className={`text-caption ${active ? 'text-on-accent/75' : 'text-faint'}`}>
                        {day.weekday}
                      </div>
                      <div className="text-lead font-extrabold mt-0.5 tabular-nums">
                        {String(day.day).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)])}
                      </div>
                      <div className={`text-caption mt-0.5 ${active ? 'text-on-accent/75' : 'text-faint'}`}>
                        {day.monthName}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5 text-caption font-bold text-muted">
                  <Clock className="w-3.5 h-3.5 text-faint" />
                  زمان‌های خالی
                </div>
                <button
                  type="button"
                  onClick={() => setSlotsAttempt((attempt) => attempt + 1)}
                  disabled={slotsLoading}
                  className="text-caption text-primary inline-flex items-center gap-1 disabled:opacity-50"
                >
                  <RefreshCw className={`w-3 h-3 ${slotsLoading ? 'animate-spin' : ''}`} />
                  به‌روزرسانی
                </button>
              </div>
              {slotsLoading ? (
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                  {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((item) => (
                    <div key={item} className="d-skeleton h-9 rounded-[3px]" />
                  ))}
                </div>
              ) : slotsError ? (
                <div className="d-soft-danger p-3 text-caption text-danger leading-5">
                  {slotsError}
                </div>
              ) : slots.length === 0 ? (
                <div className="d-empty py-6">
                  <div className="d-empty-icon">
                    <Clock className="w-5 h-5" />
                  </div>
                  <p className="text-caption text-muted">
                    برای این روز زمان خالی ثبت نشده است. روز دیگری را انتخاب کنید.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                  {slots.map((slot) => (
                    <button
                      key={slot}
                      type="button"
                      onClick={() => setTime(slot)}
                      className={`h-9 rounded-[3px] border text-small font-semibold tabular-nums transition-colors ${
                        time === slot
                          ? 'bg-primary border-primary text-on-accent'
                          : 'bg-surface border-line text-ink hover:border-primary-line'
                      }`}
                    >
                      {formatTimeFa(slot)}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-line-soft pt-4">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setMode('view')}
                disabled={saving}
              >
                انصراف
              </Button>
              <Button
                size="sm"
                onClick={confirmReschedule}
                isLoading={saving}
                disabled={!time}
                icon={<CalendarClock className="w-3.5 h-3.5" />}
              >
                ثبت زمان جدید
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
};
