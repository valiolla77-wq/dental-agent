import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { ROLE_LABELS } from '../../utils/rbac';
import { LogOut, X, ChevronLeft } from 'lucide-react';
import { WORKSPACE_LABELS, getNavigation } from './navConfig';

interface SidebarProps {
  currentView: string;
  onSelectView: (view: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

/**
 * The drawer. On desktop the top bar carries navigation; this panel only
 * exists below the lg breakpoint, where a horizontal bar cannot hold the
 * destinations.
 */
export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onSelectView,
  mobileOpen,
  onCloseMobile,
}) => {
  const { currentUser, logout } = useAuth();
  const role = currentUser?.role || 'patient';
  const navItems = getNavigation(role);

  if (!mobileOpen) return null;

  const handleNavClick = (viewId: string) => {
    onSelectView(viewId);
    onCloseMobile();
  };

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div
        className="fixed inset-0 bg-ink-deep/40"
        onClick={onCloseMobile}
        aria-hidden="true"
      />
      <aside className="d-sidebar fixed inset-y-0 right-0 z-50 flex flex-col h-full shadow-[0_0_40px_rgba(20,16,12,0.18)]">
        <div className="h-[62px] px-5 flex items-center justify-between border-b border-line">
          <div className="min-w-0">
            <div className="d-brand-name">دنتال ایجنت</div>
            <div className="text-caption text-faint mt-0.5">{WORKSPACE_LABELS[role]}</div>
          </div>
          <button
            type="button"
            onClick={onCloseMobile}
            className="p-1.5 text-faint hover:text-ink rounded-[3px]"
            aria-label="بستن منو"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <nav className="flex-1 px-3.5 py-4 overflow-y-auto">
          <div className="space-y-0.5">
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
                  {isActive && <ChevronLeft className="w-3.5 h-3.5" />}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => handleNavClick('agent')}
            className="d-card w-full text-right p-3.5 mt-6 hover:border-ai-line"
          >
            <div className="text-small font-bold text-ai">پیشنهاد با ما؛ تصمیم با شما</div>
            <p className="text-caption text-muted leading-5 mt-1">
              هیچ تغییری بدون تأیید صریح شما ثبت نمی‌شود.
            </p>
          </button>
        </nav>

        <div className="p-3.5 border-t border-line">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-9 h-9 rounded-[3px] bg-surface-muted border border-line text-ink-soft flex items-center justify-center text-small font-bold shrink-0">
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
              className="p-2 rounded-[3px] text-faint hover:text-danger hover:bg-danger-soft transition-colors shrink-0"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
};
