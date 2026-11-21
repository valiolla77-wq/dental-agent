/**
 * پزشکان و شیفت‌ها — admin management surface for the doctor catalog.
 *
 * Completes the CRUD the read-only team catalog lacked: create/edit doctors
 * with their offered services, weekly schedule editing (add/update/delete),
 * linking a doctor record to its staff account, and activating/deactivating.
 * The patient-facing booking flow keeps using the read-only catalog view.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CalendarPlus,
  Link2,
  Pencil,
  Search,
  Stethoscope,
  Trash2,
  UserPlus,
} from 'lucide-react';
import { Doctor, DoctorSchedule, DentalService } from '../../types';
import { apiClient } from '../../api/client';
import { useClinic } from '../../context/ClinicContext';
import {
  Avatar,
  ErrorBanner,
  InfoBanner,
  LoadingPanel,
  PageHeader,
  SectionCard,
  StatCard,
} from '../common/ui';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { EmptyState } from '../common/EmptyState';
import { Modal } from '../common/Modal';
import { toPersianDigits } from '../../utils/persianDate';
import { formatTimeFa } from '../../utils/persianDate';

/** Backend convention: Saturday=0 … Friday=6 (Asia/Tehran work week). */
const WORK_WEEK_DAYS: { value: number; label: string }[] = [
  { value: 0, label: 'شنبه' },
  { value: 1, label: 'یکشنبه' },
  { value: 2, label: 'دوشنبه' },
  { value: 3, label: 'سه‌شنبه' },
  { value: 4, label: 'چهارشنبه' },
  { value: 5, label: 'پنج‌شنبه' },
  { value: 6, label: 'جمعه' },
];

function dayLabel(value: number): string {
  return WORK_WEEK_DAYS.find((day) => day.value === value)?.label || '—';
}

