import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { apiClient } from '../../api/client';
import { ROLE_LABELS, ROLE_PERMISSIONS, Permission } from '../../utils/rbac';
import { toPersianDigits } from '../../utils/persianDate';
import { Badge, RoleBadge } from '../common/Badge';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import { InfoBanner, PageHeader, SectionCard } from '../common/ui';
import {
  CalendarDays,
  Check,
  HeartPulse,
  Loader2,
  LogOut,
  Pencil,
  Phone,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  UserRound,
} from 'lucide-react';

interface ProfileViewProps {
  onNavigate: (view: string) => void;
}

const PERMISSION_LABELS: Partial<Record<Permission, string>> = {
  view_dashboard: 'مشاهده داشبورد',
  manage_appointments: 'مدیریت نوبت‌ها',
  view_my_appointments: 'مشاهده نوبت‌های شخصی',
  book_appointment: 'رزرو نوبت',
  cancel_appointment: 'لغو نوبت',
  reschedule_appointment: 'تغییر زمان نوبت',
  manage_patients: 'مدیریت پرونده بیماران',
  view_patient_dossier: 'مشاهده پرونده بیمار',
  view_own_health_record: 'مشاهده پرونده سلامت خود',
  view_clinical_records: 'مشاهده پرونده بالینی بیماران',
  manage_clinical_records: 'ثبت یادداشت و وضعیت دندان',
  rate_visits: 'ثبت رضایت پس از ویزیت',
  manage_doctors: 'مدیریت پزشکان',
  view_doctors: 'مشاهده پزشکان',
  manage_services: 'مدیریت خدمات',
  view_services: 'مشاهده خدمات',
  manage_staff: 'مدیریت پرسنل و دسترسی‌ها',
  use_agent: 'استفاده از دستیار',
  view_api_spec: 'مشاهده مستندات فنی',
  manage_settings: 'تنظیمات سیستم',
};

