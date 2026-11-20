import React, { useMemo, useState } from 'react';
import { CalendarCheck, Check, RefreshCw, Search, Stethoscope, UserRound } from 'lucide-react';
import { DentalService, Doctor, Patient } from '../../../types';
import { DayMeta } from '../../../utils/analytics';
import {
  DayAvailability,
  EarliestSlot,
  groupSlotsByDayPart,
  initialsOf,
  matchesQuery,
} from '../../../utils/bookingSlots';
import { formatTimeFa, toPersianDigits } from '../../../utils/persianDate';
import { FOCUS_RING } from './FlowSection';

const tileClass = (selected: boolean) =>
  `relative w-full rounded-[14px] border p-3.5 text-start transition-colors ${FOCUS_RING} ${
    selected
      ? 'border-primary bg-primary-soft'
      : 'border-line bg-surface hover:border-primary-line'
  }`;

const CheckMark: React.FC = () => (
  <span className="absolute end-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-on-accent">
    <Check className="h-3 w-3" aria-hidden="true" />
  </span>
);

const Avatar: React.FC<{ text: React.ReactNode; selected: boolean }> = ({ text, selected }) => (
  <span
    aria-hidden="true"
    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-body font-bold ${
      selected ? 'bg-surface text-primary' : 'bg-line-soft text-ink-soft'
    }`}
  >
    {text}
  </span>
);

const EmptyNote: React.FC<{ icon: React.ReactNode; children: React.ReactNode }> = ({
  icon,
  children,
}) => (
  <div className="d-empty !py-6">
    <div className="d-empty-icon">{icon}</div>
    <p className="text-small leading-6 text-muted">{children}</p>
  </div>
);

/* ------------------------------------------------------------------ patient */

const MAX_PATIENT_RESULTS = 6;
const PATIENT_LIST_LIMIT = 5;

export const PatientPicker: React.FC<{
  patients: Patient[];
  value: string;
  onChange: (id: string) => void;
  isPatientRole: boolean;
}> = ({ patients, value, onChange, isPatientRole }) => {
  const [query, setQuery] = useState('');
  const searchable = patients.length > PATIENT_LIST_LIMIT;
  const visible = useMemo(() => {
    const matched = searchable
      ? patients.filter((p) => matchesQuery([p.full_name, p.phone, p.national_id], query))
      : patients;
    return matched;
  }, [patients, query, searchable]);
  const shown = searchable ? visible.slice(0, MAX_PATIENT_RESULTS) : visible;

  if (patients.length === 0) {
    return (
      <EmptyNote icon={<UserRound className="h-5 w-5" />}>
        {isPatientRole
          ? 'هنوز پرونده‌ای زیر این حساب ثبت نشده است. ابتدا از دستیار، پرونده بیمار را ثبت کنید.'
          : 'هنوز پرونده‌ای ثبت نشده است. ابتدا از بخش پرونده‌ها یک بیمار ایجاد کنید.'}
      </EmptyNote>
    );
  }

  return (
    <div className="space-y-3">
      {searchable && (
        <label className="d-search block">
          <span className="sr-only">جستجوی بیمار</span>
          <Search aria-hidden="true" className="h-4 w-4" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="جستجوی نام، موبایل یا کد ملی"
            className="d-input"
          />
        </label>
      )}
      <div role="group" aria-label="بیمار" className="grid gap-2.5 sm:grid-cols-2">
        {shown.map((patient) => {
          const selected = value === String(patient.id);
          return (
            <button
              key={patient.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(String(patient.id))}
              className={tileClass(selected)}
            >
              {selected && <CheckMark />}
              <span className="flex items-center gap-3">
                <Avatar text={initialsOf(patient.full_name)} selected={selected} />
                <span className="min-w-0">
                  <span className="block truncate text-body font-bold text-ink">
                    {patient.full_name}
                    {patient.is_account_holder && (
                      <span className="ms-1.5 text-small font-semibold text-primary">خودم</span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-small tabular-nums text-muted">
                    {toPersianDigits(patient.phone)}
                  </span>
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {searchable && visible.length === 0 && (
        <p className="text-small text-muted">
          بیماری با این مشخصات پیدا نشد. نام یا شمارهٔ دقیق‌تری وارد کنید.
        </p>
      )}
      {searchable && visible.length > MAX_PATIENT_RESULTS && (
        <p className="text-small text-muted">
          {toPersianDigits(visible.length - MAX_PATIENT_RESULTS)} نتیجهٔ دیگر هم هست؛ عبارت
          دقیق‌تری بنویسید.
        </p>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ service */

export const ServicePicker: React.FC<{
  services: DentalService[];
  value: string;
  onChange: (id: string) => void;
}> = ({ services, value, onChange }) => {
  if (services.length === 0) {
    return (
      <EmptyNote icon={<Stethoscope className="h-5 w-5" />}>خدمت فعالی ثبت نشده است.</EmptyNote>
    );
  }
  return (
    <div role="group" aria-label="خدمت" className="grid gap-2.5 sm:grid-cols-2">
      {services.map((service) => {
        const selected = value === String(service.id);
        return (
          <button
            key={service.id}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(String(service.id))}
            className={tileClass(selected)}
          >
            {selected && <CheckMark />}
            <span className="block pe-7 text-body font-bold text-ink">{service.name}</span>
            {service.description && (
              <span className="mt-1 block line-clamp-2 text-small leading-5 text-muted">
                {service.description}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};

/* ------------------------------------------------------------------- doctor */

export const DoctorPicker: React.FC<{
  doctors: Doctor[];
  value: string;
  onChange: (id: string) => void;
}> = ({ doctors, value, onChange }) => {
  if (doctors.length === 0) {
    return (
      <EmptyNote icon={<Stethoscope className="h-5 w-5" />}>پزشک فعالی ثبت نشده است.</EmptyNote>
    );
  }
  return (
    <div role="group" aria-label="پزشک" className="grid gap-2.5 sm:grid-cols-2">
      {doctors.map((doctor) => {
        const selected = value === String(doctor.id);
        return (
          <button
            key={doctor.id}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(String(doctor.id))}
            className={tileClass(selected)}
          >
            {selected && <CheckMark />}
            <span className="flex items-center gap-3">
              <Avatar text={initialsOf(doctor.full_name)} selected={selected} />
              <span className="min-w-0 pe-6">
                <span className="block truncate text-body font-bold text-ink">
                  {doctor.full_name}
                </span>
                <span className="mt-0.5 block truncate text-small text-muted">
                  {doctor.specialty}
                </span>
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
};

/* ---------------------------------------------------------------- when (day + time) */

const dayName = (day: DayMeta, index: number) =>
  day.isToday ? 'امروز' : index === 1 && !day.isPast ? 'فردا' : day.weekday;

export const WhenPicker: React.FC<{
  days: DayMeta[];
  dayKey: string;
  startTime: string;
  availability: Record<string, DayAvailability>;
  earliest: EarliestSlot | 'pending' | null;
  onPickDay: (day: DayMeta) => void;
  onPickTime: (slot: string) => void;
  onPickEarliest: (target: EarliestSlot) => void;
  onRefresh: (day: DayMeta) => void;
}> = ({
  days,
  dayKey,
  startTime,
  availability,
  earliest,
  onPickDay,
  onPickTime,
  onPickEarliest,
  onRefresh,
}) => {
  const selectedDay = days.find((day) => day.jalali === dayKey) || null;
  const selectedAvailability = selectedDay ? availability[selectedDay.jalali] : undefined;
  const earliestDay =
    earliest && earliest !== 'pending'
      ? days.find((day) => day.jalali === earliest.dayKey) || null
      : null;
  const earliestChosen =
    !!earliest &&
    earliest !== 'pending' &&
    dayKey === earliest.dayKey &&
    startTime === earliest.slot;

  return (
    <div className="space-y-4">
      {/* Shortcut: one tap sets both the day and the time. */}
      {earliest === 'pending' && <div className="d-skeleton h-[52px] rounded-[14px]" />}
      {earliest && earliest !== 'pending' && earliestDay && (
        <button
          type="button"
          onClick={() => onPickEarliest(earliest)}
          className={`flex w-full items-center gap-3 rounded-[14px] border border-primary-line bg-primary-soft px-3.5 py-3 text-start transition-colors hover:bg-primary-hover ${FOCUS_RING}`}
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface text-primary">
            {earliestChosen ? (
              <Check className="h-4 w-4" aria-hidden="true" />
            ) : (
              <CalendarCheck className="h-4 w-4" aria-hidden="true" />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-small text-primary-deep">نزدیک‌ترین زمان خالی</span>
            <span className="block truncate text-lead font-bold text-ink">
              {earliestDay.label}، ساعت {formatTimeFa(earliest.slot)}
            </span>
          </span>
          <span className="shrink-0 text-small font-semibold text-primary">
            {earliestChosen ? 'انتخاب شد' : 'انتخاب'}
          </span>
        </button>
      )}
      {earliest === null && (
        <div className="d-soft-warn px-3.5 py-3 text-small leading-6 text-warn">
          در {toPersianDigits(days.length)} روز آینده برای این پزشک زمان خالی پیدا نشد. پزشک دیگری
          را امتحان کنید.
        </div>
      )}

      <div
        role="group"
        aria-label="روز نوبت"
        className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 pb-1"
      >
        {days.map((day, index) => {
          const entry = availability[day.jalali];
          const active = dayKey === day.jalali;
          const full = entry?.status === 'ready' && entry.slots.length === 0;
          const failed = entry?.status === 'error';
          return (
            <button
              key={day.jalali}
              type="button"
              aria-pressed={active}
              disabled={full}
              onClick={() => onPickDay(day)}
              className={`w-[68px] shrink-0 rounded-[14px] border px-1 py-2.5 text-center transition-colors disabled:cursor-not-allowed ${FOCUS_RING} ${
                active
                  ? 'border-primary bg-primary text-on-accent'
                  : full
                  ? 'border-line-soft bg-surface-muted text-faint'
                  : 'border-line bg-surface text-ink hover:border-primary-line'
              }`}
            >
              <span className={`block text-small ${active ? 'text-on-accent/80' : 'text-muted'}`}>
                {dayName(day, index)}
              </span>
              <span className="mt-0.5 block text-[18px] font-extrabold leading-6 tabular-nums">
                {toPersianDigits(day.day)}
              </span>
              <span className={`block text-small ${active ? 'text-on-accent/80' : 'text-faint'}`}>
                {day.monthName}
              </span>
              <span className="mt-1.5 block h-5 text-caption font-semibold">
                {!entry || entry.status === 'loading' ? (
                  <span className={`d-skeleton mx-auto block h-2.5 w-8 ${active ? 'opacity-40' : ''}`} />
                ) : failed ? (
                  <span className={active ? 'text-on-accent' : 'text-danger'}>خطا</span>
                ) : full ? (
                  <span>پر</span>
                ) : (
                  <span className={active ? 'text-on-accent' : 'text-primary'}>
                    {toPersianDigits(entry.slots.length)} زمان
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      {!selectedDay ? (
        <p className="text-small leading-6 text-muted">
          روزی را انتخاب کنید تا ساعت‌های خالی‌اش دیده شود.
        </p>
      ) : (
        <div>
          <div className="mb-2.5 flex items-center justify-between">
            <span className="text-small font-semibold text-ink">
              ساعت‌های خالی {selectedDay.label}
            </span>
            <button
              type="button"
              onClick={() => onRefresh(selectedDay)}
              disabled={selectedAvailability?.status === 'loading'}
              className={`inline-flex items-center gap-1 rounded-[8px] px-1.5 py-1 text-small text-primary hover:text-primary-deep disabled:opacity-50 ${FOCUS_RING}`}
            >
              <RefreshCw
                aria-hidden="true"
                className={`h-3 w-3 ${selectedAvailability?.status === 'loading' ? 'animate-spin' : ''}`}
              />
              به‌روزرسانی
            </button>
          </div>

          {!selectedAvailability || selectedAvailability.status === 'loading' ? (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {[0, 1, 2, 3, 4].map((item) => (
                <div key={item} className="d-skeleton h-10 rounded-[10px]" />
              ))}
            </div>
          ) : selectedAvailability.status === 'error' ? (
            <div role="alert" className="d-soft-danger px-3.5 py-3 text-small leading-6 text-danger">
              {selectedAvailability.message}
            </div>
          ) : selectedAvailability.slots.length === 0 ? (
            <p className="text-small leading-6 text-muted">
              این روز زمان خالی ندارد. روز دیگری را انتخاب کنید.
            </p>
          ) : (
            <div className="space-y-3">
              {groupSlotsByDayPart(selectedAvailability.slots).map((group) => (
                <div key={group.part}>
                  <div className="mb-1.5 text-small text-muted">{group.label}</div>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                    {group.slots.map((slot) => (
                      <button
                        key={slot}
                        type="button"
                        aria-pressed={startTime === slot}
                        onClick={() => onPickTime(slot)}
                        className={`h-10 rounded-[10px] border text-body font-semibold tabular-nums transition-colors ${FOCUS_RING} ${
                          startTime === slot
                            ? 'border-primary bg-primary text-on-accent'
                            : 'border-line bg-surface text-ink hover:border-primary-line'
                        }`}
                      >
                        {formatTimeFa(slot)}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
