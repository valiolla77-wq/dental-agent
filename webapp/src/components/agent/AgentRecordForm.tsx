import React, { useEffect, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useClinic } from '../../context/ClinicContext';
import { Button } from '../common/Button';
import { toLatinDigits } from '../../utils/persianDate';
import {
  AlertCircle,
  CheckCircle2,
  FilePlus2,
  ShieldCheck,
  UserPlus,
  X,
} from 'lucide-react';

type Relation = 'self' | 'other';

/**
 * In-chat patient registration form. The first patient is the account holder;
 * later additions are family/dependent records. National id is mandatory and
 * each patient phone must be unique. Identity always comes from the token
 * server-side; the form is only the data-entry surface.
 */
export const AgentRecordForm: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const { currentUser } = useAuth();
  const {
    recordFormRequired,
    selfRecordSubmitting,
    submitSelfRecord,
    closeSelfRecordForm,
  } = useClinic();
  const hasExisting =
    (currentUser?.patients?.length ?? 0) > 0 || !!currentUser?.patient;
  const [relation, setRelation] = useState<Relation>(hasExisting ? 'other' : 'self');
  const [fullName, setFullName] = useState('');
  const [phone, setPhone] = useState('');
  const [nationalId, setNationalId] = useState('');
  const [feedback, setFeedback] = useState<{ tone: 'error' | 'success'; text: string } | null>(
    null
  );

  useEffect(() => {
    if (!recordFormRequired || !currentUser) return;
    const accountHasHolder =
      (currentUser.patients?.length ?? 0) > 0 || !!currentUser.patient;
    if (accountHasHolder) {
      setRelation('other');
      setFullName('');
      setPhone('');
    } else {
      setRelation('self');
      setFullName((prev) => prev || currentUser.full_name);
      setPhone(currentUser.phone);
    }
    setNationalId('');
    setFeedback(null);
  }, [recordFormRequired, currentUser]);

  if (!recordFormRequired) return null;

  const switchRelation = (next: Relation) => {
    setRelation(next);
    setFeedback(null);
    if (next === 'self') {
      setFullName(currentUser?.full_name || '');
      setPhone(currentUser?.phone || '');
    } else {
      setFullName('');
      setPhone('');
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFeedback(null);

    const normalizedPhone = toLatinDigits(phone).replace(/\D/g, '');
    const normalizedNationalId = toLatinDigits(nationalId).replace(/\D/g, '');

    if (fullName.trim().length < 3) {
      setFeedback({ tone: 'error', text: 'نام و نام خانوادگی را کامل وارد کنید.' });
      return;
    }
    if (normalizedPhone.length < 10) {
      setFeedback({ tone: 'error', text: 'شماره تلفن معتبر وارد کنید.' });
      return;
    }
    if (normalizedNationalId.length !== 10) {
      setFeedback({ tone: 'error', text: 'کد ملی باید دقیقاً ۱۰ رقم باشد.' });
      return;
    }
    if (relation === 'other' && normalizedPhone === currentUser?.phone.replace(/\D/g, '')) {
      setFeedback({
        tone: 'error',
        text: 'شماره تلفن بیمار دیگر باید با شماره حساب متفاوت باشد.',
      });
      return;
    }

    try {
      await submitSelfRecord({
        full_name: fullName.trim(),
        phone: normalizedPhone,
        national_id: normalizedNationalId,
        relation,
      });
      setFeedback({ tone: 'success', text: 'پرونده با موفقیت ثبت شد.' });
    } catch (err: any) {
      setFeedback({
        tone: 'error',
        text: err?.message || 'ثبت پرونده ناکام ماند. دوباره تلاش کنید.',
      });
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={`rounded-[14px] border border-primary-line bg-surface ${
        compact ? 'p-3' : 'p-4'
      } space-y-3`}
    >
      <div className="flex items-start gap-2.5">
        <div className="shrink-0 w-8 h-8 rounded-full bg-primary-soft border border-primary-line flex items-center justify-center text-primary">
          {hasExisting ? <UserPlus className="w-4 h-4" /> : <FilePlus2 className="w-4 h-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-small font-bold text-ink">
            {hasExisting ? 'افزودن بیمار جدید به این حساب' : 'ثبت پرونده بیمار'}
          </div>
          <p className="text-caption text-muted leading-5 mt-1">
            {hasExisting
              ? 'این بیمار زیر همان حساب ذخیره می‌شود و در نوبت‌دهی قابل انتخاب است. کد ملی الزامی است.'
              : 'برای شروع گفتگو و رزرو نوبت، ابتدا پرونده بیمار را ثبت کنید. کد ملی و شماره تلفن الزامی است.'}
          </p>
        </div>
        {hasExisting && (
          <button
            type="button"
            onClick={closeSelfRecordForm}
            className="shrink-0 p-1 rounded-lg text-faint hover:text-danger hover:bg-danger-soft"
            aria-label="بستن فرم"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {!hasExisting && (
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => switchRelation('self')}
            className={`rounded-xl border px-2.5 py-2 text-right transition ${
              relation === 'self'
                ? 'border-primary bg-primary-soft'
                : 'border-line bg-surface hover:border-primary-line'
            }`}
          >
            <span className="block text-caption font-bold text-ink">برای خودم</span>
            <span className="block text-caption text-muted mt-0.5">
              صاحب حساب
            </span>
          </button>
          <button
            type="button"
            onClick={() => switchRelation('other')}
            className={`rounded-xl border px-2.5 py-2 text-right transition ${
              relation === 'other'
                ? 'border-primary bg-primary-soft'
                : 'border-line bg-surface hover:border-primary-line'
            }`}
          >
            <span className="block text-caption font-bold text-ink">برای بیمار دیگر</span>
            <span className="block text-caption text-muted mt-0.5">
              عضو خانواده
            </span>
          </button>
        </div>
      )}

      {hasExisting && (
        <div className="d-soft-teal px-3 py-2 text-caption leading-5 text-primary-deep">
          پرونده صاحب حساب قبلاً ثبت شده است؛ این فرم یک بیمار دیگر را به همان حساب اضافه می‌کند.
        </div>
      )}

      <div className={`grid grid-cols-1 gap-2 ${compact ? '' : 'sm:grid-cols-2'}`}>
        <div>
          <label className="d-label" htmlFor="self-record-name">
            نام و نام خانوادگی
          </label>
          <input
            id="self-record-name"
            type="text"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="نام و نام خانوادگی بیمار"
            className="d-input"
            dir="rtl"
            autoComplete="name"
          />
        </div>
        <div>
          <label className="d-label" htmlFor="self-record-phone">
            {relation === 'self' ? 'شماره تلفن (شماره حساب)' : 'شماره تلفن بیمار'}
          </label>
          <input
            id="self-record-phone"
            type="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="مثلاً 09121234567"
            className="d-input tabular-nums"
            dir="ltr"
            inputMode="tel"
            autoComplete="tel"
            readOnly={relation === 'self'}
          />
        </div>
        <div className={compact ? '' : 'sm:col-span-2'}>
          <label className="d-label" htmlFor="self-record-national-id">
            کد ملی <span className="text-danger">*</span>
          </label>
          <input
            id="self-record-national-id"
            type="text"
            value={nationalId}
            onChange={(event) => setNationalId(event.target.value)}
            placeholder="۱۰ رقم، بدون خط تیره"
            maxLength={10}
            className="d-input tabular-nums"
            dir="ltr"
            inputMode="numeric"
            autoComplete="off"
            required
          />
        </div>
      </div>

      {feedback && (
        <div
          className={`px-3 py-2 text-caption leading-5 flex items-start gap-1.5 ${
            feedback.tone === 'success' ? 'd-soft-teal text-primary-deep' : 'd-soft-danger text-danger'
          }`}
        >
          {feedback.tone === 'success' ? (
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          )}
          <span>{feedback.text}</span>
        </div>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1">
        <span className="text-caption text-faint leading-5 flex items-start gap-1">
          <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5" />
          همه پرونده‌ها زیر حساب واردشده ذخیره می‌شوند؛ هر شماره تلفن فقط برای یک بیمار است.
        </span>
        <Button
          type="submit"
          size="sm"
          isLoading={selfRecordSubmitting}
          disabled={selfRecordSubmitting}
        >
          {hasExisting ? 'افزودن بیمار' : 'ثبت و ادامه'}
        </Button>
      </div>
    </form>
  );
};
