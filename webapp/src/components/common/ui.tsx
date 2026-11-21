import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from './Button';

/* ------------------------------------------------------------------ header */

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  action?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  eyebrow,
  action,
}) => (
  <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
    <div className="min-w-0">
      {eyebrow && (
        <div className="text-caption font-bold text-primary mb-1">{eyebrow}</div>
      )}
      <h1 className="d-title">{title}</h1>
      {subtitle && <p className="d-subtitle">{subtitle}</p>}
    </div>
    {action && <div className="flex items-center gap-2 shrink-0 flex-wrap pb-1">{action}</div>}
  </div>
);

/* ------------------------------------------------------------------- stats */

interface StatCardProps {
  /* Kept so existing call sites stay valid; the paper system prints numbers,
   * not icon bubbles, so the icon is intentionally not rendered. */
  icon?: React.ReactNode;
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  /** @deprecated tone no longer paints the figure; kept for call-site compatibility. */
  tone?: 'teal' | 'ai' | 'danger' | 'warn' | 'soft';
  onClick?: () => void;
  className?: string;
}

/**
 * A printed cell: caption, figure, note. Inside `.d-stat-band` the cells share
 * one rule, so a row of four reads as a single ledger line.
 */
export const StatCard: React.FC<StatCardProps> = ({
  label,
  value,
  hint,
  onClick,
  className = '',
}) => (
  <div
    className={`d-stat ${className} ${
      onClick ? 'cursor-pointer transition-colors hover:bg-[#fbf8f2]' : ''
    }`}
    onClick={onClick}
    role={onClick ? 'button' : undefined}
    tabIndex={onClick ? 0 : undefined}
  >
    <div className="text-caption font-medium leading-5 text-muted">{label}</div>
    <div className="d-stat-value">{value}</div>
    {hint && <div className="text-caption leading-5 text-faint">{hint}</div>}
  </div>
);

/* ------------------------------------------------------------------ section */

interface SectionCardProps {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  noPadding?: boolean;
}

export const SectionCard: React.FC<SectionCardProps> = ({
  title,
  subtitle,
  action,
  children,
  className = '',
  bodyClassName = '',
  noPadding = false,
}) => (
  <section className={`d-card min-w-0 ${className}`}>
    {(title || action) && (
      <div className="flex items-start justify-between gap-3 px-5 sm:px-6 pt-4 pb-3 border-b border-line">
        <div className="min-w-0">
          {title && <h2 className="d-section-title">{title}</h2>}
          {subtitle && <p className="d-section-sub">{subtitle}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    )}
    <div className={`${noPadding ? '' : 'p-5 sm:p-6'} ${bodyClassName}`}>{children}</div>
  </section>
);

/* ---------------------------------------------------------------- segmented */

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  count?: number;
}

interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className = '',
}: SegmentedProps<T>) {
  return (
    <div className={`d-segment ${className}`} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
          className={value === option.value ? 'active' : ''}
        >
          {option.label}
          {typeof option.count === 'number' && (
            <span className="mr-1 opacity-70">({option.count})</span>
          )}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ avatar */

export const Avatar: React.FC<{ name: string; size?: 'sm' | 'md' | 'lg' }> = ({
  name,
  size = 'md',
}) => {
  const sizes = {
    sm: 'w-7 h-7 text-caption',
    md: 'w-9 h-9 text-small',
    lg: 'w-12 h-12 text-heading',
  };
  const initial = (name || '؟').trim().charAt(0);
  return (
    <span
      className={`${sizes[size]} rounded-[3px] bg-surface-muted border border-line text-ink-soft font-bold flex items-center justify-center shrink-0`}
    >
      {initial}
    </span>
  );
};

/* ----------------------------------------------------------------- banners */

interface InfoBannerProps {
  tone?: 'teal' | 'ai' | 'warning' | 'danger' | 'info';
  icon?: React.ReactNode;
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

const BANNER_TONES: Record<string, string> = {
  teal: 'd-soft-teal text-primary-deep',
  ai: 'd-ai-card text-ai',
  warning: 'd-soft-warn text-warn',
  danger: 'd-soft-danger text-danger',
  info: 'd-note text-ink-soft',
};

export const InfoBanner: React.FC<InfoBannerProps> = ({
  tone = 'teal',
  icon,
  title,
  children,
  action,
  className = '',
}) => (
  <div className={`${BANNER_TONES[tone]} px-4 py-3.5 ${className}`}>
    <div className="flex items-start gap-2.5">
      {icon && <span className="shrink-0 mt-0.5">{icon}</span>}
      <div className="min-w-0 flex-1">
        {title && <div className="text-small font-bold mb-0.5">{title}</div>}
        <div className="text-caption leading-6 opacity-90">{children}</div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  </div>
);

export const ErrorBanner: React.FC<{ message: string; onRetry?: () => void }> = ({
  message,
  onRetry,
}) => (
  <div className="d-soft-danger px-4 py-3 text-small text-danger flex items-start gap-2">
    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
    <span className="leading-6 flex-1">{message}</span>
    {onRetry && (
      <Button
        size="sm"
        variant="ghost"
        onClick={onRetry}
        className="text-danger hover:bg-surface/60"
        icon={<RefreshCw className="w-3.5 h-3.5" />}
      >
        تلاش دوباره
      </Button>
    )}
  </div>
);

export const LoadingPanel: React.FC<{ message?: string }> = ({
  message = 'در حال دریافت داده‌ها از سرور...',
}) => (
  <div className="py-12 flex flex-col items-center justify-center gap-3">
    <div className="w-7 h-7 rounded-full border-2 border-primary-line border-t-primary animate-spin" />
    <span className="text-small text-muted">{message}</span>
  </div>
);

/* ------------------------------------------------------------------ charts */

export interface BarDatum {
  label: string;
  value: number;
  highlight?: boolean;
}

export const BarChart: React.FC<{
  data: BarDatum[];
  height?: number;
  valueFormatter?: (value: number) => string;
}> = ({ data, height = 150, valueFormatter }) => {
  const max = Math.max(1, ...data.map((item) => item.value));
  return (
    <div className="w-full">
      <div className="flex items-end justify-between gap-2 sm:gap-3" style={{ height }}>
        {data.map((item, index) => {
          const ratio = item.value / max;
          return (
            <div
              key={`${item.label}-${index}`}
              className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5"
            >
              <span className="text-caption font-semibold text-muted tabular-nums">
                {valueFormatter ? valueFormatter(item.value) : item.value}
              </span>
              <div
                className={`w-full max-w-[42px] rounded-t-[6px] transition-all duration-500 ${
                  item.highlight
                    ? 'bg-primary'
                    : item.value === 0
                    ? 'bg-line-soft'
                    : 'bg-primary-line'
                }`}
                style={{
                  height: `${Math.max(ratio * 100, item.value === 0 ? 3 : 12)}%`,
                }}
                title={`${item.label}: ${item.value}`}
              />
            </div>
          );
        })}
      </div>
      <div className="flex items-start justify-between gap-2 sm:gap-3 mt-2">
        {data.map((item, index) => (
          <div
            key={`${item.label}-label-${index}`}
            className={`min-w-0 flex-1 truncate text-center text-[11px] leading-4 sm:text-caption ${
              item.highlight ? 'text-primary font-bold' : 'text-faint'
            }`}
          >
            {item.label}
          </div>
        ))}
      </div>
    </div>
  );
};

export interface DonutDatum {
  label: string;
  value: number;
  color: string;
}

export const DonutChart: React.FC<{
  data: DonutDatum[];
  size?: number;
  centerValue?: string;
  centerLabel?: string;
}> = ({ data, size = 142, centerValue, centerLabel }) => {
  const total = data.reduce((sumValue, item) => sumValue + item.value, 0);
  let cursor = 0;
  const stops = data.map((item) => {
    const start = total ? (cursor / total) * 100 : 0;
    cursor += item.value;
    const end = total ? (cursor / total) * 100 : 0;
    return `${item.color} ${start}% ${end}%`;
  });
  const background =
    total > 0
      ? `conic-gradient(${stops.join(', ')})`
      : 'conic-gradient(#f4efe4 0% 100%)';
  return (
    <div
      className="d-donut"
      style={{ width: size, height: size, background }}
      role="img"
      aria-label={data.map((item) => `${item.label}: ${item.value}`).join('، ')}
    >
      <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
        {centerValue && (
          <span className="text-[20px] font-extrabold text-ink leading-none">{centerValue}</span>
        )}
        {centerLabel && <span className="text-caption text-faint mt-1.5">{centerLabel}</span>}
      </div>
    </div>
  );
};

export const ProgressBar: React.FC<{ value: number; max: number; soft?: boolean }> = ({
  value,
  max,
  soft,
}) => (
  <div className="d-bar-track">
    <div
      className={`d-bar-fill ${soft ? 'soft' : ''}`}
      style={{ width: `${max > 0 ? Math.min(100, (value / max) * 100) : 0}%` }}
    />
  </div>
);
