import React, { useCallback, useEffect, useState } from 'react';
import {
  Bot,
  Clock,
  Database,
  MessageSquare,
  RefreshCw,
  Server,
} from 'lucide-react';
import { apiClient } from '../../api/client';
import { SystemHealth } from '../../types';
import { toPersianDigits } from '../../utils/persianDate';
import { Button } from '../common/Button';
import { ErrorBanner, LoadingPanel, PageHeader, SectionCard } from '../common/ui';

const SMS_LABELS: Record<string, string> = {
  fake: 'شبیه‌ساز محلی',
  smsir: 'SMS.ir',
  bale: 'پیام‌رسان بله',
};

const ASSISTANT_LABELS: Record<string, string> = {
  ollama: 'Ollama (محلی)',
  openrouter: 'OpenRouter',
  openai: 'سرویس سازگار با OpenAI',
  unconfigured: 'پیکربندی نشده',
};

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${toPersianDigits(seconds)} ثانیه`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${toPersianDigits(minutes)} دقیقه`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${toPersianDigits(hours)} ساعت و ${toPersianDigits(minutes % 60)} دقیقه`;
  }
  return `${toPersianDigits(Math.floor(hours / 24))} روز و ${toPersianDigits(hours % 24)} ساعت`;
}

interface HealthRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: 'ok' | 'warn' | 'bad';
}

const TONE_CLASSES: Record<HealthRowProps['tone'], string> = {
  ok: 'text-success',
  warn: 'text-warn',
  bad: 'text-danger',
};

const TONE_DOTS: Record<HealthRowProps['tone'], string> = {
  ok: 'bg-success',
  warn: 'bg-warn',
  bad: 'bg-danger',
};

const HealthRow: React.FC<HealthRowProps> = ({ icon, label, value, tone }) => (
  <div className="flex items-start gap-2.5 py-3 min-w-0">
    <span className="shrink-0 mt-0.5 text-faint" aria-hidden="true">
      {icon}
    </span>
    <div className="min-w-0 flex-1">
      <div className="text-caption text-faint">{label}</div>
      <div className={`mt-1 flex items-center gap-1.5 text-small font-bold ${TONE_CLASSES[tone]}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${TONE_DOTS[tone]}`} aria-hidden="true" />
        <span className="truncate">{value}</span>
      </div>
    </div>
  </div>
);

/**
 * Admin-only operational view.
 *
 * It intentionally shows provider *names* and booleans, never API keys, base
 * URLs, database paths, or patient data.
 */
export const SystemHealthView: React.FC = () => {
  const [data, setData] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await apiClient.getSystemHealth());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'دریافت وضعیت سامانه ممکن نشد.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="d-page">
      <PageHeader
        eyebrow="مدیریت کلینیک"
        title="سلامت سامانه"
        subtitle="وضعیت عملیاتی سرویس‌های کلینیک. این صفحه فقط برای مدیر نمایش داده می‌شود."
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            isLoading={loading}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            بررسی دوباره
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && !data && <LoadingPanel message="در حال دریافت وضعیت سامانه..." />}

      {data && (
        <div className="space-y-4">
          <SectionCard
            title="وضعیت کلی"
            subtitle={
              data.status === 'ok'
                ? 'همهٔ سرویس‌های ضروری در دسترس هستند.'
                : 'حداقل یکی از سرویس‌های ضروری در دسترس نیست.'
            }
            action={
              <span
                className={`inline-flex items-center gap-1.5 text-caption font-bold ${
                  data.status === 'ok' ? 'text-success' : 'text-warn'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    data.status === 'ok' ? 'bg-success' : 'bg-warn'
                  }`}
                  aria-hidden="true"
                />
                {data.status === 'ok' ? 'سالم' : 'نیازمند بررسی'}
              </span>
            }
            noPadding
          >
            <div className="divide-y divide-line-soft">
              <div className="px-5 sm:px-6">
                <HealthRow
                  icon={<Database className="w-3.5 h-3.5" />}
                  label="پایگاه داده"
                  value={data.database === 'ok' ? 'در دسترس' : 'در دسترس نیست'}
                  tone={data.database === 'ok' ? 'ok' : 'bad'}
                />
              </div>
              <div className="px-5 sm:px-6">
                <HealthRow
                  icon={<MessageSquare className="w-3.5 h-3.5" />}
                  label="ارسال پیامک / کد ورود"
                  value={SMS_LABELS[data.sms_provider] || data.sms_provider}
                  tone={data.sms_provider === 'fake' ? 'warn' : 'ok'}
                />
              </div>
              <div className="px-5 sm:px-6">
                <HealthRow
                  icon={<Bot className="w-3.5 h-3.5" />}
                  label="دستیار هوشمند"
                  value={ASSISTANT_LABELS[data.assistant_provider] || data.assistant_provider}
                  tone={data.assistant_configured ? 'ok' : 'warn'}
                />
              </div>
              <div className="px-5 sm:px-6">
                <HealthRow
                  icon={<Clock className="w-3.5 h-3.5" />}
                  label="مدت فعالیت سرویس"
                  value={formatUptime(data.uptime_seconds)}
                  tone="ok"
                />
              </div>
            </div>
          </SectionCard>

          <SectionCard title="نسخهٔ سرویس">
            <div className="flex flex-wrap items-center justify-between gap-3 text-small text-muted">
              <span className="inline-flex items-center gap-2">
                <Server className="w-3.5 h-3.5 text-faint" aria-hidden="true" />
                نسخهٔ فعال
              </span>
              <span className="font-bold text-ink tabular-nums">{data.version}</span>
            </div>
            <div className="d-note px-3 py-2.5 mt-4 text-caption leading-5">
              این صفحه فقط نام سرویس‌ها و وضعیت آن‌ها را نشان می‌دهد؛ کلیدها، آدرس‌های داخلی و
              اطلاعات بیماران نمایش داده نمی‌شوند.
            </div>
          </SectionCard>
        </div>
      )}
    </div>
  );
};
