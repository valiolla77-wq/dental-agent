import React, { useEffect, useState } from 'react';
import { RefreshCw, WifiOff, X } from 'lucide-react';
import { useClinic } from '../../context/ClinicContext';
import { Button } from './Button';
import { toPersianDigits } from '../../utils/persianDate';

/**
 * Human-readable connection banner.
 *
 * The technical diagnostics live behind the admin-only «سلامت سامانه» page.
 * Patients and reception staff only need to know three things: the connection
 * is down, when it was last checked, and that they can retry safely.
 */
export const ConnectionBanner: React.FC = () => {
  const { healthState, refreshHealth } = useClinic();
  const [dismissed, setDismissed] = useState(false);
  const [retrying, setRetrying] = useState(false);

  // A dismissed banner returns only after a real reconnect + new outage, so a
  // failing background poll cannot reopen it every few seconds.
  useEffect(() => {
    if (healthState.status === 'connected') {
      setDismissed(false);
    }
  }, [healthState.status]);

  if (healthState.status !== 'disconnected' || dismissed) {
    return null;
  }

  const checked = new Date(healthState.lastChecked);
  const lastCheckedLabel = Number.isNaN(checked.getTime())
    ? 'نامشخص'
    : toPersianDigits(
        `${String(checked.getHours()).padStart(2, '0')}:${String(checked.getMinutes()).padStart(2, '0')}`
      );

  const retry = async () => {
    setRetrying(true);
    try {
      await refreshHealth();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="border-b border-danger-line bg-danger-soft" role="status">
      <div className="px-4 sm:px-6 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 text-small text-danger">
        <WifiOff className="w-4 h-4 shrink-0" aria-hidden="true" />
        <span className="font-semibold">ارتباط با سامانه برقرار نیست.</span>
        <span className="text-caption text-danger">
          آخرین بررسی: {lastCheckedLabel}
        </span>
        <div className="ms-auto flex items-center gap-1.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void retry()}
            isLoading={retrying}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            تلاش دوباره
          </Button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="p-1.5 rounded-[3px] text-danger hover:bg-danger-soft"
            aria-label="بستن پیام قطعی ارتباط"
          >
            <X className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
};
