import React from 'react';
import { AppointmentStatus, RecordStatus, UserRole } from '../../types';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'teal' | 'ai' | 'neutral';
  size?: 'sm' | 'md';
  className?: string;
  dot?: boolean;
}

const DOT_COLORS: Record<string, string> = {
  default: '#98A4B4',
  neutral: '#98A4B4',
  success: '#087F83',
  teal: '#087F83',
  warning: '#946318',
  danger: '#B73F52',
  info: '#2F5D8A',
  ai: '#6260B6',
};

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  className = '',
  dot = false,
}) => {
  const variantStyles = {
    default: 'bg-canvas text-muted border-line',
    neutral: 'bg-canvas text-muted border-line',
    success: 'bg-primary-soft text-primary-deep border-primary-line',
    warning: 'bg-warn-soft text-warn border-warn-line',
    danger: 'bg-danger-soft text-danger border-danger-line',
    info: 'bg-info-soft text-info border-info-line',
    teal: 'bg-primary-soft text-primary border-primary-line',
    ai: 'bg-ai-soft text-ai border-ai-line',
  };

  const sizeStyles = {
    sm: 'text-caption px-2.5 h-[22px]',
    md: 'text-small px-3 h-[26px]',
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-semibold rounded-full border leading-none ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
      {dot && (
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{ background: DOT_COLORS[variant] }}
        />
      )}
      {children}
    </span>
  );
};

export const AppointmentStatusBadge: React.FC<{ status: AppointmentStatus }> = ({ status }) => {
  switch (status) {
    case 'confirmed':
      return (
        <Badge variant="success" dot>
          تأییدشده
        </Badge>
      );
    case 'scheduled':
      return (
        <Badge variant="info" dot>
          زمان‌بندی‌شده
        </Badge>
      );
    case 'in_progress':
      return (
        <Badge variant="teal" dot>
          در حال درمان
        </Badge>
      );
    case 'completed':
      return (
        <Badge variant="default" dot>
          تکمیل‌شده
        </Badge>
      );
    case 'cancelled':
      return (
        <Badge variant="danger" dot>
          لغوشده
        </Badge>
      );
    case 'no_show':
      return (
        <Badge variant="warning" dot>
          عدم مراجعه
        </Badge>
      );
    case 'rescheduled':
      return (
        <Badge variant="warning" dot>
          تغییر زمان
        </Badge>
      );
    default:
      return <Badge>{status}</Badge>;
  }
};

export const RoleBadge: React.FC<{ role: UserRole }> = ({ role }) => {
  switch (role) {
    case 'admin':
      return <Badge variant="ai">مدیر کلینیک</Badge>;
    case 'receptionist':
      return <Badge variant="info">پذیرش</Badge>;
    case 'doctor':
      return <Badge variant="teal">دندان‌پزشک</Badge>;
    case 'patient':
      return <Badge variant="default">بیمار</Badge>;
    default:
      return <Badge>{role}</Badge>;
  }
};

/** Server-derived record completeness (mission §7): 'complete' | 'incomplete'. */
export const RecordStatusBadge: React.FC<{ status: RecordStatus }> = ({ status }) => {
  if (status === 'incomplete') {
    return (
      <Badge variant="warning" dot>
        نیازمند تکمیل
      </Badge>
    );
  }
  return (
    <Badge variant="success" dot>
      پرونده کامل
    </Badge>
  );
};
