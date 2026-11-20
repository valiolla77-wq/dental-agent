import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { ROLE_LABELS } from '../../utils/rbac';
import {
  LayoutDashboard,
  CalendarDays,
  Users,
  Stethoscope,
  Sparkles,
  LogOut,
  X,
  FileBarChart2,
  UserCog,
  Home,
  CalendarPlus,
  UserRound,
  HeartPulse,
  ChevronLeft,
  DoorOpen,
} from 'lucide-react';
import { UserRole } from '../../types';

interface SidebarProps {
  currentView: string;
  onSelectView: (view: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

interface NavItem {
  id: string;
  label: string;
  icon: React.ElementType;
}

const WORKSPACE_LABELS: Record<UserRole, string> = {
  admin: 'فضای کار مدیر کلینیک',
  receptionist: 'فضای کار پذیرش',
  doctor: 'فضای کار پزشک',
  patient: 'فضای کار بیمار',
};

function getNavigation(role: UserRole): NavItem[] {
  if (role === 'admin') {
    return [
      { id: 'dashboard', label: 'گزارش روز کلینیک', icon: LayoutDashboard },
      { id: 'reception', label: 'پذیرش امروز', icon: DoorOpen },
      { id: 'agent', label: 'دستیار هوشمند', icon: Sparkles },
      { id: 'appointments', label: 'نوبت‌ها', icon: CalendarDays },
      { id: 'patients', label: 'بیماران و پرونده‌ها', icon: Users },
      { id: 'doctors', label: 'پزشکان و شیفت‌ها', icon: Stethoscope },
      { id: 'reports', label: 'گزارش‌ها', icon: FileBarChart2 },
      { id: 'staff', label: 'پرسنل و دسترسی‌ها', icon: UserCog },
      { id: 'profile', label: 'حساب من', icon: UserRound },
    ];
  }
  if (role === 'receptionist') {
    return [
      { id: 'dashboard', label: 'میز پذیرش', icon: LayoutDashboard },
      { id: 'reception', label: 'پذیرش امروز', icon: DoorOpen },
      { id: 'agent', label: 'دستیار پذیرش', icon: Sparkles },
      { id: 'appointments', label: 'نوبت‌ها', icon: CalendarDays },
      { id: 'patients', label: 'اطلاعات مراجعان', icon: Users },
      { id: 'profile', label: 'حساب من', icon: UserRound },
    ];
  }
  if (role === 'doctor') {
    return [
      { id: 'dashboard', label: 'برنامه من', icon: CalendarDays },
      { id: 'reception', label: 'پذیرش امروز', icon: DoorOpen },
      { id: 'agent', label: 'دستیار پزشک', icon: Sparkles },
      { id: 'patients', label: 'بیماران مجاز', icon: Users },
      { id: 'profile', label: 'حساب من', icon: UserRound },
    ];
  }
  return [
    { id: 'dashboard', label: 'خانه من', icon: Home },
    { id: 'team', label: 'رزرو نوبت', icon: CalendarPlus },
    { id: 'appointments', label: 'نوبت‌های من', icon: CalendarDays },
    { id: 'health', label: 'پرونده سلامت من', icon: HeartPulse },
    { id: 'agent', label: 'دستیار من', icon: Sparkles },
    { id: 'profile', label: 'حساب من', icon: UserRound },
  ];
}

const ToothMark: React.FC<{ className?: string }> = ({ className = 'w-5 h-5' }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
  >
    <path d="M12 4.2c-1.5 0-2.4.8-4.6.8-2.2 0-3.4 1.6-3.1 3.8.2 1.6 1 2.8 1.4 4.5.4 1.7.5 3.3 1.1 4.8.4 1.1 1 1.9 1.8 1.9 1.1 0 1.5-1.1 1.8-2.8.3-1.3.5-2 1.6-2s1.3.7 1.6 2c.3 1.7.7 2.8 1.8 2.8.8 0 1.4-.8 1.8-1.9.6-1.5.7-3.1 1.1-4.8.4-1.7 1.2-2.9 1.4-4.5.3-2.2-.9-3.8-3.1-3.8-2.2 0-3.1-.8-4.6-.8Z" />
    <path d="M9.2 6.1c.8-.4 1.6-.5 2.8-.5" strokeWidth="1.1" opacity=".55" />
  </svg>
);

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onSelectView,
  mobileOpen,
  onCloseMobile,
}) => {
  const { currentUser, logout } = useAuth();
  const role = currentUser?.role || 'patient';
  const navItems = getNavigation(role);

  const handleNavClick = (viewId: string) => {
    onSelectView(viewId);
    onCloseMobile();
  };

  const sidebarContent = (
    <div className="d-sidebar flex flex-col h-full">
      {/* Brand */}
      <div className="h-[74px] px-5 flex items-center justify-between border-b border-line">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-[11px] bg-primary text-on-accent flex items-center justify-center shadow-[0_4px_12px_-4px_rgba(8,127,131,0.5)]">
            <ToothMark className="w-5 h-5" />
          </div>
          <div>
            <div className="text-heading font-extrabold text-ink leading-5 tracking-tight">
              دنتال ایجنت
            </div>
            <div className="text-caption text-faint mt-0.5">مراقبت هوشمند، لبخند ماندگار</div>
          </div>
        </div>
        {mobileOpen && (
          <button
            type="button"
            onClick={onCloseMobile}
            className="p-1.5 text-faint hover:text-ink rounded-[8px] lg:hidden"
            aria-label="بستن منو"
          >
            <X className="w-4.5 h-4.5" />
          </button>
        )}
      </div>

      <nav className="flex-1 px-3.5 py-4 overflow-y-auto">
        <div className="d-workspace-pill mb-3">{WORKSPACE_LABELS[role]}</div>
        <div className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentView === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => handleNavClick(item.id)}
                className={`d-nav-item ${isActive ? 'active' : ''}`}
              >
                <Icon className="w-[17px] h-[17px]" />
                <span className="flex-1 text-right">{item.label}</span>
                {isActive && <ChevronLeft className="w-3.5 h-3.5 !text-primary" />}
              </button>
            );
          })}
        </div>

        {/* Decision-boundary card — matches the design's purple panel. */}
        <button
          type="button"
          onClick={() => handleNavClick('agent')}
          className="d-ai-card w-full text-right p-3.5 mt-6 hover:shadow-[0_4px_14px_-8px_rgba(98,96,182,0.45)] transition-shadow"
        >
          <div className="flex items-start gap-2">
            <span className="w-7 h-7 rounded-full bg-surface/70 border border-ai-line text-ai flex items-center justify-center shrink-0">
              <Sparkles className="w-3.5 h-3.5" />
            </span>
            <div className="min-w-0">
              <div className="text-small font-bold text-ai leading-5">
                پیشنهاد با ما؛ تصمیم با شما
              </div>
              <p className="text-caption text-muted leading-5 mt-1">
                هیچ تغییری بدون تأیید صریح شما ثبت نمی‌شود.
              </p>
            </div>
          </div>
        </button>
      </nav>

      {/* User footer */}
      <div className="p-3.5 border-t border-line">
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-9 h-9 rounded-full bg-primary-soft border border-primary-line text-primary-deep flex items-center justify-center text-small font-bold shrink-0">
              {currentUser?.full_name ? currentUser.full_name.charAt(0) : 'U'}
            </div>
            <div className="min-w-0">
              <div className="text-small font-bold text-ink truncate">
                {currentUser?.full_name || 'کاربر سیستم'}
              </div>
              <div className="text-caption text-faint mt-0.5 truncate">
                {ROLE_LABELS[role]?.title || role}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={logout}
            title="خروج از حساب کاربری"
            aria-label="خروج از حساب کاربری"
            className="p-2 rounded-[9px] text-faint hover:text-danger hover:bg-danger-soft transition-colors shrink-0"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <aside className="d-sidebar hidden lg:block sticky top-0 h-screen z-20">
        {sidebarContent}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="fixed inset-0 bg-ink-deep/45 backdrop-blur-[2px]"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <div className="fixed inset-y-0 right-0 z-50 shadow-2xl">{sidebarContent}</div>
        </div>
      )}
    </>
  );
};
