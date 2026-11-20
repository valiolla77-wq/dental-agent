import React, { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '../../api/client';
import { NotificationItem } from '../../types';
import { formatToJalali, formatTimeFa } from '../../utils/persianDate';
import {
  AlarmClock,
  Bell,
  CalendarDays,
  CalendarPlus,
  CheckCheck,
  ClipboardPlus,
  Loader2,
  Megaphone,
} from 'lucide-react';

const KIND_META: Record<
  NotificationItem['kind'],
  { icon: React.ElementType; ring: string }
> = {
  appointment_booked: {
    icon: CalendarPlus,
    ring: 'bg-primary-soft text-primary-deep border-primary-line',
  },
  appointment_cancelled: {
    icon: CalendarDays,
    ring: 'bg-danger-soft text-danger border-danger-line',
  },
  appointment_rescheduled: {
    icon: CalendarDays,
    ring: 'bg-[#EEF4FB] text-info border-[#D7E4F4]',
  },
  reminder: {
    icon: AlarmClock,
    ring: 'bg-[#FFF7E6] text-[#9A6700] border-[#F0D48A]',
  },
  clinical_entry: {
    icon: ClipboardPlus,
    ring: 'bg-[#F3F0FF] text-ai border-ai-line',
  },
  system: {
    icon: Megaphone,
    ring: 'bg-canvas text-muted border-line',
  },
};

/** Which app view a notification kind deep-links to. */
const KIND_TARGET_VIEW: Partial<Record<NotificationItem['kind'], string>> = {
  appointment_booked: 'appointments',
  appointment_cancelled: 'appointments',
  appointment_rescheduled: 'appointments',
  reminder: 'appointments',
  clinical_entry: 'health',
};

interface NotificationBellProps {
  onNavigate: (view: string) => void;
}

/**
 * Header bell: unread badge, lazy dropdown inbox and mark-all-read.
 * The unread counter polls gently (60s) so staff stay aware of patient
 * self-service actions without any websocket infrastructure.
 */
export const NotificationBell: React.FC<NotificationBellProps> = ({
  onNavigate,
}) => {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await apiClient.getNotifications();
      setItems(data.items);
      setUnread(data.unread_count);
    } catch {
      // Silent: a failed poll must never break the header.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const handleClick = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const toggleOpen = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      await refresh();
      setLoading(false);
    }
  };

  const openItem = async (item: NotificationItem) => {
    if (!item.is_read) {
      try {
        await apiClient.markNotificationRead(item.id);
      } catch {
        // ignore — the badge fixes itself on the next poll
      }
    }
    setOpen(false);
    const target = KIND_TARGET_VIEW[item.kind];
    if (target) onNavigate(target);
    void refresh();
  };

  const markAllRead = async () => {
    try {
      await apiClient.markAllNotificationsRead();
      await refresh();
    } catch {
      // ignore
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => void toggleOpen()}
        className="relative w-8 h-8 rounded-[9px] bg-surface border border-line text-muted hover:text-primary hover:border-primary-line flex items-center justify-center transition-colors"
        aria-label="اعلان‌ها"
        title="اعلان‌ها"
      >
        <Bell className="w-4 h-4" />
        {unread > 0 && (
          <span className="absolute -top-1.5 -left-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-on-accent text-caption font-extrabold flex items-center justify-center tabular-nums leading-none">
            {unread > 9 ? '۹+' : new Intl.NumberFormat('fa-IR').format(unread)}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 mt-2 w-[320px] sm:w-[360px] max-w-[calc(100vw-1.5rem)] rounded-[16px] border border-line bg-surface shadow-[0_24px_80px_-24px_rgba(23,43,71,0.35)] z-50 overflow-hidden d-fade">
          <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-line-soft">
            <div className="text-small font-bold text-ink">اعلان‌ها</div>
            {unread > 0 && (
              <button
                type="button"
                onClick={() => void markAllRead()}
                className="inline-flex items-center gap-1 text-caption font-semibold text-primary hover:underline"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                خواندن همه
              </button>
            )}
          </div>

          <div className="max-h-[380px] overflow-y-auto">
            {loading && items.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-8 text-caption text-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                در حال دریافت...
              </div>
            ) : items.length === 0 ? (
              <div className="py-10 text-center">
                <Bell className="w-6 h-6 text-line-strong mx-auto mb-2" />
                <p className="text-caption text-muted">
                  اعلان جدیدی ندارید.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-line-soft">
                {items.map((item) => {
                  const meta = KIND_META[item.kind] || KIND_META.system;
                  const Icon = meta.icon;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => void openItem(item)}
                        className={`w-full text-right px-4 py-3 flex items-start gap-2.5 hover:bg-[#FBFDFD] transition-colors ${
                          item.is_read ? '' : 'bg-[#F7FBFA]'
                        }`}
                      >
                        <span
                          className={`w-8 h-8 rounded-[10px] border flex items-center justify-center shrink-0 ${meta.ring}`}
                        >
                          <Icon className="w-4 h-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="text-small font-bold text-ink truncate">
                              {item.title}
                            </span>
                            {!item.is_read && (
                              <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                            )}
                          </span>
                          {item.body && (
                            <span className="block text-caption text-muted leading-5 mt-1 line-clamp-2">
                              {item.body}
                            </span>
                          )}
                          <span className="block text-caption text-faint mt-1">
                            {formatToJalali(item.created_at)}
                            {' • '}
                            {formatTimeFa(
                              new Date(item.created_at)
                                .toTimeString()
                                .slice(0, 8)
                            )}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
