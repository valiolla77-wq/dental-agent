import React from 'react';
import { ChatOptionItem } from '../../types';
import {
  Calendar,
  ChevronLeft,
  Clock,
  Stethoscope,
  User as UserIcon,
  Users,
} from 'lucide-react';
import { formatTimeFa, formatToJalali, toPersianDigits } from '../../utils/persianDate';

interface AgentOptionCardsProps {
  options: ChatOptionItem[];
  disabled: boolean;
  onSelect: (numericMessage: string) => void;
  compact?: boolean;
}

function optionSubtitle(
  option: ChatOptionItem,
  compact: boolean
): React.ReactNode | null {
  const iconSize = compact ? 'w-3 h-3' : 'w-3.5 h-3.5';
  if (option.kind === 'slot_time' || option.kind === 'appointment') {
    const parts: React.ReactNode[] = [];
    if (option.appointment_date) {
      parts.push(
        <span key="date" className="flex items-center gap-1">
          <Calendar className={`${iconSize} text-faint`} />
          {formatToJalali(option.appointment_date)}
        </span>
      );
    }
    if (option.appointment_time) {
      parts.push(
        <span key="time" className="flex items-center gap-1 tabular-nums">
          <Clock className={`${iconSize} text-faint`} />
          {formatTimeFa(option.appointment_time)}
        </span>
      );
    }
    if (option.doctor_name) {
      parts.push(
        <span key="doc" className="flex items-center gap-1">
          <Stethoscope className={`${iconSize} text-faint`} />
          {option.doctor_name}
        </span>
      );
    }
    return parts.length ? parts : null;
  }
  if (option.kind === 'doctor' && option.specialty) return option.specialty;
  if (option.kind === 'service' && option.description) return option.description;
  if (option.kind === 'patient') {
    return (
      <span className="flex items-center gap-1">
        <Users className={`${iconSize} text-faint`} />
        {option.is_account_holder ? 'صاحب حساب' : 'عضو خانواده'}
      </span>
    );
  }
  return null;
}

/**
 * Clickable cards for the conversation's active option set. The selection is
 * sent back as «گزینه N»; the server resolves N against the persisted set, so a
 * stale card cannot select another row.
 */
export const AgentOptionCards: React.FC<AgentOptionCardsProps> = ({
  options,
  disabled,
  onSelect,
  compact = false,
}) => {
  if (!options.length) return null;
  const patientSelection = options.every((option) => option.kind === 'patient');

  return (
    <div className={compact ? 'mt-2 space-y-1.5' : 'mt-3 space-y-2'}>
      <div className="text-caption font-semibold text-faint">
        {patientSelection
          ? 'این درخواست برای کدام بیمار انجام شود؟'
          : 'برای انتخاب، روی گزینه موردنظر بزنید:'}
      </div>
      <div className={compact ? 'space-y-1' : 'space-y-1.5'}>
        {options.map((option) => {
          const subtitle = optionSubtitle(option, compact);
          return (
            <button
              key={`${option.index}-${option.label}`}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(`گزینه ${option.index}`)}
              className={`group w-full text-right rounded-[10px] border border-primary-line bg-[#F3FBF9] hover:bg-primary-soft hover:border-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-between gap-2 ${
                compact ? 'p-2' : 'p-2.5'
              }`}
            >
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  <span
                    className={`shrink-0 rounded-full bg-primary text-on-accent font-bold flex items-center justify-center ${
                      compact ? 'w-6 h-6 text-caption' : 'w-7 h-7 text-small'
                    }`}
                  >
                    {toPersianDigits(option.index)}
                  </span>
                  <span
                    className={`truncate font-semibold text-ink group-hover:text-primary-deep ${
                      compact ? 'text-caption' : 'text-caption'
                    }`}
                  >
                    {option.kind === 'doctor' && (
                      <UserIcon className="w-3 h-3 inline ml-1 text-primary" />
                    )}
                    {option.label}
                  </span>
                </span>
                {subtitle && (
                  <span
                    className={`mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-caption text-muted ${
                      compact ? 'pr-7' : 'pr-8'
                    }`}
                  >
                    {subtitle}
                  </span>
                )}
              </span>
              <ChevronLeft className="shrink-0 w-3.5 h-3.5 text-primary/50 group-hover:text-primary" />
            </button>
          );
        })}
      </div>
    </div>
  );
};