export const ProfileView: React.FC<ProfileViewProps> = ({ onNavigate }) => {
  const { currentUser, logout, refreshUser } = useAuth();

  // Self-service rename state (PUT /users/me — display name only).
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState('');
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);

  if (!currentUser) {
    return (
      <div className="d-page">
        <InfoBanner tone="warning" title="حساب کاربری در دسترس نیست">
          برای مشاهده اطلاعات حساب، دوباره وارد شوید.
        </InfoBanner>
      </div>
    );
  }

  const openRename = () => {
    setEditName(currentUser.full_name);
    setNameError(null);
    setNameSaved(false);
    setEditOpen(true);
  };

  const submitRename = async () => {
    const clean = editName.trim();
    if (clean.length < 3) {
      setNameError('نام باید حداقل ۳ نویسه باشد.');
      return;
    }
    setSavingName(true);
    try {
      await apiClient.updateMyProfile({ full_name: clean });
      await refreshUser();
      setEditOpen(false);
      setNameSaved(true);
    } catch (err: any) {
      setNameError(err.message || 'ثبت تغییر نام ناکام ماند');
    } finally {
      setSavingName(false);
    }
  };

  const role = currentUser.role;
  const roleMeta = ROLE_LABELS[role];
  const permissions = ROLE_PERMISSIONS[role] || [];
  const linkedName = currentUser.patient?.full_name || currentUser.doctor?.full_name;
  const linkedId = currentUser.patient?.id ?? currentUser.doctor?.id;
  const patientRecords =
    currentUser.patients && currentUser.patients.length > 0
      ? currentUser.patients
      : currentUser.patient
        ? [currentUser.patient]
        : [];

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="حساب من"
        subtitle="اطلاعات حساب، نقش دسترسی و مجوزهای شما."
        action={
          <Button
            variant="danger"
            size="md"
            onClick={logout}
            icon={<LogOut className="w-4 h-4" />}
          >
            خروج از حساب
          </Button>
        }
      />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <SectionCard className="xl:col-span-2">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-5">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-[3px] bg-surface-muted border border-line text-ink-soft flex items-center justify-center text-[24px] font-extrabold shrink-0">
                {currentUser.full_name.charAt(0)}
              </div>
              <div className="min-w-0">
                <h2 className="text-[18px] font-extrabold text-ink leading-7">
                  {currentUser.full_name}
                </h2>
                <p className="text-caption text-muted mt-1">{roleMeta?.subtitle}</p>
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <RoleBadge role={role} />
                  <Badge variant={currentUser.is_active ? 'success' : 'neutral'} dot>
                    {currentUser.is_active ? 'حساب فعال' : 'حساب غیرفعال'}
                  </Badge>
                  <button
                    type="button"
                    onClick={openRename}
                    className="inline-flex items-center gap-1 text-caption font-semibold text-primary hover:underline"
                  >
                    <Pencil className="w-3 h-3" />
                    ویرایش نام
                  </button>
                </div>
              </div>
            </div>
            <div className="d-soft-teal px-4 py-3 text-center shrink-0">
              <div className="text-caption text-muted">نقش دسترسی</div>
              <div className="text-small font-bold text-primary-deep mt-1">{roleMeta?.title}</div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-6">
            <div className="rounded-[4px] border border-line p-4">
              <div className="flex items-center gap-2 text-caption text-faint">
                <Phone className="w-3.5 h-3.5" />
                شماره تماس
              </div>
              <div className="text-small font-semibold text-ink mt-2 tabular-nums" dir="ltr">
                {toPersianDigits(currentUser.phone)}
              </div>
            </div>
            <div className="rounded-[4px] border border-line p-4">
              <div className="flex items-center gap-2 text-caption text-faint">
                <UserRound className="w-3.5 h-3.5" />
                پرونده متصل
              </div>
              <div className="text-small font-semibold text-ink mt-2">
                {linkedName ? linkedName : 'متصل نیست'}
                {linkedId && (
                  <span className="text-caption text-faint font-normal mr-2">
                    شناسه {toPersianDigits(linkedId)}
                  </span>
                )}
              </div>
            </div>
          </div>

          {role === 'patient' && patientRecords.length > 0 && (
            <div className="mt-5 rounded-[4px] border border-line p-4">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2 text-caption text-faint">
                  <UserRound className="w-3.5 h-3.5" />
                  پرونده‌های این حساب
                </div>
                <span className="text-caption text-primary font-bold">
                  {toPersianDigits(patientRecords.length)} پرونده
                </span>
              </div>
              <div className="space-y-2">
                {patientRecords.map((patient) => (
                  <div
                    key={patient.id}
                    className="flex items-center justify-between gap-2 rounded-[3px] bg-surface-muted border border-line-soft px-3 py-2"
                  >
                    <span className="text-caption font-semibold text-ink truncate">
                      {patient.full_name}
                    </span>
                    <span className="shrink-0 text-caption text-primary-deep bg-primary-soft rounded-full px-2 py-0.5">
                      {patient.is_account_holder ? 'صاحب حساب' : 'عضو خانواده'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-5 pt-4 border-t border-line-soft flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => onNavigate('appointments')} icon={<CalendarDays className="w-3.5 h-3.5" />}>
              نوبت‌های من
            </Button>
            {role === 'admin' && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onNavigate('system-health')}
                icon={<ShieldCheck className="w-3.5 h-3.5" />}
              >
                سلامت سامانه
              </Button>
            )}
            {role === 'patient' && (
              <Button variant="outline" size="sm" onClick={() => onNavigate('health')} icon={<HeartPulse className="w-3.5 h-3.5" />}>
                پرونده سلامت من
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => onNavigate('agent')} icon={<Sparkles className="w-3.5 h-3.5" />}>
              دستیار
            </Button>
            {role === 'patient' && (
              <Button variant="secondary" size="sm" onClick={() => onNavigate('team')} icon={<Stethoscope className="w-3.5 h-3.5" />}>
                پزشکان و خدمات
              </Button>
            )}
          </div>
        </SectionCard>

        <SectionCard title="دسترسی‌های این نقش" subtitle="کنترل نهایی دسترسی در سرور اعمال می‌شود">
          <div className="flex items-center gap-2 mb-4">
            <span className="d-icon-ring w-9 h-9">
              <ShieldCheck className="w-4 h-4" />
            </span>
            <div>
              <div className="text-small font-bold text-ink">{roleMeta?.title}</div>
              <div className="text-caption text-faint">{toPersianDigits(permissions.length)} دسترسی تعریف‌شده</div>
            </div>
          </div>
          <div className="space-y-2">
            {permissions.map((permission) => (
              <div key={permission} className="flex items-start gap-2 text-caption text-muted">
                <Check className="w-3.5 h-3.5 text-primary shrink-0 mt-0.5" />
                <span>{PERMISSION_LABELS[permission] || permission}</span>
              </div>
            ))}
          </div>
          <div className="d-soft-info px-3 py-2.5 mt-4 text-caption text-info leading-5">
            نام نمایشی را از دکمه «ویرایش نام» تغییر دهید. شماره تماس، هویت ورود شماست و
            تغییر آن فقط از طریق پذیرش کلینیک انجام می‌شود.
          </div>
        </SectionCard>
      </div>

      <Modal
        isOpen={editOpen}
        onClose={() => setEditOpen(false)}
        title="ویرایش نام نمایشی"
        subtitle="این نام در نوبت‌ها، گفتگو با دستیار و پرونده شما نمایش داده می‌شود."
        maxWidth="sm"
      >
        <div className="space-y-3">
          <label className="block">
            <span className="text-caption font-semibold text-muted">نام و نام خانوادگی</span>
            <input
              type="text"
              value={editName}
              onChange={(event) => setEditName(event.target.value)}
              maxLength={150}
              className="mt-1.5 w-full h-10 rounded-[3px] border border-line bg-surface px-3 text-small text-ink focus:outline-none focus:ring-2 focus:ring-primary/30"
              autoFocus
            />
          </label>
          {nameError && (
            <p className="text-caption text-danger">{nameError}</p>
          )}
          <div className="flex items-center gap-2 pt-1">
            <Button
              size="sm"
              onClick={() => void submitRename()}
              disabled={savingName || editName.trim().length < 3}
              icon={savingName ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : undefined}
            >
              ذخیره تغییر
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditOpen(false)}>
              انصراف
            </Button>
          </div>
        </div>
      </Modal>

      {nameSaved && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[110] rounded-[3px] bg-primary text-on-accent text-small font-semibold px-4 py-2 d-fade">
          نام شما با موفقیت به‌روزرسانی شد ✓
        </div>
      )}
    </div>
  );
};
