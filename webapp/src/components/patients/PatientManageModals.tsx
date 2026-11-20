/**
 * Patient-record management dialogs for the staff back-office:
 *  - edit demographics (name / phone / national id)
 *  - connect the record to an existing patient account (admin)
 *  - delete the record with explicit confirmation (admin)
 *
 * Patterns follow the same SaaS admin conventions used across the app:
 * typed confirmation for destructive actions and inline validation.
 */

import React, { useEffect, useState } from 'react';
import { AlertCircle, Link2, ShieldCheck } from 'lucide-react';
import { Patient } from '../../types';
import { apiClient } from '../../api/client';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { InfoBanner } from '../common/ui';

interface BaseProps {
  patient: Patient;
  onClose: () => void;
  onDone: (message: string) => void;
}

/* ------------------------------------------------------- edit patient */

export const EditPatientModal: React.FC<BaseProps> = ({ patient, onClose, onDone }) => {
  const [fullName, setFullName] = useState(patient.full_name);
  const [phone, setPhone] = useState(patient.phone);
  const [nationalId, setNationalId] = useState(patient.national_id || '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const safePhone = phone.replace(/\D/g, '');
    const digits = nationalId.trim().replace(/\D/g, '');
    if (!fullName.trim() || safePhone.length < 8) {
      setError('نام و شماره تلفن معتبر الزامی است.');
      return;
    }
    if (digits && digits.length !== 10) {
      setError('کد ملی باید دقیقاً ۱۰ رقم باشد یا خالی بماند.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.updatePatient(patient.id, {
        full_name: fullName.trim(),
        phone: safePhone,
        national_id: digits || null,
      });
      onDone(`اطلاعات «${fullName.trim()}» به‌روزرسانی شد.`);
    } catch (err: any) {
      setError(err.message || 'ذخیرهٔ تغییرات ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`ویرایش پرونده ${patient.full_name}`}
      subtitle="شماره تلفن پرونده در کل کلینیک یکتاست و برای نوبت‌دهی و حساب کاربری به‌کار می‌رود."
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <div>
          <label className="d-label" htmlFor="edit-name">نام و نام خانوادگی</label>
          <input
            id="edit-name"
            className="d-input"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="edit-phone">شماره تلفن همراه</label>
          <input
            id="edit-phone"
            className="d-input tabular-nums"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            dir="ltr"
            inputMode="tel"
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="edit-national-id">
            کد ملی {patient.national_id ? '' : '(در صورت تکمیل)'}
          </label>
          <input
            id="edit-national-id"
            className="d-input tabular-nums"
            value={nationalId}
            onChange={(e) => setNationalId(e.target.value)}
            placeholder="۱۰ رقم"
            dir="ltr"
            inputMode="numeric"
            maxLength={10}
          />
          <p className="text-caption text-faint mt-1.5 leading-5">
            کد ملی خالی برای پرونده‌های قدیمی مجاز است؛ پس از ثبت، پرونده «کامل» می‌شود.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          <Button type="submit" isLoading={saving}>ذخیرهٔ تغییرات</Button>
        </div>
      </form>
    </Modal>
  );
};

/* -------------------------------------------------- link patient account */

export const LinkPatientAccountModal: React.FC<BaseProps> = ({ patient, onClose, onDone }) => {
  const [phone, setPhone] = useState(patient.phone);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const safePhone = phone.replace(/\D/g, '');
    if (!safePhone) {
      setError('شماره تلفن حساب بیمار را وارد کنید.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.linkPatientUser(patient.id, safePhone);
      onDone(`پروندهٔ «${patient.full_name}» به حساب با شماره ${safePhone} متصل شد.`);
    } catch (err: any) {
      setError(
        err.message ||
          'اتصال ناکام ماند؛ حساب بیمار با این شماره باید از قبل موجود و فعال باشد.'
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`اتصال پرونده به حساب کاربری — ${patient.full_name}`}
      subtitle="بیمار پس از اتصال، این پرونده و نوبت‌هایش را در درگاه بیماران می‌بیند."
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <InfoBanner tone="info" icon={<ShieldCheck className="w-4 h-4" />}>
          شماره تلفن باید با حساب بیمار (نقش بیمار) یکی باشد. هر حساب یک «پروندهٔ
          اصلی» دارد و سایر پرونده‌های متصل‌شده به‌عنوان اعضای خانواده دیده می‌شوند.
        </InfoBanner>

        <div>
          <label className="d-label" htmlFor="link-account-phone">شماره تلفن حساب بیمار</label>
          <input
            id="link-account-phone"
            className="d-input tabular-nums"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
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

/* -------------------------------------------------------- delete patient */

export const DeletePatientModal: React.FC<BaseProps> = ({ patient, onClose, onDone }) => {
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiClient.deletePatient(patient.id);
      onDone(`پروندهٔ «${patient.full_name}» برای همیشه حذف شد.`);
    } catch (err: any) {
      setError(err.message || 'حذف پرونده ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`حذف پروندهٔ ${patient.full_name}`}
      subtitle="این عملیات بازگشت‌پذیر نیست و در گزارش فعالیت ثبت می‌شود."
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <ul className="text-caption text-muted leading-6 list-disc pr-5">
          <li>نوبت‌های گذشته و لغوشدهٔ این پرونده همراه پرونده حذف می‌شوند.</li>
          <li>اگر پرونده به حساب بیماری متصل است، اتصال جدا می‌شود.</li>
          <li>اگر بیمار نوبت فعال (پیش‌رو) دارد، ابتدا باید نوبت‌ها لغو شوند.</li>
        </ul>

        <div>
          <label className="d-label" htmlFor="delete-patient-confirm">
            برای تأیید، کلمهٔ «حذف» را بنویسید
          </label>
          <input
            id="delete-patient-confirm"
            className="d-input"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            placeholder="حذف"
          />
        </div>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          <Button
            type="submit"
            variant="danger"
            isLoading={saving}
            disabled={confirmation !== 'حذف'}
          >
            حذف قطعی پرونده
          </Button>
        </div>
      </form>
    </Modal>
  );
};
