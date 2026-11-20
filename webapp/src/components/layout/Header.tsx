import React from 'react';
import { CLINIC_NAME } from '../../config';
import { useAuth } from '../../context/AuthContext';
import { useClinic } from '../../context/ClinicContext';
import { ROLE_LABELS } from '../../utils/rbac';
import { formatToJalali } from '../../utils/persianDate';
import { NotificationBell } from '../notifications/NotificationBell';
import { Bot, Building2, Menu, ShieldCheck, WifiOff } from 'lucide-react';

interface HeaderProps {
  onOpenMobileMenu: () => void;
  onNavigate: (view: string) => void;
}

export const Header: React.FC<HeaderProps> = ({
  onOpenMobileMenu,
  onNavigate,
}) => {
  const { currentUser } = useAuth();
  const { healthState, refreshHealth, setAgentDrawerOpen } = useClinic();

  const role = currentUser?.role || 'patient';
  const today = formatToJalali(new Date(), true);
  const serverDown = healthState.status === 'disconnected';

  return (
    <header className="h-[74px] bg-surface/95 backdrop-blur border-b border-line sticky top-0 z-30">
      <div className="h-full px-4 sm:px-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <button
            type="button"
            onClick={onOpenMobileMenu}
            className="lg:hidden p-2 -mr-1 text-muted hover:text-ink hover:bg-canvas rounded-[9px]"
            aria-label="باز کردن منو"
          >
            <Menu className="w-5 h-5" />
          </button>

          <div className="w-9 h-9 rounded-[10px] bg-primary-soft border border-primary-line text-primary hidden sm:flex items-center justify-center shrink-0">
            <Building2 className="w-4.5 h-4.5" />
          </div>
          <div className="min-w-0">
            <div className="text-small sm:text-body font-bold text-ink truncate leading-5">
              {CLINIC_NAME}
            </div>
            <div className="text-caption text-faint mt-0.5 truncate">امروز، {today}</div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <NotificationBell onNavigate={onNavigate} />

          {serverDown && (
            <button
              type="button"
              onClick={() => void refreshHealth()}
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-full border border-danger-line bg-danger-soft text-small font-semibold text-danger transition-opacity hover:opacity-80"
              title="بررسی دوبارهٔ ارتباط با سرور"
            >
              <WifiOff className="w-3 h-3" aria-hidden="true" />
              ارتباط با سرور قطع است
            </button>
          )}

          <div className="hidden sm:inline-flex items-center gap-1.5 h-8 px-2.5 rounded-[9px] bg-canvas border border-line text-small font-semibold text-muted">
            <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" />
            {ROLE_LABELS[role]?.title || role}
          </div>

          <button
            type="button"
            onClick={() => setAgentDrawerOpen(true)}
            className="w-8 h-8 rounded-[9px] bg-ai-soft border border-ai-line text-ai hover:bg-[#E7E6FA] flex items-center justify-center transition-colors"
            aria-label="باز کردن دستیار"
            title="دستیار هوشمند"
          >
            <Bot className="w-4 h-4" />
          </button>
        </div>
      </div>

    </header>
  );
};
