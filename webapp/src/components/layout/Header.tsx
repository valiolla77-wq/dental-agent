import React, { useEffect, useRef, useState } from 'react';
import { CLINIC_NAME } from '../../config';
import { useAuth } from '../../context/AuthContext';
import { useClinic } from '../../context/ClinicContext';
import { ROLE_LABELS } from '../../utils/rbac';
import { formatToJalali } from '../../utils/persianDate';
import { NotificationBell } from '../notifications/NotificationBell';
import { PRIMARY_NAV_COUNT, getNavigation } from './navConfig';
import {
  Bot,
  ChevronDown,
  LogOut,
  Menu,
  MoreHorizontal,
  WifiOff,
} from 'lucide-react';

interface HeaderProps {
  currentView: string;
  onSelectView: (view: string) => void;
  onOpenMobileMenu: () => void;
}

const ToothMark: React.FC<{ className?: string }> = ({ className = 'w-4 h-4' }) => (
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
  </svg>
);

/**
 * The single navigation surface: brand, primary destinations, then utilities.
 * The sidebar survives only as the drawer below the lg breakpoint.
 */
export const Header: React.FC<HeaderProps> = ({
  currentView,
  onSelectView,
  onOpenMobileMenu,
}) => {
  const { currentUser, logout } = useAuth();
  const { healthState, refreshHealth, setAgentDrawerOpen } = useClinic();
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement | null>(null);

  const role = currentUser?.role || 'patient';
  const today = formatToJalali(new Date(), true);
  const serverDown = healthState.status === 'disconnected';

  const navItems = getNavigation(role);
  const primary = navItems.slice(0, PRIMARY_NAV_COUNT);
  const overflow = navItems.slice(PRIMARY_NAV_COUNT);
  const overflowActive = overflow.some((item) => item.id === currentView);

  useEffect(() => {
    if (!moreOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) {
        setMoreOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMoreOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [moreOpen]);

  const go = (view: string) => {
    onSelectView(view);
    setMoreOpen(false);
  };

  return (
    <header className="d-topbar sticky top-0 z-40">
      <div className="d-topbar-inner">
        <button
          type="button"
          onClick={onOpenMobileMenu}
          className="d-util-btn d-util-btn--menu"
          aria-label="باز کردن منو"
        >
          <Menu className="w-4 h-4" />
        </button>

        <div className="d-brand">
          <span className="d-brand-mark">
            <ToothMark className="w-4 h-4" />
          </span>
          <span className="min-w-0 hidden sm:block">
            <span className="d-brand-name block">دنتال ایجنت</span>
            <span className="d-brand-sub block truncate">{CLINIC_NAME}</span>
          </span>
        </div>

        <nav className="d-topnav" aria-label="ناوبری اصلی">
          {primary.map((item) => {
            const Icon = item.icon;
            const active = currentView === item.id;
            return (
              <button
                key={item.id}
                type="button"
                className={`d-topnav-item ${active ? 'active' : ''}`}
                aria-current={active ? 'page' : undefined}
                onClick={() => go(item.id)}
              >
                <Icon className="w-4 h-4" />
                {item.short || item.label}
              </button>
            );
          })}

          {overflow.length > 0 && (
            <div className="relative" ref={moreRef}>
              <button
                type="button"
                className={`d-topnav-more ${overflowActive ? 'active' : ''}`}
                aria-expanded={moreOpen}
                aria-haspopup="menu"
                onClick={() => setMoreOpen((open) => !open)}
              >
                <MoreHorizontal className="w-4 h-4" />
                بیشتر
                <ChevronDown className="w-3 h-3" />
              </button>

              {moreOpen && (
                <div className="d-menu" role="menu">
                  {overflow.map((item) => {
                    const Icon = item.icon;
                    const active = currentView === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="menuitem"
                        className={`d-menu-item ${active ? 'active' : ''}`}
                        onClick={() => go(item.id)}
                      >
                        <Icon className="w-4 h-4" />
                        {item.label}
                      </button>
                    );
                  })}
                  <div className="d-menu-sep" />
                  <button type="button" role="menuitem" className="d-menu-item" onClick={logout}>
                    <LogOut className="w-4 h-4" />
                    خروج از حساب
                  </button>
                </div>
              )}
            </div>
          )}
        </nav>

        <div className="d-topbar-util">
          <span className="d-role-chip">
            امروز، {today}
          </span>

          {serverDown && (
            <button
              type="button"
              onClick={() => void refreshHealth()}
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-[3px] border border-danger-line bg-danger-soft text-caption font-semibold text-danger"
              aria-label="ارتباط با سرور قطع است؛ بررسی دوباره"
              title="بررسی دوبارهٔ ارتباط با سرور"
            >
              <WifiOff className="w-3 h-3" aria-hidden="true" />
              قطع ارتباط
            </button>
          )}

          <NotificationBell onNavigate={onSelectView} />

          <button
            type="button"
            onClick={() => setAgentDrawerOpen(true)}
            className="d-util-btn"
            aria-label="باز کردن دستیار"
            title="دستیار هوشمند"
          >
            <Bot className="w-4 h-4" />
          </button>

          <button
            type="button"
            onClick={() => go('profile')}
            className="d-user-chip"
            title="حساب من"
          >
            <span className="w-7 h-7 rounded-[3px] bg-primary text-on-accent flex items-center justify-center text-caption font-bold shrink-0">
              {currentUser?.full_name ? currentUser.full_name.charAt(0) : 'U'}
            </span>
            <span className="min-w-0">
              <span className="d-user-chip-name block">
                {currentUser?.full_name || 'کاربر سیستم'}
              </span>
              <span className="d-user-chip-role block">{ROLE_LABELS[role]?.title || role}</span>
            </span>
          </button>
        </div>
      </div>
    </header>
  );
};
