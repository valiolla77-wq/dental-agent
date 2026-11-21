import React, { useMemo, useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { Appointment, AppointmentStatus } from '../../types';
import { AppointmentStatusBadge } from '../common/Badge';
import { Button } from '../common/Button';
import { EmptyState } from '../common/EmptyState';
import { AppointmentBookingModal } from './AppointmentBookingModal';
import { AppointmentDetailsModal } from './AppointmentDetailsModal';
import { formatTimeFa, formatToJalali, toPersianDigits } from '../../utils/persianDate';
import {
  currentWeekDays,
  formatWeekRange,
  sortAppointments,
} from '../../utils/analytics';
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock,
  Plus,
  Search,
  Stethoscope,
  UserRound,
} from 'lucide-react';
import { PageHeader, Segmented } from '../common/ui';

type ViewMode = 'week' | 'list';
type StatusFilter = 'all' | AppointmentStatus;

export const AppointmentsView: React.FC = () => {
  const { appointments, doctors } = useClinic();
  const { currentUser, hasPerm } = useAuth();

  const [viewMode, setViewMode] = useState<ViewMode>('week');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [doctorFilter, setDoctorFilter] = useState('all');
  const [weekOffset, setWeekOffset] = useState(0);
  const [bookingOpen, setBookingOpen] = useState(false);
  const [selected, setSelected] = useState<Appointment | null>(null);

  const role = currentUser?.role || 'patient';

  const baseAppointments = useMemo(() => {
    if (role === 'patient') {
      // `/appointments/me` is already scoped server-side to every patient
      // record owned by this account; filtering here would hide family rows.
      return appointments;
    }
    if (role === 'doctor') {
      return appointments.filter(
        (appointment) =>
          (currentUser?.doctor && appointment.doctor_id === currentUser.doctor.id) ||
          appointment.doctor_name.includes(currentUser?.full_name || '')
      );
    }
    return appointments;
  }, [appointments, role, currentUser]);

  const filtered = useMemo(() => {
    return sortAppointments(
      baseAppointments.filter((appointment) => {
        if (statusFilter !== 'all' && appointment.status !== statusFilter) return false;
        if (doctorFilter !== 'all' && String(appointment.doctor_id) !== doctorFilter) return false;
        if (searchQuery.trim()) {
          const query = searchQuery.trim().toLowerCase();
          return (
            appointment.patient_name.toLowerCase().includes(query) ||
            appointment.doctor_name.toLowerCase().includes(query) ||
            appointment.service_name.toLowerCase().includes(query) ||
            String(appointment.id).includes(query)
          );
        }
        return true;
      })
    );
  }, [baseAppointments, statusFilter, doctorFilter, searchQuery]);

  const anchor = useMemo(() => {
    const date = new Date();
    date.setDate(date.getDate() + weekOffset * 7);
    return date;
  }, [weekOffset]);

  const weekDays = useMemo(() => currentWeekDays(anchor), [anchor]);
  const weekRange = formatWeekRange(weekDays);
  const todayAppointments = filtered.filter((appointment) =>
    weekDays.some((day) => day.isToday && day.jalali === appointment.appointment_date)
  );
  const weekAppointments = filtered.filter((appointment) =>
    weekDays.some((day) => day.jalali === appointment.appointment_date)
  );

  const canBook =
    hasPerm('book_appointment') &&
    (role !== 'patient' ||
      (currentUser?.patients?.length ?? 0) > 0 ||
      Boolean(currentUser?.patient));

  const statusFilters: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'همه' },
    { value: 'scheduled', label: 'زمان‌بندی' },
    { value: 'confirmed', label: 'تأییدشده' },
    { value: 'in_progress', label: 'در حال درمان' },
    { value: 'completed', label: 'تکمیل‌شده' },
    { value: 'cancelled', label: 'لغوشده' },
  ];

  const resetFilters = () => {
    setStatusFilter('all');
    setSearchQuery('');
    setDoctorFilter('all');
  };

  return (
    <div className="d-page d-fade">
      <PageHeader
        title={role === 'patient' ? 'نوبت‌های من' : role === 'doctor' ? 'برنامه نوبت‌های من' : 'هر نوبت، در جای درست'}
        subtitle={
          role === 'patient'
            ? 'نوبت‌های ثبت‌شده روی حساب شما؛ زمان‌ها و وضعیت‌ها از سرور خوانده می‌شوند.'
            : 'نمای هفتگی و فهرست کامل نوبت‌ها با امکان مشاهده جزئیات، لغو یا تغییر زمان.'
        }
        action={
          canBook ? (
            <Button
              size="md"
              onClick={() => setBookingOpen(true)}
              icon={<Plus className="w-4 h-4" />}
            >
              رزرو نوبت جدید
            </Button>
          ) : undefined
        }
      />

      <div className="d-stat-band grid grid-cols-2 xl:grid-cols-4 mb-5">
        {[
          { label: 'نوبت‌های این هفته', value: weekAppointments.length },
          { label: 'نوبت‌های امروز', value: todayAppointments.length },
          {
            label: 'تکمیل‌شده',
            value: baseAppointments.filter((appointment) => appointment.status === 'completed').length,
          },
          {
            label: 'لغوشده',
            value: baseAppointments.filter((appointment) => appointment.status === 'cancelled').length,
          },
        ].map((item) => (
          <div key={item.label} className="d-stat">
            <div className="text-caption font-medium text-muted">{item.label}</div>
            <div className="d-stat-value">{toPersianDigits(item.value)}</div>
          </div>
        ))}
      </div>

      <div className="d-card p-4 sm:p-5 mb-5">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <Segmented
              options={[
                { value: 'week', label: 'نمای هفته' },
                { value: 'list', label: 'فهرست' },
              ]}
              value={viewMode}
              onChange={(value) => setViewMode(value as ViewMode)}
            />

            <div className="flex items-center gap-1 bg-surface border border-line rounded-[3px] p-1">
              <button
                type="button"
                onClick={() => setWeekOffset((offset) => offset - 1)}
                className="w-7 h-7 rounded-[3px] hover:bg-canvas text-muted flex items-center justify-center"
                aria-label="هفته قبل"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => setWeekOffset(0)}
                className="h-8 px-2.5 rounded-[3px] hover:bg-canvas text-caption font-semibold text-ink"
              >
                امروز
              </button>
              <button
                type="button"
                onClick={() => setWeekOffset((offset) => offset + 1)}
                className="w-7 h-7 rounded-[3px] hover:bg-canvas text-muted flex items-center justify-center"
                aria-label="هفته بعد"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
            <span className="text-caption text-muted">{weekRange}</span>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
            {role !== 'doctor' && role !== 'patient' && (
              <select
                className="d-select !h-9 !text-caption sm:w-40"
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
            <div className="d-search w-full sm:w-56">
              <Search className="w-4 h-4" />
              <input
                className="d-input !h-9 !text-caption"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="جستجو در نوبت‌ها..."
                aria-label="جستجوی نوبت"
              />
            </div>
          </div>
        </div>

        <div className="flex gap-1.5 overflow-x-auto no-scrollbar mt-3 pt-3 border-t border-line-soft">
          {statusFilters.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setStatusFilter(item.value)}
              className={`d-chip shrink-0 !h-8 !text-caption ${
                statusFilter === item.value ? 'active' : ''
              }`}
            >
              {item.label}
            </button>
          ))}
          {(statusFilter !== 'all' || searchQuery || doctorFilter !== 'all') && (
            <button
              type="button"
              onClick={resetFilters}
              className="text-caption text-primary hover:text-primary-deep font-semibold shrink-0 pr-2"
            >
              پاک کردن فیلترها
            </button>
          )}
        </div>
      </div>

      {viewMode === 'week' ? (
        filtered.length === 0 ? (
          <EmptyState
            icon={<CalendarDays className="w-5 h-5" />}
            title="نوبتی در این بازه یافت نشد"
            description="با تغییر هفته یا پاک کردن فیلترها دوباره بررسی کنید."
            actionLabel={canBook ? 'رزرو نوبت جدید' : undefined}
            onAction={() => setBookingOpen(true)}
          />
        ) : (
          <div className="d-card overflow-hidden">
            <div className="overflow-x-auto">
              <div className="min-w-[900px] grid grid-cols-7 divide-x divide-x-reverse divide-line-soft">
                {weekDays.map((day) => {
                  const dayAppointments = filtered.filter(
                    (appointment) => appointment.appointment_date === day.jalali
                  );
                  return (
                    <div
                      key={day.iso}
                      className={`min-h-[280px] ${day.isToday ? 'bg-surface-muted' : 'bg-surface'}`}
                    >
                      <div
                        className={`px-3 py-3 border-b border-line-soft text-center ${
                          day.isToday ? 'bg-primary-soft' : ''
                        }`}
                      >
                        <div
                          className={`text-caption ${
                            day.isToday ? 'text-primary font-bold' : 'text-faint'
                          }`}
                        >
                          {day.weekday}
                        </div>
                        <div
                          className={`text-[17px] font-extrabold mt-0.5 tabular-nums ${
                            day.isToday ? 'text-primary-deep' : 'text-ink'
                          }`}
                        >
                          {toPersianDigits(day.day)}
                        </div>
                        <div className="text-caption text-faint mt-0.5">{day.monthName}</div>
                      </div>
                      <div className="p-2 space-y-1.5">
                        {dayAppointments.length === 0 ? (
                          <div className="h-16 flex items-center justify-center text-caption text-line-strong">
                            نوبتی نیست
                          </div>
                        ) : (
                          dayAppointments.map((appointment) => (
                            <button
                              key={appointment.id}
                              type="button"
                              onClick={() => setSelected(appointment)}
                              className={`w-full text-right rounded-[3px] border p-2 transition-colors ${
                                appointment.status === 'cancelled'
                                  ? 'border-danger-line bg-danger-soft opacity-80'
                                  : appointment.status === 'completed'
                                  ? 'border-line bg-surface-muted'
                                  : 'border-primary-line bg-[#fbf8f2] hover:bg-[#f3ece2]'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="text-caption font-bold text-ink tabular-nums">
                                  {formatTimeFa(appointment.appointment_time)}
                                </span>
                                <span
                                  className={`w-1.5 h-1.5 rounded-full ${
                                    appointment.status === 'cancelled'
                                      ? 'bg-danger'
                                      : appointment.status === 'completed'
                                      ? 'bg-faint'
                                      : 'bg-primary'
                                  }`}
                                />
                              </div>
                              <div className="text-caption font-semibold text-ink mt-1 truncate">
                                {role === 'patient'
                                  ? appointment.service_name
                                  : appointment.patient_name}
                              </div>
                              <div className="text-caption text-muted mt-0.5 truncate">
                                {role === 'patient'
                                  ? appointment.doctor_name
                                  : appointment.service_name}
                              </div>
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<CalendarDays className="w-5 h-5" />}
          title="نوبتی با این مشخصات یافت نشد"
          description="می‌توانید فیلترها را پاک کنید یا نوبت جدیدی رزرو نمایید."
          actionLabel={canBook ? 'رزرو نوبت جدید' : undefined}
          onAction={() => setBookingOpen(true)}
        />
      ) : (
        <div className="d-table-card">
          <div className="overflow-x-auto">
            <table className="d-table">
              <thead>
                <tr>
                  <th>تاریخ</th>
                  <th>ساعت</th>
                  <th>{role === 'patient' ? 'پزشک' : 'بیمار'}</th>
                  <th>خدمت</th>
                  {role !== 'patient' && <th>پزشک</th>}
                  <th>وضعیت</th>
                  <th className="text-left">عملیات</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((appointment) => (
                  <tr key={appointment.id}>
                    <td className="whitespace-nowrap">
                      {formatToJalali(appointment.appointment_date)}
                    </td>
                    <td className="tabular-nums whitespace-nowrap">
                      {formatTimeFa(appointment.appointment_time)}
                    </td>
                    <td className="font-semibold whitespace-nowrap">
                      {role === 'patient'
                        ? appointment.doctor_name
                        : appointment.patient_name}
                    </td>
                    <td className="text-muted max-w-[180px] truncate">
                      {appointment.service_name}
                    </td>
                    {role !== 'patient' && (
                      <td className="text-muted whitespace-nowrap">
                        {appointment.doctor_name}
                      </td>
                    )}
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
        </div>
      )}

      <AppointmentBookingModal isOpen={bookingOpen} onClose={() => setBookingOpen(false)} />
      <AppointmentDetailsModal
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        appointment={selected}
      />
    </div>
  );
};
