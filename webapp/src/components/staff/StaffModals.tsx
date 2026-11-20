/**
 * Staff management dialogs: create account, role promotion, password reset,
 * delete confirmation and the per-account permission matrix. Every sensitive
 * action mirrors an SaaS admin pattern: explicit confirmation, typed password
 * fields and a written trail (the backend records each change in the audit
 * log).
 */

import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Check, Loader2, ShieldCheck, X } from 'lucide-react';
import {
  PermissionOverrideMap,
  User,
  UserPermissions,
  UserRole,
} from '../../types';
import { apiClient } from '../../api/client';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { InfoBanner } from '../common/ui';
import { ROLE_LABELS } from '../../utils/rbac';
import {
  STAFF_ROLE_HINTS,
  STAFF_ROLE_ORDER,
  actionLabel,
} from './permissionLabels';

interface BaseProps {
  onClose: () => void;
  onDone: (message: string) => void;
}

/* ------------------------------------------------------- create staff */

export const CreateStaffModal: React.FC<BaseProps> = ({ onClose, onDone }) => {
  const [fullName, setFullName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('receptionist');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const safePhone = phone.replace(/\D/g, '');
    if (!fullName.trim() || safePhone.length < 8 || password.length < 8) {
      setError('نام، شماره تلفن معتبر و کلمه عبور حداقل ۸ نویسه الزامی است.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.createUser({
        full_name: fullName.trim(),
        phone: safePhone,
        password,
        role,
      });
      onDone(`حساب «${fullName.trim()}» ساخته شد.`);
    } catch (err: any) {
      setError(err.message || 'ساخت حساب ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title="ایجاد حساب پرسنل"
      subtitle="حساب پس از ساخت می‌تواند از درگاه پرسنل با کلمه عبور وارد شود."
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <div>
          <label className="d-label" htmlFor="staff-name">نام و نام خانوادگی</label>
          <input
            id="staff-name"
            className="d-input"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="مثلاً سارا محمدی"
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="staff-phone">شماره تلفن همراه</label>
          <input
            id="staff-phone"
            className="d-input tabular-nums"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="۰۹۱۲۱۲۳۴۵۶۷"
            dir="ltr"
            inputMode="tel"
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="staff-password">کلمه عبور اولیه (حداقل ۸ نویسه)</label>
          <input
            id="staff-password"
            type="password"
            className="d-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            minLength={8}
            required
          />
        </div>

        <div>
          <span className="d-label">سمت سازمانی</span>
          <div className="grid grid-cols-1 gap-2 mt-1.5">
            {STAFF_ROLE_ORDER.map((option) => (
              <label
                key={option}
                className={`flex items-start gap-2.5 p-3 rounded-[10px] border cursor-pointer transition-colors ${
                  role === option
                    ? 'border-primary bg-primary-soft/60'
                    : 'border-line hover:border-primary-line'
                }`}
              >
                <input
                  type="radio"
                  name="staff-role"
                  className="mt-1 accent-primary"
                  checked={role === option}
                  onChange={() => setRole(option)}
                />
                <span className="min-w-0">
                  <span className="block text-small font-bold text-ink">
                    {ROLE_LABELS[option].title}
                  </span>
                  <span className="block text-caption text-muted leading-5 mt-0.5">
                    {STAFF_ROLE_HINTS[option]}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          <Button type="submit" isLoading={saving}>ایجاد حساب</Button>
        </div>
      </form>
    </Modal>
  );
};

/* ------------------------------------------------------ role promotion */

interface PromoteProps extends BaseProps {
  staff: User;
}

export const PromoteStaffModal: React.FC<PromoteProps> = ({ staff, onClose, onDone }) => {
  const [role, setRole] = useState<UserRole>(staff.role);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (role === staff.role) {
      setError('سمت انتخاب‌شده با سمت فعلی یکسان است.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.updateUser(staff.id, { role });
      onDone(
        `سمت «${staff.full_name}» از ${ROLE_LABELS[staff.role].title} به ${ROLE_LABELS[role].title} تغییر کرد.`
      );
    } catch (err: any) {
      setError(err.message || 'تغییر سمت ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`تغییر سمت ${staff.full_name}`}
      subtitle={`سمت فعلی: ${ROLE_LABELS[staff.role].title} — با تغییر سمت، دسترسی‌های سفارشی این حساب بازنشانی می‌شود.`}
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <div className="grid grid-cols-1 gap-2">
          {STAFF_ROLE_ORDER.map((option) => (
            <label
              key={option}
              className={`flex items-start gap-2.5 p-3 rounded-[10px] border cursor-pointer transition-colors ${
                role === option
                  ? 'border-primary bg-primary-soft/60'
                  : 'border-line hover:border-primary-line'
              }`}
            >
              <input
                type="radio"
                name="promote-role"
                className="mt-1 accent-primary"
                checked={role === option}
                onChange={() => setRole(option)}
              />
              <span className="min-w-0">
                <span className="block text-small font-bold text-ink">
                  {ROLE_LABELS[option].title}
                </span>
                <span className="block text-caption text-muted leading-5 mt-0.5">
                  {STAFF_ROLE_HINTS[option]}
                </span>
              </span>
            </label>
          ))}
        </div>

        <InfoBanner tone="warning">
          حساب‌های بیمار از این فهرست حذف شده‌اند؛ ارتقای حساب بیمار به پرسنل از مسیر
          ساخت حساب جدید انجام می‌شود تا سلسله‌مراتب دسترسی همیشه شفاف بماند.
        </InfoBanner>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          <Button type="submit" isLoading={saving}>ثبت تغییر سمت</Button>
        </div>
      </form>
    </Modal>
  );
};

/* ------------------------------------------------------ password reset */

export const ResetPasswordModal: React.FC<PromoteProps> = ({ staff, onClose, onDone }) => {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError('کلمه عبور باید حداقل ۸ نویسه باشد.');
      return;
    }
    if (password !== confirm) {
      setError('تکرار کلمه عبور مطابقت ندارد.');
      return;
    }
    setSaving(true);
    try {
      await apiClient.updateUser(staff.id, { password });
      onDone(
        `کلمه عبور «${staff.full_name}» بازنشانی شد؛ نشست‌های فعال این حساب باطل می‌شوند.`
      );
    } catch (err: any) {
      setError(err.message || 'بازنشانی کلمه عبور ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`بازنشانی کلمه عبور ${staff.full_name}`}
      subtitle="بهتر است کلمه عبور جدید را حضوری یا از راه امن به فرد تحویل دهید."
    >
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span className="leading-5">{error}</span>
          </div>
        )}

        <div>
          <label className="d-label" htmlFor="reset-password">کلمه عبور جدید</label>
          <input
            id="reset-password"
            type="password"
            className="d-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
        </div>

        <div>
          <label className="d-label" htmlFor="reset-confirm">تکرار کلمه عبور جدید</label>
          <input
            id="reset-confirm"
            type="password"
            className="d-input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
        </div>

        <InfoBanner tone="info" icon={<ShieldCheck className="w-4 h-4" />}>
          کلمه عبور با الگوریتم Argon2id ذخیره می‌شود و توکن‌های باز با «اثر انگشت
          کلمه عبور» سمت سرور بی‌اعتبار می‌شوند.
        </InfoBanner>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
          <Button type="submit" isLoading={saving}>بازنشانی کلمه عبور</Button>
        </div>
      </form>
    </Modal>
  );
};

/* -------------------------------------------------------- delete staff */

export const DeleteStaffModal: React.FC<PromoteProps> = ({ staff, onClose, onDone }) => {
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiClient.deleteStaffUser(staff.id);
      onDone(`حساب «${staff.full_name}» برای همیشه حذف شد.`);
    } catch (err: any) {
      setError(err.message || 'حذف حساب ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`حذف حساب ${staff.full_name}`}
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
          <li>پرونده‌های بیمار و پزشک متصل به این حساب، بدون حذف، جدا می‌شوند.</li>
          <li>گفتگوهای دستیار و بازخوردهای این حساب ناشناس می‌مانند.</li>
          <li>حذف مدیر نهایی سیستم ممکن نیست.</li>
        </ul>

        <div>
          <label className="d-label" htmlFor="delete-confirm">
            برای تأیید، کلمهٔ «حذف» را بنویسید
          </label>
          <input
            id="delete-confirm"
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
            حذف قطعی حساب
          </Button>
        </div>
      </form>
    </Modal>
  );
};

/* -------------------------------------------------- permission matrix */

type OverrideChoice = 'inherit' | 'allow' | 'deny';

export const PermissionsModal: React.FC<PromoteProps> = ({ staff, onClose, onDone }) => {
  const [matrix, setMatrix] = useState<UserPermissions | null>(null);
  const [choices, setChoices] = useState<Record<string, OverrideChoice>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiClient.getStaffPermissions(staff.id);
        if (cancelled) return;
        setMatrix(data);
        const initial: Record<string, OverrideChoice> = {};
        for (const item of data.actions) {
          initial[item.action] = item.override ?? 'inherit';
        }
        setChoices(initial);
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'خواندن دسترسی‌ها ناکام ماند.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [staff.id]);

  const changedCount = useMemo(
    () =>
      Object.values(choices).filter((value) => value !== 'inherit').length,
    [choices]
  );

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const overrides: PermissionOverrideMap = {};
      for (const [action, choice] of Object.entries(choices)) {
        if (choice === 'allow' || choice === 'deny') overrides[action] = choice;
      }
      await apiClient.updateStaffPermissions(staff.id, overrides);
      onDone(
        `دسترسی‌های «${staff.full_name}» به‌روزرسانی شد (${changedCount} مورد سفارشی).`
      );
    } catch (err: any) {
      setError(err.message || 'ذخیرهٔ دسترسی‌ها ناکام ماند.');
    } finally {
      setSaving(false);
    }
  };

  const setChoice = (action: string, choice: OverrideChoice) => {
    setChoices((prev) => ({ ...prev, [action]: choice }));
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`دسترسی‌های ${staff.full_name}`}
      subtitle="پیش‌فرض هر دسترسی از سمت سازمانی می‌آید؛ می‌توانید آن را برای این حساب اجازه یا رد کنید."
      maxWidth="2xl"
    >
      {loading ? (
        <div className="py-10 flex items-center justify-center gap-2 text-small text-muted">
          <Loader2 className="w-4 h-4 animate-spin" />
          در حال خواندن دسترسی‌ها...
        </div>
      ) : error && !matrix ? (
        <div className="d-soft-danger px-4 py-3 text-small text-danger">{error}</div>
      ) : (
        <div className="space-y-4">
          {error && (
            <div className="d-soft-danger px-3 py-2.5 text-caption text-danger flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span className="leading-5">{error}</span>
            </div>
          )}

          <div className="overflow-x-auto no-scrollbar">
            <table className="w-full text-right d-table">
              <thead>
                <tr>
                  <th className="min-w-[180px]">دسترسی</th>
                  <th className="text-center w-[92px]">پیش‌فرض سمت</th>
                  <th className="text-center w-[76px]">اجازه</th>
                  <th className="text-center w-[76px]">رد</th>
                  <th className="text-center w-[86px]">اثر نهایی</th>
                </tr>
              </thead>
              <tbody>
                {(matrix?.actions || []).map((item) => {
                  const choice = choices[item.action] ?? 'inherit';
                  return (
                    <tr key={item.action}>
                      <td>
                        <span className="text-small font-semibold text-ink">
                          {actionLabel(item.action)}
                        </span>
                        <span className="block text-caption text-faint font-mono" dir="ltr">
                          {item.action}
                        </span>
                      </td>
                      <td className="text-center">
                        <span
                          className={`text-caption font-bold ${
                            item.role_default ? 'text-primary-deep' : 'text-faint'
                          }`}
                        >
                          {item.role_default ? 'دارد' : 'ندارد'}
                        </span>
                      </td>
                      <td className="text-center">
                        <input
                          type="radio"
                          name={`perm-${item.action}`}
                          aria-label={`اجازه: ${actionLabel(item.action)}`}
                          className="accent-primary"
                          checked={choice === 'allow'}
                          onChange={() => setChoice(item.action, 'allow')}
                        />
                      </td>
                      <td className="text-center">
                        <input
                          type="radio"
                          name={`perm-${item.action}`}
                          aria-label={`رد: ${actionLabel(item.action)}`}
                          className="accent-danger"
                          checked={choice === 'deny'}
                          onChange={() => setChoice(item.action, 'deny')}
                        />
                      </td>
                      <td className="text-center">
                        {item.effective ? (
                          <span className="inline-flex items-center gap-1 text-caption font-bold text-primary-deep">
                            <Check className="w-3.5 h-3.5" /> فعال
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-caption font-bold text-faint">
                            <X className="w-3.5 h-3.5" /> بسته
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-2 pt-1">
            <span className="text-caption text-muted">
              {changedCount === 0
                ? 'همهٔ دسترسی‌ها از پیش‌فرض سمت پیروی می‌کنند.'
                : `${changedCount} دسترسی برای این حساب سفارشی شده است.`}
            </span>
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>انصراف</Button>
              <Button onClick={save} isLoading={saving}>ذخیرهٔ دسترسی‌ها</Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
};
