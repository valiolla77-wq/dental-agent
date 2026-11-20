import React, { useMemo, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useClinic } from '../../context/ClinicContext';
import { Appointment } from '../../types';
import { formatTimeFa, formatToJalali, toPersianDigits, todayJalaliString } from '../../utils/persianDate';
import { sortAppointments } from '../../utils/analytics';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/EmptyState';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { ClinicalRecordModal } from '../health/ClinicalRecordModal';
import { InfoBanner, PageHeader, SectionCard, StatCard } from '../common/ui';
import {
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  Clock,
  HeartPulse,
  Search,
  Stethoscope,
  Users,
} from 'lucide-react';

interface PatientSummary {
  key: string;
  name: string;
  total: number;
  completed: number;
  last?: Appointment;
  next?: Appointment;
  services: string[];
}

/**
 * Doctor's authorised patients, derived from the appointments the server
 * already returned for this physician. Contact/national-id fields are not
 * fetched here; the panel is explicit about that boundary.
 */
export const DoctorPatientsView: React.FC = () => {
  const { currentUser, hasPerm } = useAuth();
  const { appointments } = useClinic();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<PatientSummary | null>(null);
  const [clinicalOpen, setClinicalOpen] = useState(false);

  const today = todayJalaliString();
  const doctorId = currentUser?.doctor?.id ?? null;

  const rows = useMemo(
    () =>
      appointments.filter(
        (appointment) =>
          (doctorId !== null && appointment.doctor_id === doctorId) ||
          appointment.doctor_name === currentUser?.full_name
      ),
    [appointments, doctorId, currentUser?.full_name]
  );

  const patients = useMemo(() => {
    const map = new Map<string, PatientSummary>();
    for (const appointment of sortAppointments(rows)) {
      const key =
        appointment.patient_id != null
          ? `id-${appointment.patient_id}`
          : `name-${appointment.patient_name}`;
      const current =
        map.get(key) ||
        {
          key,
          name: appointment.patient_name,
          total: 0,
          completed: 0,
          services: [],
        };
      current.total += 1;
      if (appointment.status === 'completed') current.completed += 1;
      if (!current.services.includes(appointment.service_name)) {
        current.services.push(appointment.service_name);
      }
      if (appointment.appointment_date <= today && appointment.status !== 'cancelled') {
        if (
          !current.last ||
          appointment.appointment_date > current.last.appointment_date
        ) {
          current.last = appointment;
        }
      }
      if (appointment.appointment_date >= today && appointment.status !== 'cancelled') {
        if (!current.next || appointment.appointment_date < current.next.appointment_date) {
          current.next = appointment;
        }
      }
      map.set(key, current);
    }
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [rows, today]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return patients;
    return patients.filter(
      (patient) =>
        patient.name.toLowerCase().includes(query) ||
        patient.services.some((service) => service.toLowerCase().includes(query))
    );
  }, [patients, search]);

  const todayCount = rows.filter(
    (appointment) => appointment.appointment_date === today && appointment.status !== 'cancelled'
  ).length;
  const upcomingCount = rows.filter(
    (appointment) => appointment.appointment_date >= today && appointment.status !== 'cancelled'
  ).length;

  if (doctorId === null) {
    return (
      <div className="d-page">
        <InfoBanner tone="warning" title="حساب پزشک به پرونده متصل نیست">
          تا زمان اتصال حساب به پرونده پزشک، فهرست بیماران مجاز در دسترس نیست. با مدیر کلینیک
          هماهنگ کنید.
        </InfoBanner>
      </div>
    );
  }

  const selectedRows = selected
    ? sortAppointments(
        rows.filter((appointment) =>
          selected.key.startsWith('id-')
            ? `id-${appointment.patient_id}` === selected.key
            : `name-${appointment.patient_name}` === selected.key
        )
      ).reverse()
    : [];

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="بیماران مجاز"
        subtitle="مراجعانی که برای شما نوبت ثبت شده دارند؛ فهرست از نوبت‌های واقعی سرور ساخته می‌شود."
      />

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4 mb-5">
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="بیماران مجاز"
          value={toPersianDigits(patients.length)}
          hint="بر اساس نوبت‌های ثبت‌شده"
        />
        <StatCard
          icon={<CalendarDays className="w-[18px] h-[18px]" />}
          label="مراجعان امروز"
          value={toPersianDigits(todayCount)}
          hint="نوبت‌های غیرلغوشده امروز"
        />
        <StatCard
          icon={<Clock className="w-[18px] h-[18px]" />}
          label="نوبت‌های پیش‌رو"
          value={toPersianDigits(upcomingCount)}
          hint="از امروز به بعد"
          tone="soft"
        />
        <StatCard
          icon={<CheckCircle2 className="w-[18px] h-[18px]" />}
          label="ویزیت‌های تکمیل‌شده"
          value={toPersianDigits(rows.filter((appointment) => appointment.status === 'completed').length)}
          hint="در سوابق این پزشک"
        />
      </div>

      <SectionCard
        title="فهرست بیماران"
        subtitle="جستجو بر اساس نام بیمار یا نام خدمت"
        action={
          <div className="d-search w-60 hidden sm:block">
            <Search className="w-4 h-4" />
            <input
              className="d-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="جستجوی بیمار..."
              aria-label="جستجوی بیمار"
            />
          </div>
        }
        noPadding
      >
        {filtered.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={<Users className="w-5 h-5" />}
              title="بیماری یافت نشد"
              description={
                patients.length === 0
                  ? 'برای شما هنوز نوبتی ثبت نشده است؛ پس از ثبت نوبت، بیماران در این فهرست نمایش داده می‌شوند.'
                  : 'عبارت جستجو با هیچ بیماری مطابقت ندارد.'
              }
              actionLabel={search ? 'پاک کردن جستجو' : undefined}
              onAction={search ? () => setSearch('') : undefined}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="d-table">
              <thead>
                <tr>
                  <th>بیمار</th>
                  <th>تعداد نوبت</th>
                  <th>خدمات</th>
                  <th>آخرین مراجعه</th>
                  <th>نوبت بعدی</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((patient) => (
                  <tr key={patient.key}>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <span className="w-8 h-8 rounded-full bg-primary-soft border border-primary-line text-primary-deep text-small font-bold flex items-center justify-center shrink-0">
                          {patient.name.charAt(0)}
                        </span>
                        <div>
                          <div className="font-semibold text-ink">{patient.name}</div>
                          <div className="text-caption text-faint mt-0.5">
                            {toPersianDigits(patient.completed)} ویزیت تکمیل‌شده
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="tabular-nums">{toPersianDigits(patient.total)}</td>
                    <td>
                      <div className="flex flex-wrap gap-1 max-w-[220px]">
                        {patient.services.slice(0, 2).map((service) => (
                          <Badge key={service} variant="default">
                            {service}
                          </Badge>
                        ))}
                        {patient.services.length > 2 && (
                          <Badge variant="neutral">+{toPersianDigits(patient.services.length - 2)}</Badge>
                        )}
                      </div>
                    </td>
                    <td className="text-muted">
                      {patient.last ? formatToJalali(patient.last.appointment_date) : '—'}
                    </td>
                    <td>
                      {patient.next ? (
                        <span className="text-primary-deep font-semibold">
                          {formatToJalali(patient.next.appointment_date)} ·{' '}
                          {formatTimeFa(patient.next.appointment_time)}
                        </span>
                      ) : (
                        <span className="text-faint">ثبت نشده</span>
                      )}
                    </td>
                    <td className="text-left">
                      <button
                        type="button"
                        className="d-link"
                        onClick={() => setSelected(patient)}
                      >
                        سوابق
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

      <div className="mt-5">
        <InfoBanner tone="info" icon={<Stethoscope className="w-4 h-4" />}>
          این نما فقط نوبت‌ها و خدمات ثبت‌شده برای شما را نشان می‌دهد. شماره تماس و کد ملی در این
          فهرست از سرور بارگذاری نمی‌شود؛ برای جزئیات هویتی از مسیر مجاز پرونده بیمار استفاده کنید.
        </InfoBanner>
      </div>

      <Modal
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected ? `سوابق ${selected.name}` : 'سوابق بیمار'}
        subtitle={selected ? `${toPersianDigits(selected.total)} نوبت ثبت‌شده برای شما` : undefined}
        maxWidth="2xl"
      >
        {selected && selected.key.startsWith('id-') && (
          <Button
            size="sm"
            variant="outline"
            className="mb-3"
            onClick={() => setClinicalOpen(true)}
            icon={<HeartPulse className="w-3.5 h-3.5" />}
          >
            پرونده بالینی و نقشه دندان‌ها
          </Button>
        )}
        {selectedRows.length === 0 ? (
          <div className="d-empty">
            <div className="d-empty-icon">
              <CalendarDays className="w-5 h-5" />
            </div>
            <p className="text-small text-muted">سابقه‌ای برای نمایش وجود ندارد.</p>
          </div>
        ) : (
          <div className="space-y-2.5">
            {selectedRows.map((appointment) => (
              <div
                key={appointment.id}
                className="rounded-[12px] border border-line p-3.5 flex items-start justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="text-small font-bold text-ink">
                    {appointment.service_name}
                  </div>
                  <div className="text-caption text-muted mt-1 flex items-center gap-2 flex-wrap">
                    <span>{formatToJalali(appointment.appointment_date, true)}</span>
                    <span className="text-line-strong">•</span>
                    <span className="tabular-nums">ساعت {formatTimeFa(appointment.appointment_time)}</span>
                  </div>
                  {appointment.reason && (
                    <div className="text-caption text-faint mt-1.5 leading-5">
                      {appointment.reason}
                    </div>
                  )}
                </div>
                <Badge
                  variant={
                    appointment.status === 'completed'
                      ? 'success'
                      : appointment.status === 'cancelled'
                      ? 'danger'
                      : 'info'
                  }
                  dot
                >
                  {appointment.status === 'completed'
                    ? 'تکمیل‌شده'
                    : appointment.status === 'cancelled'
                    ? 'لغوشده'
                    : 'فعال'}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {selected && selected.key.startsWith('id-') && (
        <ClinicalRecordModal
          isOpen={clinicalOpen}
          onClose={() => setClinicalOpen(false)}
          patientId={Number(selected.key.slice(3))}
          patientName={selected.name}
          canWrite={hasPerm('manage_clinical_records')}
        />
      )}
    </div>
  );
};
