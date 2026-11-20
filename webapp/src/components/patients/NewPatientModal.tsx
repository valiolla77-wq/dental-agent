import React, { useEffect, useState } from 'react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { useClinic } from '../../context/ClinicContext';
import { toLatinDigits } from '../../utils/persianDate';
import { AlertCircle, UserPlus } from 'lucide-react';

interface NewPatientModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const NewPatientModal: React.FC<NewPatientModalProps> = ({ isOpen, onClose }) => {
  const { createPatient } = useClinic();
  const [fullName, setFullName] = useState('');
  const [nationalId, setNationalId] = useState('');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setFullName('');
    setNationalId('');
    setPhone('');
    setError(null);
    setSubmitting(false);
  }, [isOpen]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    const normalizedNationalId = toLatinDigits(nationalId).replace(/\D/g, '');
    const normalizedPhone = toLatinDigits(phone).replace(/\D/g, '');

    if (fullName.trim().length < 3) {
      setError('نام و نام خانوادگی را کامل وارد کنید.');
      return;
    }
    if (normalizedNationalId.length !== 10) {
      setError('کد ملی باید دقیقاً ۱۰ رقم باشد.');
      return;
    }
    if (normalizedPhone.length < 10) {
      setError('شماره تماس معتبر وارد کنید.');
      return;
    }
    if (normalizedPhone.length > 11) {
      setError('شماره تماس نباید بیشتر از ۱۱ رقم باشد.');
      return;
    }

    setSubmitting(true);
    try {
      await createPatient({
        full_name: fullName.trim(),
        national_id: normalizedNationalId,
        phone: normalizedPhone,
      });
      onClose();
    } catch (err: any) {
      setError(err.message || 'ثبت پرونده بیمار روی سرور ناکام ماند.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="تشکیل پرونده بیمار جدید"
      subtitle="مشخصات هویتی بیمار در سرور ثبت می‌شود."
      maxWidth="md"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3.5 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <div>
          <label className="d-label" htmlFor="new-patient-name">
            نام و نام خانوادگی بیمار
          </label>
          <input
            id="new-patient-name"
            className="d-input"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="مثلاً سارا صادقی"
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="new-patient-national-id">
            کد ملی (۱۰ رقم)
          </label>
          <input
            id="new-patient-national-id"
            className="d-input tabular-nums"
            maxLength={10}
            value={nationalId}
            onChange={(event) => setNationalId(event.target.value)}
            placeholder="۰۰۱۸۹۴۵۶۱۲"
            dir="ltr"
            inputMode="numeric"
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="new-patient-phone">
            شماره تلفن همراه
          </label>
          <input
            id="new-patient-phone"
            type="tel"
            className="d-input tabular-nums"
            maxLength={11}
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="۰۹۱۲۱۲۳۴۵۶۷"
            dir="ltr"
            inputMode="tel"
            required
          />
        </div>

        <div className="d-soft-info px-3.5 py-2.5 text-caption text-info leading-5">
          اعداد فارسی نیز پذیرفته می‌شوند و پیش از ارسال به سرور به شکل استاندارد تبدیل می‌گردند.
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line-soft pt-4">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={submitting}>
            انصراف
          </Button>
          <Button
            type="submit"
            size="sm"
            isLoading={submitting}
            icon={<UserPlus className="w-3.5 h-3.5" />}
          >
            ثبت پرونده
          </Button>
        </div>
      </form>
    </Modal>
  );
};
