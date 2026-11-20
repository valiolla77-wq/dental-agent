/**
 * پرسنل و دسترسی‌ها — the staff back-office for admins.
 *
 * Patterns adopted from established clinic/SaaS admin panels (Open Dental's
 * user groups + audit trail, member tables with inline role pickers):
 *  - stat strip + searchable member table with role/status badges
 *  - last-login bookkeeping so dormant accounts are visible
 *  - explicit confirmations for role change, password reset and deletion
 *  - per-account permission matrix (inherit / allow / deny)
 *  - append-only activity trail rendered next to the accounts tab
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarClock,
  KeyRound,
  ListChecks,
  Lock,
  LockOpen,
  Search,
  ShieldCheck,
  Trash2,
  UserPlus,
  UserRoundCog,
  Users,
} from 'lucide-react';
import { AuditLogItem, User, UserRole } from '../../types';
import { apiClient } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { Avatar } from '../common/ui';
import {
  PageHeader,
  StatCard,
  SectionCard,
  Segmented,
  InfoBanner,
  ErrorBanner,
  LoadingPanel,
} from '../common/ui';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { EmptyState } from '../common/EmptyState';
import { ROLE_LABELS } from '../../utils/rbac';
import { Modal } from '../common/Modal';
import {
  CreateStaffModal,
  DeleteStaffModal,
  PermissionsModal,
  PromoteStaffModal,
  ResetPasswordModal,
} from './StaffModals';
import {
  auditActionLabel,
  utcIsoToJalali,
} from './permissionLabels';

type StaffTab = 'accounts' | 'activity';

interface DialogState {
  kind: 'create' | 'promote' | 'reset' | 'delete' | 'permissions';
  staff?: User;
}

const ROLE_BADGE_VARIANT: Record<string, 'teal' | 'info' | 'ai' | 'default'> = {
  admin: 'ai',
  receptionist: 'teal',
  doctor: 'info',
  patient: 'default',
};

export const StaffView: React.FC = () => {
  const { currentUser, hasPerm } = useAuth();
  const [staff, setStaff] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<StaffTab>('accounts');
  const [search, setSearch] = useState('');
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const canManage = hasPerm('manage_staff');

  const loadStaff = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const users = await apiClient.getUsers();
      // Patient accounts live in the بیماران section; the staff table keeps
      // the back-office personas only (admin/receptionist/doctor).
      setStaff(users.filter((user) => user.role !== 'patient'));
    } catch (err: any) {
      setLoadError(err.message || 'دریافت فهرست پرسنل ناکام ماند.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const loadAudit = useCallback(async () => {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const logs = await apiClient.getAuditLogs({ limit: 120 });
      setAuditLogs(logs);
    } catch (err: any) {
      setAuditError(err.message || 'دریافت گزارش فعالیت ناکام ماند.');
    } finally {
      setAuditLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canManage) {
      loadStaff();
    } else {
      setIsLoading(false);
    }
  }, [canManage, loadStaff]);

  useEffect(() => {
    if (tab === 'activity' && canManage) {
      loadAudit();
    }
  }, [tab, canManage, loadAudit]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(timer);
  }, [toast]);

  const filtered = useMemo(() => {
    const needle = search.trim();
    if (!needle) return staff;
    return staff.filter(
      (user) =>
        user.full_name.includes(needle) ||
        user.phone.includes(needle) ||
        (ROLE_LABELS[user.role]?.title || '').includes(needle)
    );
  }, [staff, search]);

  const stats = useMemo(() => {
    const active = staff.filter((user) => user.is_active).length;
    const admins = staff.filter((user) => user.role === 'admin').length;
    const thirtyDaysAgo = Date.now() - 30 * 24 * 3600 * 1000;
    const recentLogins = staff.filter(
      (user) =>
        user.last_login_at &&
        new Date(`${user.last_login_at}Z`).getTime() >= thirtyDaysAgo
    ).length;
    return { total: staff.length, active, admins, recentLogins };
  }, [staff]);

  const handleDone = useCallback(
    async (message: string) => {
      setDialog(null);
      setToast(message);
      await loadStaff();
      if (tab === 'activity') await loadAudit();
    },
    [loadStaff, loadAudit, tab]
  );

  const toggleActive = async (user: User) => {
    try {
      await apiClient.updateUser(user.id, { is_active: !user.is_active });
      setToast(
        user.is_active
          ? `حساب «${user.full_name}» غیرفعال شد و دیگر نمی‌تواند وارد شود.`
          : `حساب «${user.full_name}» دوباره فعال شد.`
      );
      await loadStaff();
    } catch (err: any) {
      setToast(err.message || 'تغییر وضعیت حساب ناکام ماند.');
    }
  };

  if (!canManage) {
    return (
      <div className="d-page d-fade">
        <PageHeader title="پرسنل و دسترسی‌ها" eyebrow="فضای کار مدیر" />
        <InfoBanner tone="warning">
          این بخش فقط برای مدیر کلینیک فعال است؛ برای تغییر سمت یا دسترسی با
          مدیر سامانه تماس بگیرید.
        </InfoBanner>
      </div>
    );
  }

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="پرسنل و دسترسی‌ها"
        eyebrow="مدیریت تیم کلینیک"
        subtitle="سمت‌ها را ارتقا دهید، دسترسی هر حساب را تنظیم کنید و همهٔ تغییرات حساس را پیگیری کنید."
        action={
          <Button
            icon={<UserPlus className="w-4 h-4" />}
            onClick={() => setDialog({ kind: 'create' })}
          >
            حساب جدید پرسنل
          </Button>
        }
      />

      {toast && (
        <div className="d-soft-teal px-4 py-3 mb-4 text-small text-primary-deep flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 shrink-0" />
          {toast}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-6">
        <StatCard
          icon={<Users className="w-4.5 h-4.5" />}
          label="کل حساب‌های پرسنل"
          value={stats.total}
          hint="بدون حساب بیماران"
        />
        <StatCard
          icon={<LockOpen className="w-4.5 h-4.5" />}
          label="حساب‌های فعال"
          value={stats.active}
          tone="soft"
        />
        <StatCard
          icon={<ShieldCheck className="w-4.5 h-4.5" />}
          label="مدیران کلینیک"
          value={stats.admins}
          tone="ai"
        />
        <StatCard
          icon={<CalendarClock className="w-4.5 h-4.5" />}
          label="ورود در ۳۰ روز اخیر"
          value={stats.recentLogins}
          tone="soft"
        />
      </div>

      <div className="mb-4">
        <Segmented<StaffTab>
          options={[
            { value: 'accounts', label: 'حساب‌ها', count: staff.length },
            { value: 'activity', label: 'گزارش فعالیت' },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>

      {tab === 'accounts' ? (
        <SectionCard
          title="حساب‌های پرسنل"
          subtitle="مدیران، پذیرش و پزشکان؛ حساب بیماران در بخش «بیماران و پرونده‌ها» مدیریت می‌شود."
          noPadding
          action={
            <div className="relative w-[220px]">
              <Search className="w-4 h-4 text-faint absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                className="d-input !pr-9 !h-9 text-caption"
                placeholder="جستجوی نام، تلفن یا سمت..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="جستجو در حساب‌های پرسنل"
              />
            </div>
          }
        >
          {isLoading ? (
            <LoadingPanel message="در حال دریافت حساب‌ها..." />
          ) : loadError ? (
            <div className="p-5">
              <ErrorBanner message={loadError} onRetry={loadStaff} />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Users className="w-8 h-8" />}
              title="حسابی پیدا نشد"
              description="با تغییر عبارت جستجو یا افزودن حساب جدید شروع کنید."
              actionLabel="ساخت حساب پرسنل"
              onAction={() => setDialog({ kind: 'create' })}
            />
          ) : (
            <div className="overflow-x-auto no-scrollbar">
              <table className="w-full text-right d-table">
                <thead>
                  <tr>
                    <th>حساب</th>
                    <th className="text-center">سمت</th>
                    <th className="text-center">وضعیت</th>
                    <th className="text-center">تاریخ عضویت</th>
                    <th className="text-center">آخرین ورود</th>
                    <th className="text-center">عملیات</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((user) => {
                    const isSelf = currentUser?.phone === user.phone;
                    const overrides = user.permission_overrides || {};
                    const overrideCount = Object.keys(overrides).length;
                    return (
                      <tr key={user.id}>
                        <td>
                          <div className="flex items-center gap-2.5">
                            <Avatar name={user.full_name} size="sm" />
                            <div className="min-w-0">
                              <div className="text-small font-bold text-ink truncate">
                                {user.full_name}
                                {isSelf && (
                                  <span className="text-caption text-primary font-semibold"> (شما)</span>
                                )}
                              </div>
                              <div className="text-caption text-faint tabular-nums" dir="ltr">
                                {user.phone}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="text-center">
                          <Badge variant={ROLE_BADGE_VARIANT[user.role] || 'default'} dot>
                            {ROLE_LABELS[user.role]?.title || user.role}
                          </Badge>
                          {overrideCount > 0 && (
                            <span className="block text-caption text-ai mt-1">
                              {overrideCount} دسترسی سفارشی
                            </span>
                          )}
                        </td>
                        <td className="text-center">
                          {user.is_active ? (
                            <Badge variant="success" dot>فعال</Badge>
                          ) : (
                            <Badge variant="danger" dot>غیرفعال</Badge>
                          )}
                        </td>
                        <td className="text-center text-caption text-muted tabular-nums whitespace-nowrap">
                          {utcIsoToJalali(user.created_at, false)}
                        </td>
                        <td className="text-center text-caption text-muted tabular-nums whitespace-nowrap">
                          {user.last_login_at
                            ? utcIsoToJalali(user.last_login_at)
                            : 'بدون ورود'}
                        </td>
                        <td className="text-center">
                          <div className="inline-flex items-center justify-center gap-1">
                            <IconAction
                              title="دسترسی‌های این حساب"
                              onClick={() => setDialog({ kind: 'permissions', staff: user })}
                              disabled={user.role === 'admin'}
                            >
                              <ListChecks className="w-4 h-4" />
                            </IconAction>
                            <IconAction
                              title="تغییر سمت"
                              onClick={() => setDialog({ kind: 'promote', staff: user })}
                              disabled={isSelf}
                            >
                              <UserRoundCog className="w-4 h-4" />
                            </IconAction>
                            <IconAction
                              title="بازنشانی کلمه عبور"
                              onClick={() => setDialog({ kind: 'reset', staff: user })}
                            >
                              <KeyRound className="w-4 h-4" />
                            </IconAction>
                            <IconAction
                              title={user.is_active ? 'غیرفعال‌سازی حساب' : 'فعال‌سازی حساب'}
                              onClick={() => toggleActive(user)}
                              disabled={isSelf}
                              danger={user.is_active}
                            >
                              {user.is_active ? (
                                <Lock className="w-4 h-4" />
                              ) : (
                                <LockOpen className="w-4 h-4" />
                              )}
                            </IconAction>
                            <IconAction
                              title="حذف حساب"
                              onClick={() => setDialog({ kind: 'delete', staff: user })}
                              disabled={isSelf}
                              danger
                            >
                              <Trash2 className="w-4 h-4" />
                            </IconAction>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      ) : (
        <SectionCard
          title="گزارش فعالیت"
          subtitle="دنبالهٔ فقط-افزودنی از همهٔ تغییرات حساس؛ هیچ ردیفی از این گزارش حذف یا ویرایش نمی‌شود."
          noPadding
          action={
            <Button variant="outline" size="sm" onClick={loadAudit} isLoading={auditLoading}>
              به‌روزرسانی
            </Button>
          }
        >
          {auditLoading && auditLogs.length === 0 ? (
            <LoadingPanel message="در حال دریافت گزارش فعالیت..." />
          ) : auditError ? (
            <div className="p-5">
              <ErrorBanner message={auditError} onRetry={loadAudit} />
            </div>
          ) : auditLogs.length === 0 ? (
            <EmptyState
              icon={<ShieldCheck className="w-8 h-8" />}
              title="فعالیتی ثبت نشده است"
              description="به‌محض انجام تغییرات مدیریتی، ردیف‌های این گزارش این‌جا دیده می‌شوند."
            />
          ) : (
            <div className="overflow-x-auto no-scrollbar">
              <table className="w-full text-right d-table">
                <thead>
                  <tr>
                    <th>زمان</th>
                    <th>رویداد</th>
                    <th>انجام‌دهنده</th>
                    <th>هدف</th>
                    <th>جزئیات</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((log) => (
                    <tr key={log.id}>
                      <td className="text-caption text-muted tabular-nums whitespace-nowrap">
                        {utcIsoToJalali(log.created_at)}
                      </td>
                      <td>
                        <Badge
                          variant={
                            log.action.endsWith('delete')
                              ? 'danger'
                              : log.action.includes('permissions')
                              ? 'ai'
                              : 'teal'
                          }
                        >
                          {auditActionLabel(log.action)}
                        </Badge>
                      </td>
                      <td className="text-caption text-muted tabular-nums" dir="ltr">
                        {log.actor_phone || '—'}
                      </td>
                      <td className="text-small text-ink">{log.target_label || '—'}</td>
                      <td className="text-caption text-muted max-w-[260px]">
                        <span className="line-clamp-2 break-all" dir="auto">
                          {log.detail ? JSON.stringify(log.detail) : '—'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}

      {dialog?.kind === 'create' && (
        <CreateStaffModal onClose={() => setDialog(null)} onDone={handleDone} />
      )}
      {dialog?.kind === 'promote' && dialog.staff && (
        <PromoteStaffModal
          staff={dialog.staff}
          onClose={() => setDialog(null)}
          onDone={handleDone}
        />
      )}
      {dialog?.kind === 'reset' && dialog.staff && (
        <ResetPasswordModal
          staff={dialog.staff}
          onClose={() => setDialog(null)}
          onDone={handleDone}
        />
      )}
      {dialog?.kind === 'delete' && dialog.staff && (
        <DeleteStaffModal
          staff={dialog.staff}
          onClose={() => setDialog(null)}
          onDone={handleDone}
        />
      )}
      {dialog?.kind === 'permissions' && dialog.staff && (
        <PermissionsModal
          staff={dialog.staff}
          onClose={() => setDialog(null)}
          onDone={handleDone}
        />
      )}
    </div>
  );
};

const IconAction: React.FC<{
  title: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}> = ({ title, onClick, disabled, danger, children }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    disabled={disabled}
    onClick={onClick}
    className={`p-2 rounded-[9px] transition-colors disabled:opacity-30 disabled:pointer-events-none ${
      danger
        ? 'text-faint hover:text-danger hover:bg-danger-soft'
        : 'text-faint hover:text-primary hover:bg-primary-soft'
    }`}
  >
    {children}
  </button>
);
