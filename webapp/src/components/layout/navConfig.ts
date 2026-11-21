import type { LucideIcon } from 'lucide-react';
import {
  CalendarDays,
  CalendarPlus,
  DoorOpen,
  FileBarChart2,
  HeartPulse,
  Home,
  LayoutDashboard,
  Sparkles,
  Stethoscope,
  UserCog,
  UserRound,
  Users,
} from 'lucide-react';
import type { UserRole } from '../../types';

export interface NavItem {
  id: string;
  /** Full label, used in the drawer and menus. */
  label: string;
  /** Shorter label for the horizontal bar, where width is scarce. */
  short?: string;
  icon: LucideIcon;
}

export const WORKSPACE_LABELS: Record<UserRole, string> = {
  admin: 'فضای کار مدیر کلینیک',
  receptionist: 'فضای کار پذیرش',
  doctor: 'فضای کار پزشک',
  patient: 'فضای کار بیمار',
};

/**
 * One navigation model for every surface. The top bar shows the first five
 * destinations; the rest live under «بیشتر». Order matters: it is the path a
 * receptionist walks through in a shift.
 */
export function getNavigation(role: UserRole): NavItem[] {
  if (role === 'admin') {
    return [
      { id: 'dashboard', label: 'گزارش روز کلینیک', short: 'داشبورد', icon: LayoutDashboard },
      { id: 'reception', label: 'پذیرش امروز', short: 'پذیرش', icon: DoorOpen },
      { id: 'appointments', label: 'نوبت‌ها', icon: CalendarDays },
      { id: 'patients', label: 'بیماران و پرونده‌ها', short: 'بیماران', icon: Users },
      { id: 'agent', label: 'دستیار هوشمند', short: 'دستیار', icon: Sparkles },
      { id: 'doctors', label: 'پزشکان و شیفت‌ها', short: 'پزشکان', icon: Stethoscope },
      { id: 'reports', label: 'گزارش‌ها', icon: FileBarChart2 },
      { id: 'staff', label: 'پرسنل و دسترسی‌ها', short: 'پرسنل', icon: UserCog },
      { id: 'profile', label: 'حساب من', icon: UserRound },
    ];
  }
  if (role === 'receptionist') {
    return [
      { id: 'dashboard', label: 'میز پذیرش', icon: LayoutDashboard },
      { id: 'reception', label: 'پذیرش امروز', short: 'پذیرش', icon: DoorOpen },
      { id: 'appointments', label: 'نوبت‌ها', icon: CalendarDays },
      { id: 'patients', label: 'اطلاعات مراجعان', short: 'مراجعان', icon: Users },
      { id: 'agent', label: 'دستیار پذیرش', short: 'دستیار', icon: Sparkles },
      { id: 'profile', label: 'حساب من', icon: UserRound },
    ];
  }
  if (role === 'doctor') {
    return [
      { id: 'dashboard', label: 'برنامه من', icon: CalendarDays },
      { id: 'reception', label: 'پذیرش امروز', short: 'پذیرش', icon: DoorOpen },
      { id: 'patients', label: 'بیماران مجاز', short: 'بیماران', icon: Users },
      { id: 'agent', label: 'دستیار پزشک', short: 'دستیار', icon: Sparkles },
      { id: 'profile', label: 'حساب من', icon: UserRound },
    ];
  }
  return [
    { id: 'dashboard', label: 'خانه من', icon: Home },
    { id: 'team', label: 'رزرو نوبت', icon: CalendarPlus },
    { id: 'appointments', label: 'نوبت‌های من', short: 'نوبت‌ها', icon: CalendarDays },
    { id: 'health', label: 'پرونده سلامت من', short: 'پرونده من', icon: HeartPulse },
    { id: 'agent', label: 'دستیار من', short: 'دستیار', icon: Sparkles },
    { id: 'profile', label: 'حساب من', icon: UserRound },
  ];
}

/** How many destinations stay in the bar before the «بیشتر» menu takes over. */
export const PRIMARY_NAV_COUNT = 5;
