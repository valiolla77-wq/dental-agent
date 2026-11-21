import React, { useState } from 'react';
import { WifiOff } from 'lucide-react';
import { Button } from './Button';
import { CLINIC_NAME } from '../../config';

interface ConnectionLostViewProps {
  onRetry: () => Promise<void> | void;
}

/** Full-page state when the saved session cannot be checked (server unreachable). */
export const ConnectionLostView: React.FC<ConnectionLostViewProps> = ({ onRetry }) => {
  const [retrying, setRetrying] = useState(false);

  const retry = async () => {
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center px-4" dir="rtl">
      <div className="w-full max-w-[400px] rounded-[4px] border border-line bg-surface p-7 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-danger-soft text-danger">
          <WifiOff className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="text-small text-faint">{CLINIC_NAME}</div>
        <h1 className="mt-1 text-[18px] font-extrabold text-ink">ارتباط با سرور برقرار نشد</h1>
        <p className="mt-2 text-body leading-7 text-muted">
          اتصال اینترنت را بررسی کنید. نشست شما حفظ شده است و بعد از برقراری ارتباط می‌توانید ادامه
          دهید.
        </p>
        <Button className="mt-5 w-full" size="lg" onClick={retry} isLoading={retrying}>
          تلاش دوباره
        </Button>
      </div>
    </div>
  );
};