export const DoctorsManageView: React.FC = () => {
  const { services } = useClinic();
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [formModal, setFormModal] = useState<{ mode: 'create' | 'edit'; doctor?: Doctor } | null>(null);
  const [scheduleModal, setScheduleModal] = useState<Doctor | null>(null);
  const [linkModal, setLinkModal] = useState<Doctor | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const loadDoctors = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      // One admin call returns contact data + account/service links.
      const managementDoctors = await apiClient.listDoctorsForManagement();
      setDoctors(managementDoctors);
    } catch (err: any) {
      setLoadError(err.message || 'دریافت فهرست پزشکان ناکام ماند.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDoctors();
  }, [loadDoctors]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(timer);
  }, [toast]);

  const filtered = useMemo(() => {
    const needle = search.trim();
    if (!needle) return doctors;
    return doctors.filter(
      (doctor) => doctor.full_name.includes(needle) || doctor.specialty.includes(needle)
    );
  }, [doctors, search]);

  const stats = useMemo(() => {
    const active = doctors.filter((doctor) => doctor.is_active).length;
    return {
      total: doctors.length,
      active,
      inactive: doctors.length - active,
    };
  }, [doctors]);

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="پزشکان و شیفت‌ها"
        eyebrow="مدیریت کادر درمان"
        subtitle="پزشک‌ها را اضافه یا ویرایش کنید، خدمات هر پزشک و شیفت‌های هفتگی را تنظیم و حساب کاربری‌شان را متصل کنید."
        action={
          <Button
            icon={<UserPlus className="w-4 h-4" />}
            onClick={() => setFormModal({ mode: 'create' })}
          >
            ثبت پزشک جدید
          </Button>
        }
      />

      {toast && (
        <div className="d-soft-teal px-4 py-3 mb-4 text-small text-primary-deep flex items-center gap-2">
          <Stethoscope className="w-4 h-4 shrink-0" />
          {toast}
        </div>
      )}

      <div className="grid grid-cols-3 gap-3.5 mb-6">
        <StatCard
          icon={<Stethoscope className="w-4.5 h-4.5" />}
          label="کل پزشکان"
          value={stats.total}
        />
        <StatCard
          icon={<Stethoscope className="w-4.5 h-4.5" />}
          label="فعال برای نوبت‌دهی"
          value={stats.active}
          tone="soft"
        />
        <StatCard
          icon={<Stethoscope className="w-4.5 h-4.5" />}
          label="غیرفعال"
          value={stats.inactive}
          tone="warn"
        />
      </div>

      <SectionCard
        title="فهرست پزشکان"
        subtitle="خدمات و شیفت‌های هر پزشک را از ستون عملیات باز کنید."
        noPadding
        action={
          <div className="relative w-[220px]">
            <Search className="w-4 h-4 text-faint absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              className="d-input !pr-9 !h-9 text-caption"
              placeholder="جستجوی نام یا تخصص..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="جستجوی پزشک"
            />
          </div>
        }
      >
        {isLoading ? (
          <LoadingPanel message="در حال دریافت پزشکان..." />
        ) : loadError ? (
          <div className="p-5">
            <ErrorBanner message={loadError} onRetry={loadDoctors} />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Stethoscope className="w-8 h-8" />}
            title="پزشکی پیدا نشد"
            description="اولین پزشک کلینیک را ثبت کنید یا عبارت جستجو را تغییر دهید."
            actionLabel="ثبت پزشک جدید"
            onAction={() => setFormModal({ mode: 'create' })}
          />
        ) : (
          <div className="overflow-x-auto no-scrollbar">
            <table className="w-full text-right d-table">
              <thead>
                <tr>
                  <th>پزشک</th>
                  <th className="text-center">خدمات</th>
                  <th className="text-center">وضعیت</th>
                  <th className="text-center">حساب کاربری</th>
                  <th className="text-center">عملیات</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((doctor) => (
                  <tr key={doctor.id}>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <Avatar name={doctor.full_name} size="sm" />
                        <div className="min-w-0">
                          <div className="text-small font-bold text-ink truncate">
                            {doctor.full_name}
                          </div>
                          <div className="text-caption text-faint">
                            {doctor.specialty}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="text-center text-caption text-muted whitespace-nowrap">
                      {toPersianDigits(getServiceCount(doctor, services))} خدمت
                    </td>
                    <td className="text-center">
                      {doctor.is_active ? (
                        <Badge variant="success" dot>فعال</Badge>
                      ) : (
                        <Badge variant="danger" dot>غیرفعال</Badge>
                      )}
                    </td>
                    <td className="text-center">
                      <Badge variant={doctor.user_id ? 'teal' : 'default'}>
                        {doctor.user_id ? 'متصل' : 'بدون حساب'}
                      </Badge>
                    </td>
                    <td className="text-center">
                      <div className="inline-flex items-center justify-center gap-1">
                        <button
                          type="button"
                          title="شیفت‌های هفتگی"
                          aria-label={`شیفت‌های هفتگی ${doctor.full_name}`}
                          onClick={() => setScheduleModal(doctor)}
                          className="p-2 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
                        >
                          <CalendarPlus className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          title="ویرایش پزشک"
                          aria-label={`ویرایش ${doctor.full_name}`}
                          onClick={() => setFormModal({ mode: 'edit', doctor })}
                          className="p-2 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          title="اتصال حساب کاربری"
                          aria-label={`اتصال حساب ${doctor.full_name}`}
                          onClick={() => setLinkModal(doctor)}
                          disabled={!!doctor.user_id}
                          className="p-2 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors disabled:opacity-30 disabled:pointer-events-none"
                        >
                          <Link2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {formModal && (
        <DoctorFormModal
          mode={formModal.mode}
          doctor={formModal.doctor}
          services={services}
          onClose={() => setFormModal(null)}
          onDone={async (message) => {
            setFormModal(null);
            setToast(message);
            await loadDoctors();
          }}
        />
      )}

      {scheduleModal && (
        <SchedulesModal
          doctor={scheduleModal}
          onClose={() => setScheduleModal(null)}
          onDone={setToast}
        />
      )}

      {linkModal && (
        <LinkDoctorAccountModal
          doctor={linkModal}
          onClose={() => setLinkModal(null)}
          onDone={async (message) => {
            setLinkModal(null);
            setToast(message);
            await loadDoctors();
          }}
        />
      )}
    </div>
  );
};

/** The management listing carries the service membership directly. */
function getServiceCount(doctor: Doctor, _services: DentalService[]): number {
  return doctor.service_ids?.length ?? 0;
}

/* ------------------------------------------------------- doctor form */

const DoctorFormModal: React.FC<{
  mode: 'create' | 'edit';
  doctor?: Doctor;
  services: DentalService[];
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ mode, doctor, services, onClose, onDone }) => {
  const [fullName, setFullName] = useState(doctor?.full_name || '');
  const [specialty, setSpecialty] = useState(doctor?.specialty || '');
  const [phone, setPhone] = useState('');
  const [isActive, setIsActive] = useState(doctor?.is_active ?? true);
  const [selectedServices, setSelectedServices] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(mode === 'edit');

  useEffect(() => {
    if (mode !== 'edit' || !doctor) return;
    let cancelled = false;
    (async () => {
      try {
        const [full, doctorServices] = await Promise.all([
          apiClient.getDoctorForManagement(doctor.id),
          apiClient.getDoctorServices(doctor.id),
        ]);
        if (cancelled) return;
        setFullName(full.full_name);
        setSpecialty(full.specialty);
        setPhone(full.phone);
        setIsActive(full.is_active);
        setSelectedServices(doctorServices.map((service) => service.id));
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'خواندن اطلاعات پزشک ناکام ماند.');
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, doctor]);

  const toggleService = (serviceId: number) => {
    setSelectedServices((prev) =>
      prev.includes(serviceId)
        ? prev.filter((id) => id !== serviceId)
        : [...prev, serviceId]
    );
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const safePhone = phone.replace(/\D/g, '');
    if (!fullName.trim() || !specialty.trim() || safePhone.length < 8) {
      setError('نام، تخصص و شماره تلفن معتبر الزامی است.');
      return;
    }
    setSaving(true);
    try {
      if (mode === 'create') {
        await apiClient.createDoctor({
          full_name: fullName.trim(),
          specialty: specialty.trim(),
          phone: safePhone,
          service_ids: selectedServices,
        });
        onDone(`پزشک «${fullName.trim()}» ثبت شد.`);
      } else if (doctor) {
        await apiClient.updateDoctor(doctor.id, {
          full_name: fullName.trim(),
          specialty: specialty.trim(),
          phone: safePhone,
          is_active: isActive,
          service_ids: selectedServices,
        });
        onDone(`اطلاعات «${fullName.trim()}» به‌روزرسانی شد.`);
      }
    } catch (err: any) {
      setError(err.message || 'ذخیرهٔ پزشک ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={mode === 'create' ? 'ثبت پزشک جدید' : `ویرایش ${doctor?.full_name}`}
      subtitle="خدمات انتخاب‌شده در نوبت‌دهی و دستیار هوشمند برای این پزشک نمایش داده می‌شود."
    >
      {loadingDetail ? (
        <LoadingPanel message="در حال خواندن اطلاعات پزشک..." />
      ) : (
        <form onSubmit={submit} className="space-y-4">
          {error && (
            <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span className="leading-5">{error}</span>
            </div>
          )}

          <div>
            <label className="d-label" htmlFor="doctor-name">نام و نام خانوادگی</label>
            <input
              id="doctor-name"
              className="d-input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="مثلاً دکتر سارا احمدی"
              required
            />
          </div>

          <div>
            <label className="d-label" htmlFor="doctor-specialty">تخصص</label>
            <input
              id="doctor-specialty"
              className="d-input"
              value={specialty}
              onChange={(e) => setSpecialty(e.target.value)}
              placeholder="مثلاً دندانپزشکی ترمیمی"
              required
            />
          </div>

          <div>
            <label className="d-label" htmlFor="doctor-phone">شماره تلفن</label>
            <input
              id="doctor-phone"
              className="d-input tabular-nums"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="۰۹۱۲۱۲۳۴۵۶۷"
              dir="ltr"
              inputMode="tel"
              required
            />
            <p className="text-caption text-faint mt-1.5 leading-5">
              این شماره معیار اتصال حساب کاربری پزشک است؛ حساب با همان شماره باید از قبل ساخته شده باشد.
            </p>
          </div>

          <div>
            <span className="d-label">خدمات ارائه‌شده</span>
            <div className="flex flex-wrap gap-2 mt-1.5">
              {services.length === 0 && (
                <span className="text-caption text-faint">
                  هنوز خدمتی ثبت نشده است؛ از بخش خدمات اضافه کنید.
                </span>
              )}
              {services.map((service) => {
                const checked = selectedServices.includes(service.id);
                return (
                  <button
                    key={service.id}
                    type="button"
                    onClick={() => toggleService(service.id)}
                    aria-pressed={checked}
                    className={`text-caption font-semibold rounded-full border px-3 h-8 transition-colors ${
                      checked
                        ? 'bg-primary-soft border-primary-line text-primary-deep'
                        : 'bg-surface border-line text-muted hover:border-primary-line'
                    }`}
                  >
                    {service.name}
                  </button>
                );
              })}
            </div>
          </div>

          {mode === 'edit' && (
            <label className="flex items-center gap-2 text-small text-ink">
              <input
                type="checkbox"
                className="accent-primary w-4 h-4"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
              />
              فعال برای نوبت‌دهی
            </label>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
            <Button type="submit" isLoading={saving}>
              {mode === 'create' ? 'ثبت پزشک' : 'ذخیرهٔ تغییرات'}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
};

/* -------------------------------------------------------- schedules */

const SchedulesModal: React.FC<{
  doctor: Doctor;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ doctor, onClose, onDone }) => {
  const [schedules, setSchedules] = useState<DoctorSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState(0);
  const [start, setStart] = useState('09:00');
  const [end, setEnd] = useState('13:00');
  const [slot, setSlot] = useState(30);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiClient.getDoctorSchedules(doctor.id);
      setSchedules(rows.sort((a, b) => a.day_of_week - b.day_of_week));
      setError(null);
    } catch (err: any) {
      setError(err.message || 'خواندن شیفت‌ها ناکام ماند.');
    } finally {
      setLoading(false);
    }
  }, [doctor.id]);

  useEffect(() => {
    load();
  }, [load]);

  const addSchedule = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (start >= end) {
      setError('ساعت پایان باید بعد از ساعت شروع باشد.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.createDoctorSchedule({
        doctor_id: doctor.id,
        day_of_week: day,
        start_time: start,
        end_time: end,
        slot_duration_minutes: slot,
      });
      onDone(`شیفت ${dayLabel(day)} برای «${doctor.full_name}» اضافه شد.`);
      await load();
    } catch (err: any) {
      setError(err.message || 'افزودن شیفت ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  const removeSchedule = async (scheduleId: number) => {
    try {
      await apiClient.deleteDoctorSchedule(scheduleId);
      onDone('شیفت حذف شد.');
      await load();
    } catch (err: any) {
      setError(err.message || 'حذف شیفت ناکام ماند.');
    }
  };

  const toggleActive = async (schedule: DoctorSchedule) => {
    try {
      await apiClient.updateDoctorSchedule(schedule.id, {
        day_of_week: schedule.day_of_week,
        start_time: schedule.start_time.slice(0, 5),
        end_time: schedule.end_time.slice(0, 5),
        slot_duration_minutes: schedule.slot_duration_minutes,
        is_active: !schedule.is_active,
      });
      await load();
    } catch (err: any) {
      setError(err.message || 'تغییر وضعیت شیفت ناکام ماند.');
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`شیفت‌های هفتگی ${doctor.full_name}`}
      subtitle="بیماران فقط در بازه‌های فعال می‌توانند نوبت بگیرند."
      maxWidth="lg"
    >
      <div className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        {loading ? (
          <LoadingPanel message="در حال خواندن شیفت‌ها..." />
        ) : schedules.length === 0 ? (
          <EmptyState
            icon={<CalendarPlus className="w-8 h-8" />}
            title="هنوز شیفعی ثبت نشده"
            description="برای این پزشک یک بازهٔ کاری هفتگی اضافه کنید."
          />
        ) : (
          <ul className="space-y-2">
            {schedules.map((schedule) => (
              <li
                key={schedule.id}
                className="flex items-center justify-between gap-3 border border-line rounded-[4px] px-3.5 py-2.5"
              >
                <div className="min-w-0">
                  <div className="text-small font-bold text-ink">
                    {dayLabel(schedule.day_of_week)}
                  </div>
                  <div className="text-caption text-muted tabular-nums">
                    {formatTimeFa(schedule.start_time.slice(0, 5))} تا{' '}
                    {formatTimeFa(schedule.end_time.slice(0, 5))} — نوبت‌های{' '}
                    {toPersianDigits(schedule.slot_duration_minutes)} دقیقه‌ای
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Badge variant={schedule.is_active ? 'success' : 'default'} dot>
                    {schedule.is_active ? 'فعال' : 'متوقف'}
                  </Badge>
                  <button
                    type="button"
                    title={schedule.is_active ? 'توقف موقت' : 'فعال‌سازی'}
                    onClick={() => toggleActive(schedule)}
                    className="p-2 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    title="حذف شیفت"
                    onClick={() => removeSchedule(schedule.id)}
                    className="p-2 rounded-[3px] text-faint hover:text-danger hover:bg-danger-soft transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={addSchedule} className="border-t border-line-soft pt-4 space-y-3">
          <div className="text-small font-bold text-ink">افزودن شیفت جدید</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div>
              <label className="d-label" htmlFor="schedule-day">روز هفته</label>
              <select
                id="schedule-day"
                className="d-select"
                value={day}
                onChange={(e) => setDay(Number(e.target.value))}
              >
                {WORK_WEEK_DAYS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="d-label" htmlFor="schedule-start">از ساعت</label>
              <input
                id="schedule-start"
                type="time"
                className="d-input tabular-nums"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="d-label" htmlFor="schedule-end">تا ساعت</label>
              <input
                id="schedule-end"
                type="time"
                className="d-input tabular-nums"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="d-label" htmlFor="schedule-slot">طول نوبت (دقیقه)</label>
              <input
                id="schedule-slot"
                type="number"
                min={5}
                max={240}
                step={5}
                className="d-input tabular-nums"
                value={slot}
                onChange={(e) => setSlot(Number(e.target.value) || 30)}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button type="submit" size="sm" isLoading={saving} icon={<CalendarPlus className="w-4 h-4" />}>
              افزودن شیفت
            </Button>
          </div>
        </form>
      </div>
    </Modal>
  );
};

/* ------------------------------------------------------ link account */

const LinkDoctorAccountModal: React.FC<{
  doctor: Doctor;
  onClose: () => void;
  onDone: (message: string) => void;
}> = ({ doctor, onClose, onDone }) => {
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const safePhone = phone.replace(/\D/g, '');
    if (!safePhone) {
      setError('شماره تلفن حساب پزشک را وارد کنید.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.linkDoctorUser(doctor.id, safePhone);
      onDone(`حساب پزشک با شماره ${safePhone} به «${doctor.full_name}» متصل شد.`);
    } catch (err: any) {
      setError(
        err.message ||
          'اتصال ناکام ماند؛ شماره باید با تلفن پروندهٔ پزشک یکی باشد و حساب با نقش پزشک از قبل ساخته شده باشد.'
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`اتصال حساب کاربری به ${doctor.full_name}`}
      subtitle="پزشک پس از اتصال، از درگاه پرسنل برنامهٔ کاری و بیماران مجاز خود را می‌بیند."
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <InfoBanner tone="info">
          پیش‌نیازها: حسابی با نقش «پزشک» و همین شماره تلفن در بخش پرسنل ساخته شده باشد و
          پروندهٔ پزشک هنوز به حساب دیگری متصل نباشد.
        </InfoBanner>

        <div>
          <label className="d-label" htmlFor="link-phone">شماره تلفن حساب پزشک</label>
          <input
            id="link-phone"
            className="d-input tabular-nums"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="۰۹۱۲۱۲۳۴۵۶۷"
            dir="ltr"
            inputMode="tel"
            required
          />
        </div>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          <Button type="submit" isLoading={saving} icon={<Link2 className="w-4 h-4" />}>
            اتصال حساب
          </Button>
        </div>
      </form>
    </Modal>
  );
};
