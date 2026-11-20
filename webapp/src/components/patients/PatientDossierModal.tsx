import React, { useEffect, useMemo, useState } from 'react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { Patient } from '../../types';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { apiClient } from '../../api/client';
import { ClinicalRecordModal } from '../health/ClinicalRecordModal';
import { AppointmentStatusBadge, RecordStatusBadge } from '../common/Badge';
import { formatTimeFa, formatToJalali, toPersianDigits, todayJalaliString } from '../../utils/persianDate';
import { isUpcoming, sortAppointments } from '../../utils/analytics';
import {
  BadgeCheck,
  CalendarDays,
  CheckCircle2,
  Clock,
  FileText,
  HeartPulse,
  Phone,
  Stethoscope,
  User,
} from 'lucide-react';

interface PatientDossierModalProps {
  isOpen: boolean;
  onClose: () => void;
  patient: Patient | null;
  /** Admin actions wired by the host view (edit / link-to-account). */
  onEdit?: (patient: Patient) => void;
  onLink?: (patient: Patient) => void;
}

export const PatientDossierModal: React.FC<PatientDossierModalProps> = ({
  isOpen,
  onClose,
  patient,
  onEdit,
  onLink,
}) => {
  const { appointments, refreshAll } = useClinic();
  const { hasPerm, currentUser } = useAuth();
  const isAdmin = currentUser?.role === 'admin';
  const [nationalId, setNationalId] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState(false);
  const [clinicalOpen, setClinicalOpen] = useState(false);

  useEffect(() => {
    setNationalId('');
    setFormError(null);
    setFormSuccess(false);
    setSaving(false);
  }, [patient?.id]);

  const patientAppointments = useMemo(() => {
    if (!patient) return [];
    return sortAppointments(
      appointments.filter(
        (appointment) =>
          appointment.patient_id === patient.id ||
          appointment.patient_name === patient.full_name
      )
    ).reverse();
  }, [appointments, patient]);

  if (!patient) return null;

  const today = todayJalaliString();
  const completedCount = patientAppointments.filter(
    (appointment) => appointment.status === 'completed'
  ).length;
  const upcomingCount = patientAppointments.filter((appointment) =>
    isUpcoming(appointment, today)
  ).length;

  const submitNationalId = async (event: React.FormEvent) => {
    event.preventDefault();
    const digits = nationalId.trim().replace(/\D/g, '');
    if (digits.length !== 10) {
      setFormError('کد ملی باید دقیقاً ۱۰ رقم باشد.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await apiClient.updatePatient(patient.id, {
        full_name: patient.full_name,
        phone: patient.phone,
        national_id: digits,
      });
      await refreshAll();
      setFormSuccess(true);
      setNationalId('');
    } catch (err: any) {
      setFormError(err.message || 'تکمیل کد ملی ناکام ماند');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`پرونده ${patient.full_name}`}
      subtitle={`شناسه سرور ${toPersianDigits(patient.id)} · ${toPersianDigits(
        patientAppointments.length
      )} نوبت ثبت‌شده`}
      maxWidth="2xl"
    >
      <div className="space-y-4">
        {/* Identity card */}
        <div className="rounded-[16px] border border-line bg-surface-muted p-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-12 h-12 rounded-full bg-primary-soft border border-primary-line text-primary-deep text-[17px] font-extrabold flex items-center justify-center shrink-0">
                {patient.full_name.charAt(0)}
              </div>
              <div className="min-w-0">
                <div className="text-body font-bold text-ink truncate">
                  {patient.full_name}
                </div>
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <RecordStatusBadge status={patient.record_status} />
                  <span className="text-caption text-faint tabular-nums" dir="ltr">
                    {toPersianDigits(patient.phone)}
                  </span>
                </div>
              </div>
            </div>
            <div className="grid w-full grid-cols-3 gap-1.5 sm:w-auto sm:gap-2">
              <div className="text-center px-2 py-2 rounded-[10px] bg-surface border border-line sm:px-3">
                <div className="text-heading font-extrabold text-ink tabular-nums">
                  {toPersianDigits(patientAppointments.length)}
                </div>
                <div className="text-caption text-faint mt-0.5">کل نوبت</div>
              </div>
              <div className="text-center px-2 py-2 rounded-[10px] bg-surface border border-line sm:px-3">
                <div className="text-heading font-extrabold text-primary tabular-nums">
                  {toPersianDigits(upcomingCount)}
                </div>
                <div className="text-caption text-faint mt-0.5">پیش‌رو</div>
              </div>
              <div className="text-center px-2 py-2 rounded-[10px] bg-surface border border-line sm:px-3">
                <div className="text-heading font-extrabold text-muted tabular-nums">
                  {toPersianDigits(completedCount)}
                </div>
                <div className="text-caption text-faint mt-0.5">تکمیل</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-4 pt-4 border-t border-line-soft">
            <div className="flex items-center gap-2 text-caption text-muted">
              <Phone className="w-3.5 h-3.5 text-faint" />
              شماره تماس:
              <span className="font-semibold text-ink tabular-nums" dir="ltr">
                {toPersianDigits(patient.phone)}
              </span>
            </div>
            <div className="flex items-center gap-2 text-caption text-muted">
              <User className="w-3.5 h-3.5 text-faint" />
              کد ملی:
              <span className="font-semibold text-ink tabular-nums">
                {patient.national_id ? toPersianDigits(patient.national_id) : 'ثبت نشده'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-caption text-muted">
              <BadgeCheck className="w-3.5 h-3.5 text-faint" />
              حساب کاربری:
              <span className={`font-semibold ${patient.user_id ? 'text-primary-deep' : 'text-ink'}`}>
                {patient.user_id
                  ? `متصل${patient.is_account_holder ? ' (پروندهٔ اصلی)' : ''}`
                  : 'بدون حساب (بدون ورود به اپ)'}
              </span>
            </div>
          </div>
        </div>

        {/* Completion form */}
        {patient.record_status === 'incomplete' && hasPerm('manage_patients') && !formSuccess && (
          <form onSubmit={submitNationalId} className="d-soft-warn p-4 space-y-3">
            <div className="flex items-center gap-2 text-small font-bold text-warn">
              <BadgeCheck className="w-4 h-4" />
              تکمیل کد ملی این پرونده
            </div>
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
              <input
                value={nationalId}
                onChange={(event) => setNationalId(event.target.value)}
                placeholder="کد ملی ۱۰ رقمی"
                className="d-input tabular-nums flex-1"
                dir="ltr"
                inputMode="numeric"
              />
              <Button type="submit" size="sm" isLoading={saving}>
                ثبت کد ملی
              </Button>
            </div>
            {formError && (
              <div className="d-soft-danger px-3 py-2 text-caption text-danger">{formError}</div>
            )}
            <p className="text-caption text-warn leading-5">
              پس از ثبت، سرور وضعیت پرونده را به «کامل» تغییر می‌دهد. اعداد فارسی نیز پذیرفته می‌شوند.
            </p>
          </form>
        )}

        {formSuccess && (
          <div className="d-soft-teal px-3.5 py-2.5 text-caption text-primary-deep flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" />
            کد ملی ثبت شد و پرونده کامل گردید. فهرست بیماران تازه‌سازی شد.
          </div>
        )}

        {/* Clinical record entry point */}
        <button
          type="button"
          onClick={() => setClinicalOpen(true)}
          className="w-full rounded-[14px] border border-primary-line bg-[#FBFDFD] p-4 flex items-center justify-between gap-3 hover:bg-[#F3FAF9] transition-colors text-right"
        >
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-10 h-10 rounded-[12px] bg-primary-soft border border-primary-line text-primary-deep flex items-center justify-center shrink-0">
              <HeartPulse className="w-5 h-5" />
            </span>
            <div className="min-w-0">
              <div className="text-small font-bold text-ink">
                پرونده بالینی و نقشه دندان‌ها
              </div>
              <div className="text-caption text-muted mt-0.5 leading-5">
                {hasPerm('manage_clinical_records')
                  ? 'مشاهده و ثبت یادداشت درمانی، حساسیت و وضعیت هر دندان'
                  : 'مشاهده یادداشت‌های درمانی و وضعیت دندان‌ها'}
              </div>
            </div>
          </div>
          <span className="text-caption font-bold text-primary shrink-0">باز کردن ←</span>
        </button>

        {/* Appointment history */}
        <div>
          <div className="flex items-center justify-between mb-2.5">
            <div className="text-small font-bold text-ink flex items-center gap-1.5">
              <FileText className="w-4 h-4 text-primary" />
              سوابق نوبت‌ها
            </div>
            <span className="text-caption text-faint">جدیدترین در بالا</span>
          </div>

          {patientAppointments.length === 0 ? (
            <div className="d-empty py-6">
              <div className="d-empty-icon">
                <CalendarDays className="w-5 h-5" />
              </div>
              <p className="text-caption text-muted">
                هنوز نوبتی برای این بیمار ثبت نشده است.
              </p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[300px] overflow-y-auto pl-1">
              {patientAppointments.map((appointment) => (
                <div
                  key={appointment.id}
                  className="flex flex-col gap-2 rounded-[12px] border border-line p-3.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-small font-bold text-ink">
                      {appointment.service_name}
                    </div>
                    <div className="text-caption text-muted mt-1 flex items-center gap-2 flex-wrap">
                      <Stethoscope className="w-3 h-3" />
                      <span>{appointment.doctor_name}</span>
                      <span className="text-line-strong">•</span>
                      <span>{formatToJalali(appointment.appointment_date, true)}</span>
                      <span className="text-line-strong">•</span>
                      <span className="tabular-nums">{formatTimeFa(appointment.appointment_time)}</span>
                    </div>
                    {appointment.reason && (
                      <div className="text-caption text-faint mt-1.5 leading-5">
                        {appointment.reason}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 self-start">
                    <AppointmentStatusBadge status={appointment.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-col-reverse gap-3 border-t border-line-soft pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-1.5 text-caption leading-5 text-faint">
            <Clock className="w-3 h-3 shrink-0 mt-0.5" />
            اطلاعات این پرونده از پاسخ واقعی سرور خوانده شده است.
          </div>
          <div className="flex items-center gap-2">
            {onEdit && hasPerm('manage_patients') && (
              <Button size="sm" variant="outline" onClick={() => onEdit(patient)}>
                ویرایش اطلاعات
              </Button>
            )}
            {onLink && isAdmin && !patient.user_id && (
              <Button size="sm" variant="outline" onClick={() => onLink(patient)}>
                اتصال به حساب
              </Button>
            )}
            <Button size="sm" onClick={onClose} className="w-full sm:w-auto">
              بستن پرونده
            </Button>
          </div>
        </div>
      </div>

      <ClinicalRecordModal
        isOpen={clinicalOpen}
        onClose={() => {
          setClinicalOpen(false);
        }}
        patientId={patient.id}
        patientName={patient.full_name}
        canWrite={hasPerm('manage_clinical_records')}
      />
    </Modal>
  );
};
