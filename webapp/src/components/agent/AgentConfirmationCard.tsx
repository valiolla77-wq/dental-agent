import React, { useState } from 'react';
import { ChatSuggestedAppointment } from '../../types';
import { Button } from '../common/Button';
import {
  AlertTriangle,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  FileText,
  ShieldCheck,
  Stethoscope,
  X,
  XCircle,
} from 'lucide-react';
import { formatTimeFa, formatToJalali } from '../../utils/persianDate';

interface AgentConfirmationCardProps {
  token: string;
  promptText?: string | null;
  suggestedAppointments?: ChatSuggestedAppointment[];
  confirmed?: boolean;
  rejected?: boolean;
  outcomeUnknown?: boolean;
  onConfirm: (token: string) => Promise<void>;
  onReject: (token: string) => Promise<void>;
}

/**
 * Two-step confirmation card. The token is intentionally not rendered: it is
 * an implementation detail of the server-side action, not user-facing data.
 */
export const AgentConfirmationCard: React.FC<AgentConfirmationCardProps> = ({
  token,
  promptText,
  suggestedAppointments,
  confirmed,
  rejected,
  outcomeUnknown,
  onConfirm,
  onReject,
}) => {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const run = async (action: 'confirm' | 'reject') => {
    setIsSubmitting(true);
    try {
      if (action === 'confirm') {
        await onConfirm(token);
      } else {
        await onReject(token);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const isResolved = Boolean(confirmed || rejected || outcomeUnknown);

  return (
    <div className="mt-3 rounded-[4px] border border-warn-line bg-warn-soft p-3 text-ink space-y-2.5">
      <div className="flex items-start gap-2 pb-2 border-b border-warn-line">
        <AlertTriangle className="w-3.5 h-3.5 text-warn shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="text-caption font-bold text-warn">تأیید اجرای عملیات</div>
          <div className="text-caption text-warn/75 mt-0.5">
            این تغییر فقط با تأیید صریح شما ثبت می‌شود
          </div>
        </div>
        <ShieldCheck className="w-3.5 h-3.5 text-warn/60 shrink-0" />
      </div>

      <p className="text-caption leading-6 text-ink">
        {promptText || 'این عملیات وضعیت سامانه را تغییر می‌دهد. آیا آن را تأیید می‌کنید؟'}
      </p>

      {suggestedAppointments && suggestedAppointments.length > 0 && (
        <div className="space-y-2">
          {suggestedAppointments.map((appointment, index) => (
            <div
              key={`${appointment.doctor_name}-${appointment.appointment_date}-${index}`}
              className="grid grid-cols-1 sm:grid-cols-2 gap-2 bg-surface p-2.5 rounded-[3px] border border-warn-line"
            >
              <div className="flex items-center gap-1.5 text-caption">
                <Stethoscope className="w-3 h-3 text-faint shrink-0" />
                <span className="text-muted">پزشک:</span>
                <span className="font-semibold truncate">{appointment.doctor_name}</span>
              </div>
              <div className="flex items-center gap-1.5 text-caption">
                <FileText className="w-3 h-3 text-faint shrink-0" />
                <span className="text-muted">خدمت:</span>
                <span className="font-semibold truncate">{appointment.service_name}</span>
              </div>
              <div className="flex items-center gap-1.5 text-caption">
                <Calendar className="w-3 h-3 text-faint shrink-0" />
                <span className="text-muted">تاریخ:</span>
                <span className="font-medium">{formatToJalali(appointment.appointment_date, true)}</span>
              </div>
              <div className="flex items-center gap-1.5 text-caption">
                <Clock className="w-3 h-3 text-faint shrink-0" />
                <span className="text-muted">ساعت:</span>
                <span className="font-semibold tabular-nums">
                  {formatTimeFa(appointment.appointment_time)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {!isResolved ? (
        <div className="flex items-center justify-end gap-2 pt-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => run('reject')}
            disabled={isSubmitting}
            icon={<X className="w-3.5 h-3.5" />}
          >
            انصراف
          </Button>
          <Button
            size="sm"
            onClick={() => run('confirm')}
            isLoading={isSubmitting}
            icon={<Check className="w-3.5 h-3.5" />}
          >
            تأیید و اجرا
          </Button>
        </div>
      ) : outcomeUnknown ? (
        <div role="status" className="flex items-start gap-1.5 rounded-[3px] bg-warn-soft border border-warn-line px-2.5 py-2 text-caption font-semibold leading-5 text-warn">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          نتیجه مشخص نیست؛ برای جلوگیری از ثبت تکراری دوباره ارسال نمی‌شود.
        </div>
      ) : confirmed ? (
        <div className="flex items-center gap-1.5 rounded-[3px] bg-primary-soft border border-primary-line px-2.5 py-2 text-caption font-semibold text-primary-deep">
          <CheckCircle2 className="w-3.5 h-3.5" />
          تأیید شد و انجام شد.
        </div>
      ) : (
        <div className="flex items-center gap-1.5 rounded-[3px] bg-canvas border border-line px-2.5 py-2 text-caption font-semibold text-muted">
          <XCircle className="w-3.5 h-3.5" />
          عملیات لغو شد؛ هیچ تغییری ثبت نشد.
        </div>
      )}
    </div>
  );
};
