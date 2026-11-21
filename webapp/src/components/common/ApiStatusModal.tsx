import React, { useState } from 'react';
import { Modal } from './Modal';
import { Button } from './Button';
import { useClinic } from '../../context/ClinicContext';
import { apiClient } from '../../api/client';
import { AlertCircle, CheckCircle2, RefreshCw, Server } from 'lucide-react';

interface ApiStatusModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Connection diagnostics for the clinic backend.
 *
 * The API base URL is a build-time setting (`VITE_API_BASE_URL`), so this
 * panel reports it read-only and only offers a live health re-check. It used
 * to expose runtime URL switching and a demo-mode reset, which the current
 * client intentionally no longer supports.
 */
export const ApiStatusModal: React.FC<ApiStatusModalProps> = ({ isOpen, onClose }) => {
  const { healthState, refreshHealth, refreshAll } = useClinic();
  const [isChecking, setIsChecking] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleTestConnection = async () => {
    setIsChecking(true);
    setFeedback(null);
    try {
      const res = await apiClient.checkHealth();
      setFeedback(
        res.status === 'connected'
          ? 'ارتباط با سرویس FastAPI با موفقیت برقرار شد.'
          : 'پاسخی از سرور دریافت نشد. از اجرای بک‌اند پایتون روی این پورت مطمئن شوید.'
      );
      await refreshHealth();
    } catch (err: any) {
      setFeedback(`خطا در اتصال: ${err.message}`);
    } finally {
      setIsChecking(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="وضعیت اتصال به سرویس"
      subtitle="بررسی سلامت بک‌اند و فهرست سرویس‌های در دسترس"
      maxWidth="lg"
    >
      <div className="space-y-5 text-caption">
        <div
          className={`p-3.5 rounded-[3px] border flex items-start gap-3 ${
            healthState.status === 'connected'
              ? 'bg-primary-soft border-primary-line text-primary-deep'
              : 'bg-danger-soft border-danger-line text-danger'
          }`}
        >
          {healthState.status === 'connected' ? (
            <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          )}
          <div className="leading-relaxed space-y-1">
            <div className="font-semibold text-sm">
              {healthState.status === 'connected'
                ? 'متصل به سرور FastAPI (آنلاین)'
                : 'عدم پاسخگویی سرور بک‌اند'}
            </div>
            <p className="text-caption">
              {healthState.status === 'connected'
                ? `درخواست‌ها به آدرس ${healthState.serverUrl} ارسال می‌شوند.`
                : 'سرور پاسخ نمی‌دهد. آن را با «uvicorn app.main:app --reload» اجرا کنید.'}
            </p>
            {healthState.latencyMs !== undefined && healthState.status === 'connected' && (
              <p className="text-caption tabular-nums">
                پینگ: {healthState.latencyMs} میلی‌ثانیه
              </p>
            )}
          </div>
        </div>

        <div>
          <label className="block text-caption font-medium text-muted mb-1.5">
            آدرس ریشه سرویس (از تنظیمات ساخت)
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={apiClient.getBaseUrl() || '(همان میزبان فعلی)'}
              readOnly
              className="flex-1 text-caption tabular-nums bg-canvas border border-line rounded-[3px] px-3 py-2 text-muted"
              dir="ltr"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleTestConnection()}
              isLoading={isChecking}
              icon={<RefreshCw className="w-3.5 h-3.5" />}
            >
              آزمون اتصال
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void refreshAll()}
              icon={<RefreshCw className="w-3.5 h-3.5" />}
            >
              به‌روزرسانی داده‌ها
            </Button>
          </div>
        </div>

        {feedback && (
          <div className="text-caption p-2.5 rounded-[3px] bg-canvas text-muted">
            {feedback}
          </div>
        )}

        <div className="border-t border-line-soft pt-4 space-y-2">
          <h4 className="text-caption font-semibold text-ink flex items-center gap-1.5">
            <Server className="w-4 h-4 text-faint" />
            سرویس‌های اصلی
          </h4>
          <div
            className="space-y-1 text-caption text-muted bg-canvas p-3 rounded-[3px] border border-line font-mono max-h-40 overflow-y-auto"
            dir="ltr"
          >
            <div>POST /auth/staff/login &nbsp;|&nbsp; POST /auth/otp/request</div>
            <div>GET&nbsp; /auth/me</div>
            <div>GET&nbsp; /patients/ &nbsp;|&nbsp; POST /patients/</div>
            <div>GET&nbsp; /appointments/ &nbsp;|&nbsp; GET /appointments/day</div>
            <div>POST /appointments/{'{id}'}/check-in | start | complete | no-show</div>
            <div>GET&nbsp; /clinical/patients/{'{id}'}</div>
            <div>POST /clinical/patients/{'{id}'}/prescriptions</div>
            <div>POST /clinical/patients/{'{id}'}/plan-items</div>
            <div>GET&nbsp; /reports/dashboard</div>
            <div>POST /agent/chat</div>
          </div>
        </div>

        <div className="flex items-center justify-end border-t border-line-soft pt-4">
          <Button size="sm" onClick={onClose}>
            بستن
          </Button>
        </div>
      </div>
    </Modal>
  );
};
