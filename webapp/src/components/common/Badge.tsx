import React from 'react';
import { AppointmentStatus, RecordStatus, UserRole } from '../../types';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'teal' | 'ai' | 'neutral';
  size?: 'sm' | 'md';
  className?: string;
  dot?: boolean;
}

/**
 * Paper badges are not pills: they are coloured text with a dot. In a dense
 * table a row of pills reads as noise; a dot and a word read as a fact.
 */
export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  className = '',
  dot = false,
}) => {
  const variantStyles = {
    default: 'text-muted',
    neutral: 'text-muted',
    success: 'text-success',
    warning: 'text-warn',
    danger: 'text-danger',
    info: 'text-info',
    teal: 'text-primary',
    ai: 'text-ai',
  };

  const sizeStyles = {
    sm: 'text-caption h-[20px]',
    md: 'text-small h-[24px]',
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-semibold leading-none ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
      {dot && <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-current" aria-hidden="true" />}
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
