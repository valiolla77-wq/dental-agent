import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import { User, UserCreate, UserRole } from '../../types';
import { toPersianDigits } from '../../utils/persianDate';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import { EmptyState } from '../common/EmptyState';
import { Badge } from '../common/Badge';
import {
  ErrorBanner,
  LoadingPanel,
  PageHeader,
  SectionCard,
  StatCard,
} from '../common/ui';
import {
  CheckCircle2,
  Search,
  ShieldCheck,
  UserPlus,
  Users,
  UserCog,
  XCircle,
  RefreshCw,
} from 'lucide-react';

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: 'admin', label: 'مدیر کلینیک' },
  { value: 'receptionist', label: 'پذیرش' },
  { value: 'doctor', label: 'دندان‌پزشک' },
  { value: 'patient', label: 'بیمار' },
];

type RoleFilter = 'all' | UserRole;

const EMPTY_FORM: UserCreate = {
  full_name: '',
  phone: '',
  password: '',
  role: 'receptionist',
};

export const UsersView: React.FC = () => {
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('all');
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<UserCreate>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await apiClient.getUsers());
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت کاربران ناکام ماند');
      setUsers(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(() => {
    const rows = users || [];
    return {
      all: rows.length,
      admin: rows.filter((user) => user.role === 'admin').length,
      receptionist: rows.filter((user) => user.role === 'receptionist').length,
      doctor: rows.filter((user) => user.role === 'doctor').length,
      patient: rows.filter((user) => user.role === 'patient').length,
      active: rows.filter((user) => user.is_active).length,
    };
  }, [users]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (users || []).filter((user) => {
      const matchesRole = roleFilter === 'all' || user.role === roleFilter;
      const matchesQuery =
        !query ||
        user.full_name.toLowerCase().includes(query) ||
        user.phone.includes(query) ||
        ROLE_OPTIONS.find((role) => role.value === user.role)?.label.includes(query);
      return matchesRole && matchesQuery;
    });
  }, [users, search, roleFilter]);

  const changeRole = async (user: User, role: UserRole) => {
    const snapshot = users;
    setUsers((prev) =>
      prev ? prev.map((row) => (row.id === user.id ? { ...row, role } : row)) : prev
    );
    try {
      await apiClient.updateUser(user.id, { role });
      await load();
    } catch (err: any) {
      setUsers(snapshot);
      setError(err.message || 'تغییر نقش ناکام ماند');
    }
  };

  const toggleActive = async (user: User) => {
    const snapshot = users;
    setUsers((prev) =>
      prev
        ? prev.map((row) => (row.id === user.id ? { ...row, is_active: !row.is_active } : row))
        : prev
    );
    try {
      await apiClient.updateUser(user.id, { is_active: !user.is_active });
      await load();
    } catch (err: any) {
      setUsers(snapshot);
      setError(err.message || 'تغییر وضعیت حساب ناکام ماند');
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (form.full_name.trim().length < 3) {
      setFormError('نام و نام خانوادگی را کامل وارد کنید.');
      return;
    }
    if (form.phone.trim().length < 10) {
      setFormError('شماره تماس معتبر وارد کنید.');
      return;
    }
    if (form.password.trim().length < 6) {
      setFormError('رمز عبور باید حداقل ۶ کاراکتر باشد.');
      return;
    }
    setSubmitting(true);
    try {
      await apiClient.createUser({
        ...form,
        full_name: form.full_name.trim(),
        phone: form.phone.trim(),
      });
      setForm(EMPTY_FORM);
      setCreateOpen(false);
      await load();
    } catch (err: any) {
      setFormError(err.message || 'ایجاد کاربر ناکام ماند');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="کاربران و دسترسی‌ها"
        subtitle="حساب‌های کلینیک، نقش‌ها و وضعیت فعال‌بودن؛ تغییرات مستقیماً روی سرور ثبت می‌شوند."
        action={
          <>
            <Button
              variant="outline"
              size="md"
              onClick={load}
              disabled={loading}
              icon={<RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />}
            >
              به‌روزرسانی
            </Button>
            <Button
              size="md"
              onClick={() => {
                setFormError(null);
                setCreateOpen(true);
              }}
              icon={<UserPlus className="w-4 h-4" />}
            >
              ایجاد حساب
            </Button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4 mb-5">
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="کل کاربران"
          value={toPersianDigits(counts.all)}
          hint={`${toPersianDigits(counts.active)} حساب فعال`}
        />
        <StatCard
          icon={<UserCog className="w-[18px] h-[18px]" />}
          label="کادر درمان و پذیرش"
          value={toPersianDigits(counts.admin + counts.receptionist + counts.doctor)}
          hint={`${toPersianDigits(counts.doctor)} پزشک · ${toPersianDigits(counts.receptionist)} پذیرش`}
          tone="soft"
        />
        <StatCard
          icon={<ShieldCheck className="w-[18px] h-[18px]" />}
          label="مدیران کلینیک"
          value={toPersianDigits(counts.admin)}
          hint="دسترسی کامل مدیریتی"
          tone="ai"
        />
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="بیماران"
          value={toPersianDigits(counts.patient)}
          hint="حساب‌های متصل به پرونده"
        />
      </div>

      <SectionCard
        title="فهرست حساب‌ها"
        subtitle="نقش هر حساب را می‌توانید از همین جدول تغییر دهید"
        noPadding
      >
        <div className="p-4 sm:p-5 border-b border-line-soft flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex gap-1.5 overflow-x-auto no-scrollbar pb-1 lg:pb-0">
            {(['all', 'admin', 'receptionist', 'doctor', 'patient'] as RoleFilter[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRoleFilter(value)}
                className={`d-chip shrink-0 ${roleFilter === value ? 'active' : ''}`}
              >
                {value === 'all' ? 'همه' : ROLE_OPTIONS.find((role) => role.value === value)?.label}
                <span className="opacity-70">({toPersianDigits(counts[value])})</span>
              </button>
            ))}
          </div>
          <div className="d-search w-full lg:w-64">
            <Search className="w-4 h-4" />
            <input
              className="d-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="جستجوی نام یا شماره تماس..."
              aria-label="جستجوی کاربر"
            />
          </div>
        </div>

        {loading && users === null ? (
          <LoadingPanel message="در حال دریافت کاربران..." />
        ) : filtered.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={<Users className="w-5 h-5" />}
              title="کاربری یافت نشد"
              description={
                (users || []).length === 0
                  ? 'هنوز حسابی در سامانه ثبت نشده است.'
                  : 'فیلتر یا عبارت جستجو با هیچ کاربری مطابقت ندارد.'
              }
              actionLabel="پاک کردن فیلترها"
              onAction={() => {
                setSearch('');
                setRoleFilter('all');
              }}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="d-table">
              <thead>
                <tr>
                  <th>کاربر</th>
                  <th>شماره تماس</th>
                  <th>نقش</th>
                  <th>وضعیت</th>
                  <th className="text-left">عملیات</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <span className="w-8 h-8 rounded-full bg-primary-soft border border-primary-line text-primary-deep text-small font-bold flex items-center justify-center shrink-0">
                          {user.full_name.charAt(0)}
                        </span>
                        <span className="font-semibold text-ink">{user.full_name}</span>
                      </div>
                    </td>
                    <td className="tabular-nums text-muted" dir="ltr">
                      {toPersianDigits(user.phone)}
                    </td>
                    <td>
                      <select
                        value={user.role}
                        onChange={(event) => changeRole(user, event.target.value as UserRole)}
                        className="h-8 rounded-[8px] border border-line bg-surface px-2 text-caption text-ink cursor-pointer focus:outline-none focus:border-primary"
                        aria-label={`نقش ${user.full_name}`}
                      >
                        {ROLE_OPTIONS.map((role) => (
                          <option key={role.value} value={role.value}>
                            {role.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <Badge variant={user.is_active ? 'success' : 'neutral'} dot>
                        {user.is_active ? 'فعال' : 'غیرفعال'}
                      </Badge>
                    </td>
                    <td className="text-left">
                      <button
                        type="button"
                        onClick={() => toggleActive(user)}
                        className={`inline-flex items-center gap-1 text-caption font-semibold ${
                          user.is_active
                            ? 'text-danger hover:text-danger-deep'
                            : 'text-primary hover:text-primary-deep'
                        }`}
                      >
                        {user.is_active ? (
                          <XCircle className="w-3.5 h-3.5" />
                        ) : (
                          <CheckCircle2 className="w-3.5 h-3.5" />
                        )}
                        {user.is_active ? 'غیرفعال کردن' : 'فعال‌سازی'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <Modal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        title="ایجاد حساب کاربری جدید"
        subtitle="حساب با نقش انتخاب‌شده در سرور ساخته می‌شود."
        maxWidth="md"
      >
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="d-label" htmlFor="new-user-name">
              نام و نام خانوادگی
            </label>
            <input
              id="new-user-name"
              className="d-input"
              value={form.full_name}
              onChange={(event) => setForm({ ...form, full_name: event.target.value })}
              placeholder="مثلاً مریم رضایی"
              required
            />
          </div>
          <div>
            <label className="d-label" htmlFor="new-user-phone">
              شماره تماس (نام کاربری)
            </label>
            <input
              id="new-user-phone"
              className="d-input tabular-nums"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
              placeholder="۰۹۱۲۱۲۳۴۵۶۷"
              dir="ltr"
              inputMode="tel"
              required
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="d-label" htmlFor="new-user-role">
                نقش
              </label>
              <select
                id="new-user-role"
                className="d-select"
                value={form.role}
                onChange={(event) =>
                  setForm({ ...form, role: event.target.value as UserRole })
                }
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="d-label" htmlFor="new-user-password">
                رمز عبور
              </label>
              <input
                id="new-user-password"
                type="password"
                className="d-input"
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                placeholder="حداقل ۶ کاراکتر"
                dir="ltr"
                required
              />
            </div>
          </div>
          {formError && (
            <div className="d-soft-danger px-3 py-2 text-caption text-danger">{formError}</div>
          )}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" size="sm" onClick={() => setCreateOpen(false)}>
              انصراف
            </Button>
            <Button type="submit" size="sm" isLoading={submitting} icon={<UserPlus className="w-3.5 h-3.5" />}>
              ایجاد حساب
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
